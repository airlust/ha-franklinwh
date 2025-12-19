"""Button platform for FranklinWH Energy Storage."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
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
    """Set up FranklinWH button platform."""
    coordinator: FranklinWHCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([FranklinWHTOURefreshButton(coordinator, entry)])


class FranklinWHTOURefreshButton(CoordinatorEntity[FranklinWHCoordinator], ButtonEntity):
    """Button to manually refresh TOU rate schedule."""

    _attr_has_entity_name = True
    _attr_name = "Refresh TOU Schedule"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_GATEWAY_ID]}_tou_refresh"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_GATEWAY_ID])},
            "name": f"FranklinWH {entry.data[CONF_GATEWAY_ID]}",
            "manufacturer": "FranklinWH",
            "model": "Energy Storage System",
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_refresh_tou_schedule()
