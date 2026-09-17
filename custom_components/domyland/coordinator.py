"""DataUpdateCoordinator интеграции Domyland."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DomylandApiClient, DomylandAuthError, DomylandError
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type DomylandConfigEntry = ConfigEntry[DomylandCoordinator]


@dataclass
class BuildingData:
    """Один физический дом (buildingId) со своими дверями и камерами."""

    building_id: int
    building_title: str
    # place_id/тип помещения, чьими заголовками мы ходим за дверями/камерами.
    place_id: int
    place_address: str
    doors: dict[int, dict[str, Any]] = field(default_factory=dict)
    cameras: dict[int, dict[str, Any]] = field(default_factory=dict)
    # Встроенные камеры домофонов (door_id → детали с полем `video`).
    door_cameras: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass
class DomylandData:
    """Снимок состояния, который отдаёт координатор в платформы."""

    buildings: dict[int, BuildingData] = field(default_factory=dict)


class DomylandCoordinator(DataUpdateCoordinator[DomylandData]):
    """Тянет места → двери/камеры по каждому уникальному дому.

    Двери и камеры физически привязаны к дому (buildingId), а не к юниту.
    Несколько мест в одном доме (напр. квартира + машиноместо) дали бы дубли,
    поэтому группируем по buildingId и ходим за содержимым один раз на дом.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: DomylandConfigEntry,
        client: DomylandApiClient,
        enable_cameras: bool,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.enable_cameras = enable_cameras

    async def _async_update_data(self) -> DomylandData:
        try:
            places = await self.client.get_places()
        except DomylandAuthError as err:
            # Протух Яндекс-токен → запустить reauth-флоу.
            raise ConfigEntryAuthFailed(err) from err
        except DomylandError as err:
            raise UpdateFailed(str(err)) from err

        buildings: dict[int, BuildingData] = {}

        # Выбираем по одному представительному place на каждый дом.
        # Предпочитаем жилой юнит (placeTypeId == 1, «Квартира») — у него точно
        # есть доступ к домофонам; машиноместо/паркинг оставляем как фолбэк.
        for place in places:
            building_id = place.get("buildingId")
            if building_id is None:
                continue
            existing = buildings.get(building_id)
            is_flat = place.get("placeTypeId") == 1
            if existing is None or (is_flat and existing.place_id != place["id"]):
                buildings[building_id] = BuildingData(
                    building_id=building_id,
                    building_title=place.get("buildingTitle") or str(building_id),
                    place_id=place["id"],
                    place_address=place.get("address") or "",
                )
                if is_flat:
                    # Жилой юнит найден — фиксируем его как представителя.
                    continue

        # Тянем содержимое по каждому дому.
        for building in buildings.values():
            try:
                doors = await self.client.get_access_points(
                    building.place_id, building.building_id
                )
                building.doors = {d["id"]: d for d in doors}
                if self.enable_cameras:
                    cameras = await self.client.get_cameras(
                        building.place_id, building.building_id
                    )
                    building.cameras = {c["id"]: c for c in cameras}
                    building.door_cameras = await self._fetch_door_cameras(building)
            except DomylandAuthError as err:
                raise ConfigEntryAuthFailed(err) from err
            except DomylandError as err:
                # Один дом мог отвалиться (нет smart home) — не роняем весь апдейт.
                _LOGGER.warning(
                    "Не удалось получить устройства дома %s: %s",
                    building.building_title,
                    err,
                )

        return DomylandData(buildings=buildings)

    async def _fetch_door_cameras(
        self, building: BuildingData
    ) -> dict[int, dict]:
        """Собрать встроенные камеры домофонов дома.

        Поток камеры (`video`) есть только в детальном ответе по каждой двери,
        поэтому тянем детали всех дверей параллельно. Подписанный URL
        перевыпускается при каждом запросе — обновляется вместе с координатором.
        """

        async def _one(door_id: int) -> tuple[int, dict | None]:
            try:
                detail = await self.client.get_access_detail(
                    door_id, building.place_id, building.building_id
                )
            except DomylandError as err:
                _LOGGER.debug("Нет деталей двери %s: %s", door_id, err)
                return door_id, None
            if not detail.get("video"):
                return door_id, None
            return door_id, {
                "title": detail.get("title"),
                "video": detail["video"],
                "videoType": detail.get("videoType"),
                "image": detail.get("image"),
            }

        results = await asyncio.gather(*(_one(d) for d in building.doors))
        return {door_id: info for door_id, info in results if info is not None}


