"""Switch platform for FranklinWH Energy Storage."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_GATEWAY_ID, DOMAIN
from .coordinator import FranklinWHCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FranklinWH switch platform."""
    coordinator: FranklinWHCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Check if smart circuits are available in the stats
    # The exact structure depends on the API response
    # This is a placeholder that will need to be updated based on actual data
    entities = []

    # TODO: Parse smart circuits from coordinator.data
    # For now, we'll create a placeholder structure
    # When you test this, you'll need to inspect coordinator.data to see
    # how smart circuits are exposed and update this accordingly

    if coordinator.data:
        # Example: Check if there's a smart_circuits attribute
        # smart_circuits = getattr(coordinator.data, 'smart_circuits', [])
        # for circuit in smart_circuits:
        #     entities.append(FranklinWHSmartCircuit(coordinator, entry, circuit))
        pass

    async_add_entities(entities)


class FranklinWHSmartCircuit(CoordinatorEntity[FranklinWHCoordinator], SwitchEntity):
    """Representation of a FranklinWH smart circuit switch."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        entry: ConfigEntry,
        circuit_id: str,
        circuit_name: str | None = None,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self._circuit_id = circuit_id
        self._attr_name = circuit_name or f"Smart Circuit {circuit_id}"
        self._attr_unique_id = f"{entry.data[CONF_GATEWAY_ID]}_circuit_{circuit_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_GATEWAY_ID])},
            "name": f"FranklinWH {entry.data[CONF_GATEWAY_ID]}",
            "manufacturer": "FranklinWH",
            "model": "Energy Storage System",
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        # TODO: Parse switch state from coordinator.data
        # This will depend on how the API exposes circuit states
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        try:
            await self.coordinator.async_set_smart_switch_state(self._circuit_id, True)
            _LOGGER.info("Turned on smart circuit %s", self._circuit_id)
        except Exception as err:
            _LOGGER.error("Failed to turn on circuit %s: %s", self._circuit_id, err)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        try:
            await self.coordinator.async_set_smart_switch_state(self._circuit_id, False)
            _LOGGER.info("Turned off smart circuit %s", self._circuit_id)
        except Exception as err:
            _LOGGER.error("Failed to turn off circuit %s: %s", self._circuit_id, err)
            raise
