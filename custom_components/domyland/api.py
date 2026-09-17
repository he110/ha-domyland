"""Клиент customer-api.domyland.ru."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    APP_NAME,
    APP_VERSION,
    ORIGINAL_APP_NAME,
    REQUEST_TIMEOUT,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class DomylandError(Exception):
    """Общая ошибка API Domyland."""


class DomylandAuthError(DomylandError):
    """Токен невалиден/протух — нужен повторный логин (reauth)."""


class DomylandApiClient:
    """Тонкий асинхронный клиент вокруг customer-api.domyland.ru.

    JWT (Authorization) и Яндекс-токен (x-yandex-oauth) обязательны в каждом
    запросе. Дом выбирается заголовками placeId/buildingId — отдельного
    серверного «switch» нет, поэтому они передаются на уровне вызова.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        yandex_token: str,
        jwt: str | None = None,
    ) -> None:
        self._session = session
        self._yandex_token = yandex_token
        self._jwt = jwt

    @property
    def jwt(self) -> str | None:
        return self._jwt

    def _base_headers(self) -> dict[str, str]:
        return {
            "AppName": APP_NAME,
            "OriginalAppName": ORIGINAL_APP_NAME,
            "AppVersion": APP_VERSION,
            "AppTheme": "light",
            "TimeZone": "Europe/Moscow",
            "Accept-Language": "ru-RU",
            "User-Agent": USER_AGENT,
            "x-yandex-oauth": self._yandex_token,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        place_id: int | str | None = None,
        building_id: int | str | None = None,
        json_body: dict[str, Any] | None = None,
        with_auth: bool = True,
    ) -> dict[str, Any]:
        headers = self._base_headers()
        if with_auth:
            if not self._jwt:
                raise DomylandAuthError("JWT отсутствует")
            headers["Authorization"] = self._jwt
        if place_id is not None:
            headers["placeId"] = str(place_id)
        if building_id is not None:
            headers["buildingId"] = str(building_id)

        url = f"{API_BASE}{path}"
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        try:
            async with self._session.request(
                method, url, headers=headers, json=json_body, timeout=timeout
            ) as resp:
                text = await resp.text()
                if resp.status in (401, 403):
                    _LOGGER.debug("Auth error %s on %s: %s", resp.status, path, text[:200])
                    raise DomylandAuthError(f"{resp.status}: {text[:200]}")
                if resp.status >= 400:
                    raise DomylandError(f"{method} {path} → HTTP {resp.status}: {text[:200]}")
                try:
                    data = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as err:
                    raise DomylandError(f"Не JSON в ответе {path}: {err}") from err
        except aiohttp.ClientError as err:
            raise DomylandError(f"Сетевая ошибка {method} {path}: {err}") from err

        if isinstance(data, dict) and data.get("success") is False:
            raise DomylandError(f"API вернул success=false на {path}: {str(data)[:200]}")
        return data

    # --- Аутентификация ------------------------------------------------------

    async def exchange_yandex_token(self) -> dict[str, Any]:
        """Обменять Яндекс-OAuth токен на JWT domyland.

        POST /auth/yandex/scenario → data.payload.authData.token = JWT.
        Заодно кладёт полученный JWT в клиент.
        """
        body = {
            "deviceModel": "HomeAssistant",
            "deviceOSName": "Home Assistant",
            "deviceOSVersion": "1",
            "deviceVendor": "Home Assistant",
            "token": self._yandex_token,
        }
        # Единственная переменная обмена — Яндекс-токен, поэтому ЛЮБОЙ отказ
        # (в т.ч. 500, которым бэкенд Domyland отвечает на невалидный токен)
        # трактуем как проблему авторизации → reauth, а не как сетевой сбой.
        try:
            data = await self._request(
                "POST", "/auth/yandex/scenario", json_body=body, with_auth=False
            )
        except DomylandError as err:
            raise DomylandAuthError(str(err)) from err
        try:
            auth_data = data["data"]["payload"]["authData"]
            self._jwt = auth_data["token"]
        except (KeyError, TypeError) as err:
            raise DomylandAuthError(
                f"Неожиданный ответ /auth/yandex/scenario: {err}"
            ) from err
        return auth_data

    # --- Данные --------------------------------------------------------------

    async def get_current_customer(self) -> dict[str, Any]:
        data = await self._request("GET", "/current-customer")
        return data["data"]

    async def get_places(self) -> list[dict[str, Any]]:
        """GET /current-customer/places → список мест (домов/квартир/паркингов)."""
        data = await self._request("GET", "/current-customer/places", place_id="", building_id="")
        return data["data"]["places"]

    async def get_access_points(
        self, place_id: int | str, building_id: int | str
    ) -> list[dict[str, Any]]:
        """GET /smarthome/access → список дверей для дома (placeId/buildingId)."""
        data = await self._request(
            "GET", "/smarthome/access", place_id=place_id, building_id=building_id
        )
        return data["data"].get("items", [])

    async def get_access_detail(
        self, access_id: int | str, place_id: int | str, building_id: int | str
    ) -> dict[str, Any]:
        """GET /smarthome/access/{id} → детали двери.

        В отличие от списка, отдаёт MJPEG-поток встроенной камеры домофона
        (`video`, `videoType`) — у каждой двери своя камера.
        """
        data = await self._request(
            "GET",
            f"/smarthome/access/{access_id}",
            place_id=place_id,
            building_id=building_id,
        )
        return data["data"]

    async def get_cameras(
        self, place_id: int | str, building_id: int | str
    ) -> list[dict[str, Any]]:
        """GET /cameras → список камер (streamURL перевыпускается каждый вызов)."""
        data = await self._request(
            "GET", "/cameras", place_id=place_id, building_id=building_id
        )
        return data["data"].get("items", [])

    async def open_door(
        self, access_id: int | str, place_id: int | str, building_id: int | str
    ) -> None:
        """PUT /smarthome/access/{id}/open — открыть дверь. Тело не нужно."""
        await self._request(
            "PUT",
            f"/smarthome/access/{access_id}/open",
            place_id=place_id,
            building_id=building_id,
        )
