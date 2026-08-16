# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant custom integration for FranklinWH Whole Home battery systems. It provides real-time power monitoring, battery status, energy statistics, and system control through Home Assistant.

The integration uses the `franklinwh-python` library (https://github.com/richo/franklinwh-python) to communicate with the FranklinWH cloud API.

## Architecture

### Core Components

- **Coordinator** (`coordinator.py`): Central data fetching layer using Home Assistant's `DataUpdateCoordinator`. Polls the FranklinWH API on `UPDATE_INTERVAL`. A single retry loop in `_async_update_data()` covers everything the cycle fetches — retries on `TRANSIENT_ERRORS`, applies adaptive backoff, then serves cached values for up to `MAX_STALE_CYCLES` before entities go unavailable. Manages authentication via `TokenFetcher` which handles automatic token refresh.

- **Platforms**: The integration implements five Home Assistant platforms:
  - `sensor.py`: Power sensors (solar, battery, grid, load, generator), battery SOC, daily energy totals, diagnostic sensors (grid status, ambient temperature), charging rate prediction sensors (current charge rate, time to full charge), and TOU rate sensors (current period, current rate, next period start, utility company, rate plan) - 22 sensors total
  - `binary_sensor.py`: Charging power limited indicator (shows when BMS is limiting charging power)
  - `button.py`: Manual TOU schedule refresh button
  - `select.py`: Operating mode selector (Time of Use, Self Consumption, Backup, Smart Energy Dispatch — the last is read-only)
  - `switch.py`: Smart circuit control (dynamically created based on gateway configuration)

- **Config Flow** (`config_flow.py`): User-facing setup requiring email, password, and gateway ID. Validates credentials during setup and prevents duplicate entries using gateway ID as unique identifier.

### Data Flow

1. **Authentication**: `TokenFetcher(email, password)` → `Client(token_fetcher, gateway_id)`
2. **Data Fetching**: Coordinator calls `await client.get_stats()` every 60 seconds → Returns `Stats` object with `current` (instantaneous values) and `totals` (daily energy)
3. **Mode Detection**: Coordinator calls `await client._switch_status()` for the raw `runingMode`, then resolves it against the gateway's TOU profile list (`getGatewayTouListV2`) and reads that profile's `workMode` → Stored as `coordinator.current_mode`, with the profile's own name in `coordinator.current_mode_name`
4. **Charging Status**: Coordinator calls `await client._mqtt_send()` to get BMS charging limitation status → Stored as `coordinator.charging_power_limited`
5. **Ambient Temperature**: Coordinator calls `await client._status()` to get ambient temperature from gateway → Stored as `coordinator.ambient_temp`
6. **TOU Schedule**: Coordinator calls `await client._mqtt_send()` with endpoint 227 to fetch TOU rate schedule → Stored as `coordinator.tou_schedule`
7. **Battery Capacity**: Coordinator calls `obtainApowersInfo` once and sums each unit's `ratedCapacity` → Stored as `coordinator.battery_capacity`
8. **Entity Updates**: Platform entities extend `CoordinatorEntity` and access data via `self.coordinator.data` or coordinator properties

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

Transient backend conditions are listed once in `TRANSIENT_ERRORS` (`coordinator.py`): `DeviceTimeoutException`, `GatewayOfflineException`, and the httpx read/connect timeouts. Add to that tuple rather than to an individual `except` clause, so every fetch sharing the update cycle keeps the same behavior.

`_async_update_data()` owns the only retry loop. It retries (`MAX_RETRIES`, `UPDATE_RETRY_DELAYS`), applies adaptive backoff, and then serves cached values for up to `MAX_STALE_CYCLES` before marking entities unavailable.

`_fetch_current_mode()` deliberately has **no** retry loop of its own — it runs inside that one and re-raises transient errors for it to handle. Do not give it one: it previously had independent retries and set `current_mode = None` on failure, which meant a brief backend blip that the power sensors rode out silently dropped the operating mode to "unknown". The mode now stays available exactly as long as the sensors do.

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

1. **Operating Mode Handling**: The integration calls `_switch_status()` directly for the raw `runingMode`, bypassing the library's `get_mode()`, which only knows 9322/9323/9324 and raises KeyError otherwise. It then resolves the value via `_resolve_mode_from_tou_list()`: fetch `getGatewayTouListV2`, find the active profile (by `runingMode`, or by `currendId` when `runingMode` isn't a profile id), and read that profile's `workMode` from `WORK_MODE_TO_KEY`.

   **Do not add a table of `runingMode` → mode constants.** One existed and was removed. Those numbers are per-account database ids for TOU profile rows, not protocol constants — the same account reports different ids for the same mode on different gateways, and ids from different accounts interleave numerically. Such a table only ever helps users who reported their own values, and it is actively harmful: since an unrecognized `workMode` and a failed request both mean "unresolved", a table consulted at that point answers a *brand-new* mode with whatever that id previously meant. That is the silent mis-mapping of issue #6. When the mode can't be resolved, set `current_mode = None` and log loudly.

2. **Smart Energy Dispatch**: `workMode` 7, the AI-assisted mode added by the FranklinWH app in mid-2026. Read-only: the library's `Mode` class has no constructor for it, so `select.py` raises `HomeAssistantError` pointing at the app. Note it must still appear in `MODES` — HA renders a `current_option` that isn't in `options` as "unknown", which was the original bug.

3. **Smart Circuits**: The switch platform has placeholder implementation. The actual structure depends on how the FranklinWH API exposes smart circuit data. When implementing, inspect `coordinator.data` to determine the correct structure.

4. **Generator Sensor**: Only created if `generator_production` exists and is greater than 0 (uses `exists_fn` in sensor description).

5. **Grid Status Sensor**: Disabled by default (`entity_registry_enabled_default=False`). Values map from enum: normal/down/off.

6. **Sensor Value Functions**: All sensors use lambda functions in `value_fn` to extract data from the `Stats` object. These handle None checks for missing data gracefully.

7. **Device Info**: All entities share the same device info using gateway_id as the identifier, grouping them under a single device in Home Assistant.

8. **Async/Await Pattern**: The franklinwh library methods are ALL async (`async def get_stats()`, `async def set_mode()`, `async def _switch_status()`, etc.) except for `__init__`, `next_snno`, and `_build_payload`. All async methods MUST be awaited directly, NOT wrapped in `async_add_executor_job()`. Using the executor with async methods causes deadlocks (blocking the event loop while waiting for the executor thread which is waiting for the event loop).

9. **Coordinator Properties**: The coordinator exposes calculated properties:
   - `current_charge_rate`: Returns positive kW value when charging (abs of negative battery_use)
   - `time_to_full_charge`: Hours to full from the current charge rate and `battery_capacity`. Returns `0.0` at or above `BATTERY_FULL_SOC` and `None` below `MIN_MEANINGFUL_CHARGE_RATE`. Both thresholds are load-bearing: gateways need not ever report exactly 100 (an aHub sitting full reports 99.7 while the app shows 100), and a full battery still draws a balancing trickle, so comparing against exactly 100 and exactly 0 made the sensor divide a tiny remainder by a tiny rate and report hours for a battery that was already full.
   - `ambient_temp`: Temperature in Celsius from gateway
   - `charging_power_limited`: Boolean indicating if BMS is limiting charging power
   - `tou_current_period`: Current TOU period name (e.g., 'on-peak', 'off-peak')
   - `tou_current_rate`: Current electricity rate in $/kWh
   - `tou_next_period_start`: Start time of next rate period (HH:MM format)
   - `tou_utility_company`: Utility company name
   - `tou_rate_plan`: Rate plan name (e.g., 'E-TOU-C')

10. **TOU Rate Sensors**: The integration fetches Time-of-Use rate schedules from endpoint 227 (`getTouDispatchDetail`). This provides season-based schedules with time periods, rates, and utility information. All TOU sensors are disabled by default (`entity_registry_enabled_default=False`). The schedule includes:
   - Seasonal variations (Winter/Summer months)
   - Multiple rate periods per day (on-peak, off-peak, shoulder)
   - Electricity rates for each period
   - Utility company and rate plan information
   - TOU schedule is fetched once per hour (3600 seconds) to minimize API calls
   - Manual refresh available via "Refresh TOU Schedule" button entity

## Constants and Configuration

- **Domain**: `franklinwh`
- **Update Interval**: 30 seconds (`UPDATE_INTERVAL`)
- **Retry Configuration**: `MAX_RETRIES = 2`, `UPDATE_RETRY_DELAYS = [5, 15]` seconds; `MAX_STALE_CYCLES = 10` cycles of cached data before entities go unavailable
- **Required Config**: `CONF_EMAIL`, `CONF_PASSWORD`, `CONF_GATEWAY_ID`
- **Mode Keys**: The first three must match library constants (`time_of_use`, `self_consumption`, `emergency_backup`); `smart_energy_dispatch` is integration-only, as the library has no equivalent
- **Mode Enum**: `WORK_MODE_TO_KEY` maps the gateway's `workMode` (1, 2, 3, 7) to those keys
- **Battery Capacity**: read from the gateway by summing `ratedCapacity` across installed aPower units (`obtainApowersInfo`). `DEFAULT_BATTERY_CAPACITY = 15.0` kWh covers one unit and is only used until the first successful fetch. Do not reintroduce a hardcoded total: installations have more than one aPower, and units are not all the same size.

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
