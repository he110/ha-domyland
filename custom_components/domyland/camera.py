"""Камеры ЖК (MJPEG через UJIN) Domyland."""

from __future__ import annotations

import logging

import aiohttp
from aiohttp import web
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import (
    async_aiohttp_proxy_web,
    async_get_clientsession,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import DomylandConfigEntry, DomylandCoordinator
from .entity import DomylandBuildingEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomylandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать по камере на каждый streamURL. Отслеживаем появление новых."""
    coordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()

    @callback
    def _add_new() -> None:
        new_entities: list[DomylandCamera] = []
        for building_id, building in coordinator.data.buildings.items():
            for cam_id in building.cameras:
                key = (building_id, cam_id)
                if key in known:
                    continue
                known.add(key)
                new_entities.append(DomylandCamera(coordinator, building_id, cam_id))
        if new_entities:
            async_add_entities(new_entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class DomylandCamera(DomylandBuildingEntity, Camera):
    """MJPEG-камера UJIN.

    Поток отдаётся как `multipart/x-mixed-replace` (чистый MJPEG), поэтому его
    нужно проксировать в браузер напрямую, а НЕ через stream-компонент HA (тот
    рассчитан на RTSP/HLS и на MJPEG деградирует до покадрового опроса — рывки).
    Подписанный streamURL перевыпускается координатором каждые N минут.
    """

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int, cam_id: int
    ) -> None:
        DomylandBuildingEntity.__init__(self, coordinator, building_id)
        Camera.__init__(self)
        self._cam_id = cam_id
        self._attr_unique_id = f"{DOMAIN}_camera_{cam_id}"

    @property
    def _camera(self) -> dict | None:
        building = self._building
        if building is None:
            return None
        return building.cameras.get(self._cam_id)

    @property
    def name(self) -> str | None:
        cam = self._camera
        return cam.get("title") if cam else None

    @property
    def available(self) -> bool:
        return super().available and self._camera is not None

    def _stream_url(self) -> str | None:
        cam = self._camera
        return cam.get("streamURL") if cam else None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Один кадр из MJPEG-потока (для превью и снапшотов)."""
        url = self._stream_url()
        if not url:
            return None
        session = async_get_clientsession(self.hass)
        return await self._async_mjpeg_single_frame(session, url)

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse | None:
        """Живой просмотр: проксируем MJPEG-мультипарт UJIN прямо в браузер."""
        url = self._stream_url()
        if not url:
            return None
        session = async_get_clientsession(self.hass)
        stream_coro = session.get(url, timeout=aiohttp.ClientTimeout(total=None))
        return await async_aiohttp_proxy_web(self.hass, request, stream_coro)

    async def _async_mjpeg_single_frame(
        self, session: aiohttp.ClientSession, url: str
    ) -> bytes | None:
        """Вытащить один JPEG-кадр из MJPEG-стрима."""
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return None
                buffer = b""
                async for chunk in resp.content.iter_chunked(4096):
                    buffer += chunk
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if start != -1 and end != -1:
                        return buffer[start : end + 2]
                    if len(buffer) > 2_000_000:
                        break
        except Exception as err:  # noqa: BLE001 — камера best-effort
            _LOGGER.debug("Не удалось получить кадр камеры %s: %s", self.name, err)
        return None
