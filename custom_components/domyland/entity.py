"""Базовые сущности Domyland."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BuildingData, DomylandCoordinator


class DomylandBuildingEntity(CoordinatorEntity[DomylandCoordinator]):
    """Сущность, привязанная к дому (buildingId)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DomylandCoordinator, building_id: int) -> None:
        super().__init__(coordinator)
        self._building_id = building_id

    @property
    def _building(self) -> BuildingData | None:
        return self.coordinator.data.buildings.get(self._building_id)

    @property
    def device_info(self) -> DeviceInfo:
        building = self._building
        title = building.building_title if building else str(self._building_id)
        return DeviceInfo(
            identifiers={(DOMAIN, f"building_{self._building_id}")},
            name=title,
            manufacturer=MANUFACTURER,
            model="ЖК / дом",
        )
