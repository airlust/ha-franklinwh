"""Select platform for FranklinWH Energy Storage."""
from __future__ import annotations

import logging

from franklinwh import Mode

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_GATEWAY_ID, DOMAIN, MODE_BACKUP, MODE_SELF_CONSUMPTION, MODE_TIME_OF_USE, MODES
from .coordinator import FranklinWHCoordinator

_LOGGER = logging.getLogger(__name__)

# Map our mode keys to the Mode class constructors
MODE_MAP = {
    MODE_TIME_OF_USE: Mode.time_of_use,
    MODE_SELF_CONSUMPTION: Mode.self_consumption,
    MODE_BACKUP: Mode.emergency_backup,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FranklinWH select platform."""
    coordinator: FranklinWHCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([FranklinWHModeSelect(coordinator, entry)])


class FranklinWHModeSelect(CoordinatorEntity[FranklinWHCoordinator], SelectEntity):
    """Representation of a FranklinWH operating mode selector."""

    _attr_has_entity_name = True
    _attr_name = "Operating Mode"
    _attr_options = list(MODES.keys())

    def __init__(
        self,
        coordinator: FranklinWHCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_GATEWAY_ID]}_operating_mode"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.data[CONF_GATEWAY_ID])},
            "name": f"FranklinWH {entry.data[CONF_GATEWAY_ID]}",
            "manufacturer": "FranklinWH",
            "model": "Energy Storage System",
        }

    @property
    def current_option(self) -> str | None:
        """Return the current operating mode."""
        if not self.coordinator.data or not self.coordinator.data.current:
            return None

        # Try to determine current mode from stats
        # This is a best-effort approach since the API might not directly expose the mode
        # We'll need to add this to the Stats data if available
        # For now, return None and the user can select a mode
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the operating mode."""
        if option not in MODE_MAP:
            _LOGGER.error("Invalid mode selected: %s", option)
            return

        mode_constructor = MODE_MAP[option]
        # Create mode with library default SOC values
        # time_of_use and self_consumption default to 20%, emergency_backup to 100%
        mode = mode_constructor()

        try:
            await self.coordinator.async_set_mode(mode)
            _LOGGER.info("Successfully set mode to %s", option)
        except Exception as err:
            _LOGGER.error("Failed to set mode to %s: %s", option, err)
            raise
