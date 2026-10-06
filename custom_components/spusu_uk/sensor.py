"""Sensors for allowance, usage, and remaining balances."""

import re

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SpusuCoordinator
from .models import Metric

DATA_UNITS = {"B", "kB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SpusuCoordinator = entry.runtime_data
    known = set()

    @callback
    def discover() -> None:
        new = [key for key in (coordinator.data or {}) if key not in known]
        if new:
            known.update(new)
            async_add_entities(
                [SpusuSensor(coordinator, entry, coordinator.data[key]) for key in new]
            )

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class SpusuSensor(CoordinatorEntity[SpusuCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SpusuCoordinator, entry: ConfigEntry, metric: Metric
    ) -> None:
        super().__init__(coordinator)
        self.key = metric.key
        self._unit = metric.unit
        self._attr_unique_id = (
            f"{entry.entry_id}:{metric.subscription}:{metric.category}:{metric.kind}"
        )
        category = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", metric.category).replace(
            "_", " "
        )
        self._attr_name = f"{category.capitalize()} {metric.kind}"
        self._attr_native_unit_of_measurement = metric.unit
        if metric.unit in DATA_UNITS:
            self._attr_device_class = SensorDeviceClass.DATA_SIZE
        elif metric.unit == "min":
            self._attr_device_class = SensorDeviceClass.DURATION
        elif metric.unit == "GBP":
            self._attr_device_class = SensorDeviceClass.MONETARY
        # Monetary caps are snapshots, not totals to accumulate in statistics.
        self._attr_state_class = (
            None if metric.unit == "GBP" else SensorStateClass.MEASUREMENT
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}:{metric.subscription}")},
            name="Spusu UK"
            if metric.subscription == "primary"
            else f"Spusu UK {metric.subscription}",
            manufacturer="Spusu",
            entry_type="service",
        )

    @property
    def available(self) -> bool:
        metric = (self.coordinator.data or {}).get(self.key)
        # The coordinator remains successful while it awaits a renewal token.
        # Missing/unlimited numeric values are unavailable rather than fabricated.
        return (
            self.coordinator.last_update_success
            and metric is not None
            and metric.value is not None
            and metric.unit == self._unit
        )

    @property
    def native_value(self) -> float | None:
        metric = (self.coordinator.data or {}).get(self.key)
        return metric.value if metric else None

    @property
    def extra_state_attributes(self) -> dict:
        metric = (self.coordinator.data or {}).get(self.key)
        return {
            "renewing_session": self.coordinator.renewing,
            "unlimited": metric.unlimited if metric else False,
            **(
                {
                    "default_allowance": metric.default_allowance,
                    "next_month_allowance": metric.next_month_allowance,
                    "maximum_limit": metric.maximum_limit,
                }
                if metric and metric.category.startswith("costLimit")
                else {}
            ),
        }
