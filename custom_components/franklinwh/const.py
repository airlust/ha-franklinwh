"""Constants for the FranklinWH Energy Storage integration."""
from datetime import timedelta
from typing import Final

DOMAIN: Final = "franklinwh"

# Configuration
CONF_GATEWAY_ID: Final = "gateway_id"

# Update interval
UPDATE_INTERVAL: Final = timedelta(seconds=30)

# Attributes
ATTR_BATTERY_SOC: Final = "battery_soc"
ATTR_SOLAR_POWER: Final = "solar_power"
ATTR_GRID_POWER: Final = "grid_power"
ATTR_LOAD_POWER: Final = "load_power"
ATTR_BATTERY_POWER: Final = "battery_power"
ATTR_GRID_STATUS: Final = "grid_status"

# Operating Modes
MODE_TIME_OF_USE: Final = "time_of_use"
MODE_SELF_CONSUMPTION: Final = "self_consumption"
MODE_BACKUP: Final = "backup"

MODES: Final = {
    MODE_TIME_OF_USE: "Time of Use",
    MODE_SELF_CONSUMPTION: "Self Consumption",
    MODE_BACKUP: "Backup",
}
