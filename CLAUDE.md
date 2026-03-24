# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom integration for FranklinWH Whole Home battery systems. It provides real-time power monitoring, battery status, energy statistics, and system control through Home Assistant.

The integration uses the `franklinwh-python` library (https://github.com/richo/franklinwh-python) to communicate with the FranklinWH cloud API.

## Architecture

### Core Components

- **Coordinator** (`coordinator.py`): Central data fetching layer using Home Assistant's `DataUpdateCoordinator`. Polls the FranklinWH API every 60 seconds. Implements retry logic (2 retries with 3-second delays) for transient errors (`DeviceTimeoutException`, `GatewayOfflineException`) for both stats and mode fetching. Manages authentication via `TokenFetcher` which handles automatic token refresh.

- **Platforms**: The integration implements five Home Assistant platforms:
  - `sensor.py`: Power sensors (solar, battery, grid, load, generator), battery SOC, daily energy totals, diagnostic sensors (grid status, ambient temperature), charging rate prediction sensors (current charge rate, time to full charge), and TOU rate sensors (current period, current rate, next period start, utility company, rate plan) - 22 sensors total
  - `binary_sensor.py`: Charging power limited indicator (shows when BMS is limiting charging power)
  - `button.py`: Manual TOU schedule refresh button
  - `select.py`: Operating mode selector (Time of Use, Self Consumption, Backup)
  - `switch.py`: Smart circuit control (dynamically created based on gateway configuration)

- **Config Flow** (`config_flow.py`): User-facing setup requiring email, password, and gateway ID. Validates credentials during setup and prevents duplicate entries using gateway ID as unique identifier.

### Data Flow

1. **Authentication**: `TokenFetcher(email, password)` → `Client(token_fetcher, gateway_id)`
2. **Data Fetching**: Coordinator calls `await client.get_stats()` every 60 seconds → Returns `Stats` object with `current` (instantaneous values) and `totals` (daily energy)
3. **Mode Detection**: Coordinator calls `await client._switch_status()` to get raw mode value, maps it via `MODE_VALUE_MAP` → Stored as `coordinator.current_mode`
4. **Charging Status**: Coordinator calls `await client._mqtt_send()` to get BMS charging limitation status → Stored as `coordinator.charging_power_limited`
5. **Ambient Temperature**: Coordinator calls `await client._status()` to get ambient temperature from gateway → Stored as `coordinator.ambient_temp`
6. **TOU Schedule**: Coordinator calls `await client._mqtt_send()` with endpoint 227 to fetch TOU rate schedule → Stored as `coordinator.tou_schedule`
7. **Entity Updates**: Platform entities extend `CoordinatorEntity` and access data via `self.coordinator.data` or coordinator properties

### Important Data Structures

- **Stats object** (from franklinwh library):
  - `stats.current`: Instantaneous power values (solar_production, battery_use, grid_use, home_load, generator_production, battery_soc, grid_status)
  - `stats.totals`: Daily energy totals (solar, battery_charge, battery_discharge, grid_import, grid_export, home_use)

- **Mode objects** (from franklinwh library):
  - Created via `Mode.time_of_use()`, `Mode.self_consumption()`, `Mode.emergency_backup()`
  - Each mode constructor accepts optional SOC parameter (defaults: 20% for TOU/Self Consumption, 100% for Emergency Backup)

### Power and Energy Units

**Critical**: The FranklinWH API returns power values in kilowatts (kW), not watts. All power sensors use `UnitOfPower.KILO_WATT` with 2 decimal precision. Energy sensors use `UnitOfEnergy.KILO_WATT_HOUR`.

### Error Handling

The coordinator implements retry logic specifically for:
- `DeviceTimeoutException`: Gateway didn't respond in time
- `GatewayOfflineException`: Gateway is offline

Both stats fetching (`_async_update_data`) and mode fetching (`_fetch_current_mode`) have independent retry logic. If mode fetching fails after all retries, it logs an error and sets `current_mode = None` (making the select entity unavailable) but doesn't fail the entire coordinator update. This ensures sensor data remains available even if mode detection temporarily fails.

Other exceptions (like authentication errors) are not retried and immediately fail the update.

## Development Commands

This is a Home Assistant custom component with no build process. Testing is done by:

1. **Installation**: Copy `custom_components/franklinwh` to your Home Assistant's `custom_components` directory
2. **Restart**: Restart Home Assistant to load the integration
3. **Configuration**: Add integration via UI (Settings → Devices & Services → Add Integration)
4. **Testing**: Monitor Home Assistant logs for errors:
   ```
   tail -f /config/home-assistant.log | grep franklinwh
   ```

## Key Implementation Notes

1. **Operating Mode Handling**: The integration calls `_switch_status()` directly to get the raw `runingMode` value from the gateway, then maps it using `MODE_VALUE_MAP` in coordinator.py. This bypasses the library's `get_mode()` method which only supports three standard modes (9322, 9323, 9324) and throws KeyError for customized modes like 113349 (E-TOU-C customized). Unknown modes default to time_of_use with a warning.

2. **Smart Circuits**: The switch platform has placeholder implementation. The actual structure depends on how the FranklinWH API exposes smart circuit data. When implementing, inspect `coordinator.data` to determine the correct structure.

3. **Generator Sensor**: Only created if `generator_production` exists and is greater than 0 (uses `exists_fn` in sensor description).

4. **Grid Status Sensor**: Disabled by default (`entity_registry_enabled_default=False`). Values map from enum: normal/down/off.

5. **Sensor Value Functions**: All sensors use lambda functions in `value_fn` to extract data from the `Stats` object. These handle None checks for missing data gracefully.

6. **Device Info**: All entities share the same device info using gateway_id as the identifier, grouping them under a single device in Home Assistant.

7. **Async/Await Pattern**: The franklinwh library methods are ALL async (`async def get_stats()`, `async def set_mode()`, `async def _switch_status()`, etc.) except for `__init__`, `next_snno`, and `_build_payload`. All async methods MUST be awaited directly, NOT wrapped in `async_add_executor_job()`. Using the executor with async methods causes deadlocks (blocking the event loop while waiting for the executor thread which is waiting for the event loop).

8. **Coordinator Properties**: The coordinator exposes calculated properties:
   - `current_charge_rate`: Returns positive kW value when charging (abs of negative battery_use)
   - `time_to_full_charge`: Calculates hours to 100% SOC based on current charge rate and 15kWh capacity
   - `ambient_temp`: Temperature in Celsius from gateway
   - `charging_power_limited`: Boolean indicating if BMS is limiting charging power
   - `tou_current_period`: Current TOU period name (e.g., 'on-peak', 'off-peak')
   - `tou_current_rate`: Current electricity rate in $/kWh
   - `tou_next_period_start`: Start time of next rate period (HH:MM format)
   - `tou_utility_company`: Utility company name
   - `tou_rate_plan`: Rate plan name (e.g., 'E-TOU-C')

9. **TOU Rate Sensors**: The integration fetches Time-of-Use rate schedules from endpoint 227 (`getTouDispatchDetail`). This provides season-based schedules with time periods, rates, and utility information. All TOU sensors are disabled by default (`entity_registry_enabled_default=False`). The schedule includes:
   - Seasonal variations (Winter/Summer months)
   - Multiple rate periods per day (on-peak, off-peak, shoulder)
   - Electricity rates for each period
   - Utility company and rate plan information
   - TOU schedule is fetched once per hour (3600 seconds) to minimize API calls
   - Manual refresh available via "Refresh TOU Schedule" button entity

## Constants and Configuration

- **Domain**: `franklinwh`
- **Update Interval**: 60 seconds (`UPDATE_INTERVAL`)
- **Retry Configuration**: `MAX_RETRIES = 2`, `RETRY_DELAY = 3` seconds
- **Required Config**: `CONF_EMAIL`, `CONF_PASSWORD`, `CONF_GATEWAY_ID`
- **Mode Keys**: Must match library constants (`time_of_use`, `self_consumption`, `emergency_backup`)
- **Battery Capacity**: 15.0 kWh (used for time-to-full calculations)

## Dependencies

- `franklinwh>=0.4.1`: Python library for FranklinWH API access
- Home Assistant core >= 2024.1 (uses modern config flow and coordinator patterns)

## Documentation Maintenance

**IMPORTANT**: When making changes to the codebase, keep the architecture documentation synchronized:

1. **ARCHITECTURE.md**: Update the text-based architecture documentation for any:
   - New entities or platforms added
   - Changes to coordinator methods, properties, or data flow
   - Updates to retry logic or error handling strategies
   - New mode mappings discovered
   - Changes to the async/await patterns

2. **architecture.svg**: Update the visual SVG diagram to reflect:
   - New components in the architecture layers
   - Changes to data flow paths
   - Updates to entity counts or types
   - New configuration constants
   - Changes to availability logic

Commit documentation updates together with code changes to maintain consistency. The architecture documentation serves as the primary reference for understanding the integration's design and implementation.
