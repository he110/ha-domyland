"""Замки (домофоны/калитки) Domyland — открытие двери импульсом."""

from __future__ import annotations

import logging

from homeassistant.components.lock import LockEntity, LockEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import DomylandError
from .const import DOMAIN
from .coordinator import DomylandConfigEntry, DomylandCoordinator
from .entity import DomylandBuildingEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DomylandConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Создать замок на каждую дверь. Отслеживаем появление новых дверей."""
    coordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()

    @callback
    def _add_new() -> None:
        new_entities: list[DomylandDoorLock] = []
        for building_id, building in coordinator.data.buildings.items():
            for door_id in building.doors:
                key = (building_id, door_id)
                if key in known:
                    continue
                known.add(key)
                new_entities.append(
                    DomylandDoorLock(coordinator, building_id, door_id)
                )
        if new_entities:
            async_add_entities(new_entities)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class DomylandDoorLock(DomylandBuildingEntity, LockEntity):
    """Домофон/калитка как замок с действием «Открыть».

    API Domyland умеет только импульсное открытие (PUT .../open) и не сообщает
    состояние двери. Поэтому замок всегда показываем «заперто» (безопасное
    состояние по умолчанию), а любое действие открытия шлёт импульс.
    """

    _attr_supported_features = LockEntityFeature.OPEN
    _attr_is_locked = True  # состояния от API нет → всегда «заперто»

    def __init__(
        self, coordinator: DomylandCoordinator, building_id: int, door_id: int
    ) -> None:
        super().__init__(coordinator, building_id)
        self._door_id = door_id
        self._attr_unique_id = f"{DOMAIN}_door_{door_id}"

    @property
    def _door(self) -> dict | None:
        building = self._building
        if building is None:
            return None
        return building.doors.get(self._door_id)

    @property
    def name(self) -> str | None:
        door = self._door
        return door.get("title") if door else None

    @property
    def available(self) -> bool:
        door = self._door
        return (
            super().available
            and door is not None
            and door.get("isAvailable", True)
        )

    async def _buzz(self) -> None:
        building = self._building
        if building is None:
            raise HomeAssistantError("Дом недоступен")
        try:
            await self.coordinator.client.open_door(
                self._door_id, building.place_id, building.building_id
            )
        except DomylandError as err:
            raise HomeAssistantError(f"Не удалось открыть дверь: {err}") from err
        _LOGGER.info("Domyland: открыта дверь %s", self.name)

    async def async_open(self, **kwargs) -> None:
        """Открыть дверь (импульс)."""
        await self._buzz()

    async def async_unlock(self, **kwargs) -> None:
        """Основное действие карточки тоже открывает дверь импульсом."""
        await self._buzz()

    async def async_lock(self, **kwargs) -> None:
        """Запирания у домофона нет — дверь закрывается сама. No-op."""
        return
