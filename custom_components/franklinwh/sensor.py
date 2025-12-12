"""Sensor platform for FranklinWH Energy Storage."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from franklinwh import Stats

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_GATEWAY_ID, DOMAIN
from .coordinator import FranklinWHCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FranklinWHSensorEntityDescription(SensorEntityDescription):
    """Describes FranklinWH sensor entity."""

    value_fn: Callable[[Stats], StateType] | None = None
    exists_fn: Callable[[Stats], bool] | None = None


SENSORS: tuple[FranklinWHSensorEntityDescription, ...] = (
    # Current Power Sensors (API returns values in kilowatts)
    FranklinWHSensorEntityDescription(
        key="solar_power",
        name="Solar Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats: stats.current.solar_production if stats.current else None,
    ),
    FranklinWHSensorEntityDescription(
        key="battery_power",
        name="Battery Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats: stats.current.battery_use if stats.current else None,
    ),
    FranklinWHSensorEntityDescription(
        key="grid_power",
        name="Grid Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats: stats.current.grid_use if stats.current else None,
    ),
    FranklinWHSensorEntityDescription(
        key="load_power",
        name="Load Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats: stats.current.home_load if stats.current else None,
    ),
    FranklinWHSensorEntityDescription(
        key="generator_power",
        name="Generator Power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats: stats.current.generator_production if stats.current else None,
        exists_fn=lambda stats: stats.current and stats.current.generator_production is not None and stats.current.generator_production > 0,
    ),
    # Battery State of Charge
    FranklinWHSensorEntityDescription(
        key="battery_soc",
        name="Battery State of Charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats: stats.current.battery_soc if stats.current else None,
    ),
    # Daily Energy Totals
    FranklinWHSensorEntityDescription(
        key="solar_energy_today",
        name="Solar Energy Today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.solar if stats.totals else None,
    ),
    FranklinWHSensorEntityDescription(
        key="battery_charge_today",
        name="Battery Charge Today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.battery_charge if stats.totals else None,
    ),
    FranklinWHSensorEntityDescription(
        key="battery_discharge_today",
        name="Battery Discharge Today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.battery_discharge if stats.totals else None,
    ),
    FranklinWHSensorEntityDescription(
        key="grid_import_today",
        name="Grid Import Today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.grid_import if stats.totals else None,
    ),
    FranklinWHSensorEntityDescription(
        key="grid_export_today",
        name="Grid Export Today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.grid_export if stats.totals else None,
    ),
    FranklinWHSensorEntityDescription(
        key="consumption_today",
        name="Consumption Today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda stats: stats.totals.home_use if stats.totals else None,
    ),
    # Diagnostic Sensors
    FranklinWHSensorEntityDescription(
        key="grid_status",
        name="Grid Status",
        device_class=SensorDeviceClass.ENUM,
        options=["normal", "down", "off"],
        value_fn=lambda stats: stats.current.grid_status.name.lower() if stats.current and stats.current.grid_status else None,
        entity_registry_enabled_default=False,
    ),
    FranklinWHSensorEntityDescription(
        key="ambient_temperature",
        name="Ambient Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        # Note: This sensor uses coordinator.ambient_temp directly, not from stats
        value_fn=None,  # Custom handling in FranklinWHAmbientTempSensor
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FranklinWH sensor platform."""
    coordinator: FranklinWHCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Add all sensors, but only if they exist (for optional ones like generator)
    entities = []
    for description in SENSORS:
        # Check if sensor should exist based on current data
        if description.exists_fn is not None:
            if coordinator.data and not description.exists_fn(coordinator.data):
                continue

        # Use custom sensor class for ambient temperature
        if description.key == "ambient_temperature":
            entities.append(FranklinWHAmbientTempSensor(coordinator, description, entry))
        else:
            entities.append(FranklinWHSensor(coordinator, description, entry))

    async_add_entities(entities)


class FranklinWHSensor(CoordinatorEntity[FranklinWHCoordinator], SensorEntity):
    """Representation of a FranklinWH sensor."""

    entity_description: FranklinWHSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        description: FranklinWHSensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.data[CONF_GATEWAY_ID]}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_GATEWAY_ID])},
            "name": f"FranklinWH {entry.data[CONF_GATEWAY_ID]}",
            "manufacturer": "FranklinWH",
            "model": "Energy Storage System",
        }

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.coordinator.data and self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return None


class FranklinWHAmbientTempSensor(FranklinWHSensor):
    """Ambient temperature sensor that reads from coordinator.ambient_temp."""

    @property
    def native_value(self) -> StateType:
        """Return the ambient temperature from coordinator."""
        return self.coordinator.ambient_temp
