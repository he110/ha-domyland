"""Config flow интеграции Domyland."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DomylandApiClient, DomylandAuthError, DomylandError
from .const import (
    CONF_CUSTOMER_ID,
    CONF_CUSTOMER_NAME,
    CONF_ENABLE_CAMERAS,
    CONF_JWT,
    CONF_YANDEX_TOKEN,
    DEFAULT_ENABLE_CAMERAS,
    DOMAIN,
    YANDEX_AUTHORIZE_URL,
)
from .coordinator import DomylandConfigEntry

_LOGGER = logging.getLogger(__name__)

CONF_TOKEN_INPUT = "token_input"

# Яндекс-токен формата y0_..., либо вся строка редиректа с #access_token=...
_TOKEN_RE = re.compile(r"(y[0-3]_[A-Za-z0-9_-]{20,})")


def _extract_yandex_token(raw: str) -> str | None:
    """Достать Яндекс-токен из вставленного значения.

    Пользователь может вставить сам токен (y0_...) или целиком URL, на который
    его перекинул Яндекс после логина (`...#access_token=y0_...&...`).
    """
    raw = raw.strip()
    if not raw:
        return None
    # 1) URL с фрагментом access_token
    if "access_token=" in raw:
        parsed = urlparse(raw)
        frag = parse_qs(parsed.fragment) or parse_qs(parsed.query)
        if token := frag.get("access_token"):
            return token[0]
    # 2) Голый токен где-то в строке
    if match := _TOKEN_RE.search(raw):
        return match.group(1)
    return None


class DomylandConfigFlow(ConfigFlow, domain=DOMAIN):
    """Логин через Яндекс → обмен на JWT domyland."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: DomylandConfigEntry | None = None

    async def _validate_and_build(
        self, yandex_token: str
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Проверить токен, обменять на JWT, вернуть (данные_entry, инфо).

        Возвращает None и заполняет self._errors при ошибке.
        """
        session = async_get_clientsession(self.hass)
        client = DomylandApiClient(session, yandex_token)
        auth_data = await client.exchange_yandex_token()
        customer = await client.get_current_customer()
        entry_data = {
            CONF_YANDEX_TOKEN: yandex_token,
            CONF_JWT: client.jwt,
            CONF_CUSTOMER_ID: auth_data.get("customerId") or customer.get("id"),
            CONF_CUSTOMER_NAME: customer.get("shortName") or customer.get("fullName"),
        }
        return entry_data, customer

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = _extract_yandex_token(user_input[CONF_TOKEN_INPUT])
            if not token:
                errors["base"] = "invalid_token_format"
            else:
                try:
                    entry_data, _ = await self._validate_and_build(token)
                except DomylandAuthError:
                    errors["base"] = "invalid_auth"
                except DomylandError:
                    _LOGGER.exception("Ошибка при настройке Domyland")
                    errors["base"] = "cannot_connect"
                else:
                    customer_id = entry_data[CONF_CUSTOMER_ID]
                    await self.async_set_unique_id(str(customer_id))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=entry_data.get(CONF_CUSTOMER_NAME) or "Domyland",
                        data=entry_data,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN_INPUT): str}),
            errors=errors,
            description_placeholders={"auth_url": YANDEX_AUTHORIZE_URL},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        if user_input is not None:
            token = _extract_yandex_token(user_input[CONF_TOKEN_INPUT])
            if not token:
                errors["base"] = "invalid_token_format"
            else:
                try:
                    entry_data, _ = await self._validate_and_build(token)
                except DomylandAuthError:
                    errors["base"] = "invalid_auth"
                except DomylandError:
                    _LOGGER.exception("Ошибка при повторной авторизации Domyland")
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry,
                        data={**self._reauth_entry.data, **entry_data},
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN_INPUT): str}),
            errors=errors,
            description_placeholders={"auth_url": YANDEX_AUTHORIZE_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: DomylandConfigEntry,
    ) -> DomylandOptionsFlow:
        return DomylandOptionsFlow()


class DomylandOptionsFlow(OptionsFlow):
    """Опции: включение/выключение камер."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENABLE_CAMERAS, default=current): bool,
                }
            ),
        )
