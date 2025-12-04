# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom integration for FranklinWH Whole Home battery systems. It provides real-time power monitoring, battery status, energy statistics, and system control through Home Assistant.

The integration uses the `franklinwh-python` library (https://github.com/richo/franklinwh-python) to communicate with the FranklinWH cloud API.

## Architecture

### Core Components

- **Coordinator** (`coordinator.py`): Central data fetching layer using Home Assistant's `DataUpdateCoordinator`. Polls the FranklinWH API every 30 seconds. Implements retry logic (2 retries with 3-second delays) for transient errors (`DeviceTimeoutException`, `GatewayOfflineException`) for both stats and mode fetching. Manages authentication via `TokenFetcher` which handles automatic token refresh.

- **Platforms**: The integration implements three Home Assistant platforms:
  - `sensor.py`: Power sensors (solar, battery, grid, load, generator), battery SOC, daily energy totals, and diagnostic sensors
  - `select.py`: Operating mode selector (Time of Use, Self Consumption, Backup)
  - `switch.py`: Smart circuit control (placeholder implementation - needs actual API data structure)

- **Config Flow** (`config_flow.py`): User-facing setup requiring email, password, and gateway ID. Validates credentials during setup and prevents duplicate entries using gateway ID as unique identifier.

### Data Flow

1. **Authentication**: `TokenFetcher(email, password)` → `Client(token_fetcher, gateway_id)`
2. **Data Fetching**: Coordinator calls `client.get_stats()` every 30 seconds → Returns `Stats` object with `current` (instantaneous values) and `totals` (daily energy)
3. **Mode Detection**: Coordinator also calls `client.get_mode()` to fetch current operating mode → Stored as `coordinator.current_mode`
4. **Entity Updates**: Platform entities extend `CoordinatorEntity` and access data via `self.coordinator.data`

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

1. **Operating Mode Current State**: The integration can read the current operating mode via `coordinator.current_mode`. The select entity displays this value and only shows as available when a valid mode is detected.

2. **Smart Circuits**: The switch platform has placeholder implementation. The actual structure depends on how the FranklinWH API exposes smart circuit data. When implementing, inspect `coordinator.data` to determine the correct structure.

3. **Generator Sensor**: Only created if `generator_production` exists and is greater than 0 (uses `exists_fn` in sensor description).

4. **Grid Status Sensor**: Disabled by default (`entity_registry_enabled_default=False`). Values map from enum: normal/down/off.

5. **Sensor Value Functions**: All sensors use lambda functions in `value_fn` to extract data from the `Stats` object. These handle None checks for missing data gracefully.

6. **Device Info**: All entities share the same device info using gateway_id as the identifier, grouping them under a single device in Home Assistant.

## Constants and Configuration

- **Domain**: `franklinwh`
- **Update Interval**: 30 seconds (`UPDATE_INTERVAL`)
- **Required Config**: `CONF_EMAIL`, `CONF_PASSWORD`, `CONF_GATEWAY_ID`
- **Mode Keys**: Must match library constants (`time_of_use`, `self_consumption`, `emergency_backup`)

## Dependencies

- `franklinwh>=0.4.1`: Python library for FranklinWH API access
- Home Assistant core >= 2024.1 (uses modern config flow and coordinator patterns)
