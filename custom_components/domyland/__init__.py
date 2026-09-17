"""Интеграция Domyland — домофоны и камеры ЖК через платформу Domyland."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DomylandApiClient
from .const import (
    CONF_ENABLE_CAMERAS,
    CONF_JWT,
    CONF_YANDEX_TOKEN,
    DEFAULT_ENABLE_CAMERAS,
)
from .coordinator import DomylandConfigEntry, DomylandCoordinator

PLATFORMS: list[Platform] = [Platform.LOCK, Platform.CAMERA]


async def async_setup_entry(hass: HomeAssistant, entry: DomylandConfigEntry) -> bool:
    """Настроить config entry."""
    session = async_get_clientsession(hass)
    client = DomylandApiClient(
        session,
        yandex_token=entry.data[CONF_YANDEX_TOKEN],
        jwt=entry.data.get(CONF_JWT),
    )
    enable_cameras = entry.options.get(CONF_ENABLE_CAMERAS, DEFAULT_ENABLE_CAMERAS)

    coordinator = DomylandCoordinator(hass, entry, client, enable_cameras)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DomylandConfigEntry) -> bool:
    """Выгрузить config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: DomylandConfigEntry
) -> None:
    """Перезагрузить при изменении опций (напр. вкл/выкл камеры)."""
    await hass.config_entries.async_reload(entry.entry_id)
