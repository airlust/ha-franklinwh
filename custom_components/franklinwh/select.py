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
        mode = self.coordinator.current_mode
        if mode and mode in self._attr_options:
            return mode
        if mode:
            _LOGGER.warning("Current mode '%s' not in valid options: %s", mode, self._attr_options)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose the gateway's own name for the active profile.

        The gateway names profiles after the rate plan they implement (e.g. "EV2A"),
        which is more specific than the mode key it maps to.
        """
        name = self.coordinator.current_mode_name
        if name:
            return {"profile_name": name}
        return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Allow mode selection even if we can't read the current mode
        # (e.g., when gateway returns unsupported mode values)
        return self.coordinator.last_update_success

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
