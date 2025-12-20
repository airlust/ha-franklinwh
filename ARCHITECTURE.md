# FranklinWH Integration Architecture

## High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Home Assistant Core                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Config Entry
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     FranklinWH Integration                               │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  __init__.py (Entry Point)                                        │  │
│  │  - Sets up config entry                                           │  │
│  │  - Creates coordinator instance                                   │  │
│  │  - Forwards setup to platforms                                    │  │
│  └──────────────────────────┬────────────────────────────────────────┘  │
│                             │                                            │
│                             │ Creates & Stores                           │
│                             ▼                                            │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  coordinator.py (FranklinWHCoordinator)                           │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │  Core Responsibilities:                                      │ │  │
│  │  │  - Manages data fetching on UPDATE_INTERVAL (60s)           │ │  │
│  │  │  - Handles authentication via TokenFetcher                  │ │  │
│  │  │  - Maintains franklinwh.Client instance                     │ │  │
│  │  │  - Implements retry logic (3 attempts, 3s delay)            │ │  │
│  │  │  - Exposes data via coordinator.data (Stats object)         │ │  │
│  │  │  - Stores current_mode, ambient_temp, charging_limited,     │ │  │
│  │  │    tou_schedule                                              │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  │                                                                     │  │
│  │  Key Methods:                                                       │  │
│  │  • _async_update_data() - Main update loop                         │  │
│  │  • _fetch_current_mode() - Gets operating mode via _switch_status │  │
│  │  • _fetch_charging_limited() - Gets BMS limiting status           │  │
│  │  • _fetch_ambient_temp() - Gets temperature via _status           │  │
│  │  • _fetch_tou_schedule_if_needed() - Gets TOU (hourly)            │  │
│  │  • async_refresh_tou_schedule() - Manual TOU refresh              │  │
│  │  • async_set_mode() - Changes operating mode                       │  │
│  │  • async_set_smart_switch_state() - Controls smart switches       │  │
│  │                                                                     │  │
│  │  Properties:                                                        │  │
│  │  • current_charge_rate - Calculated from battery_use              │  │
│  │  • time_to_full_charge - Estimated based on charge rate           │  │
│  │  • tou_current_period - Current rate period name                  │  │
│  │  • tou_current_rate - Current electricity rate                    │  │
│  │  • tou_next_period_start - Next period start time                 │  │
│  └──────────────────┬──────────────────────────────────────────────────┘  │
│                     │                                                     │
│                     │ Data Distribution                                  │
│                     ▼                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │                    Entity Platforms                                 │ │
│  │                                                                     │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │ │
│  │  │  sensor.py       │  │ binary_sensor.py │  │  select.py      │  │ │
│  │  │                  │  │                  │  │                 │  │ │
│  │  │ • Solar Power    │  │ • Charging Power │  │ • Operating     │  │ │
│  │  │ • Battery Power  │  │   Limited        │  │   Mode          │  │ │
│  │  │ • Grid Power     │  │   (BMS status)   │  │   - TOU         │  │ │
│  │  │ • Load Power     │  │                  │  │   - Self Use    │  │ │
│  │  │ • Generator      │  │  Available when: │  │   - Backup      │  │ │
│  │  │ • Battery SOC    │  │  - coordinator   │  │                 │  │ │
│  │  │ • Energy Totals  │  │    success       │  │  Allows mode    │  │ │
│  │  │   (7 sensors)    │  │  - charging_     │  │  selection even │  │ │
│  │  │ • Grid Status    │  │    limited != None  │ when current   │  │ │
│  │  │ • Ambient Temp   │  │                  │  │  mode unknown   │  │ │
│  │  │ • Charge Rate    │  └──────────────────┘  │                 │  │ │
│  │  │ • Time to Full   │                        └─────────────────┘  │ │
│  │  │ • TOU Sensors:   │  ┌─────────────────┐                        │ │
│  │  │   - Current Per. │  │  button.py      │                        │ │
│  │  │   - Current Rate │  │                 │                        │ │
│  │  │   - Next Start   │  │ • Refresh TOU   │                        │ │
│  │  │   - Utility Co.  │  │   Schedule      │                        │ │
│  │  │   - Rate Plan    │  │                 │                        │ │
│  │  │                  │  └─────────────────┘                        │ │
│  │  │ Total: 22 sensors│  ┌─────────────────┐                        │ │
│  │  └──────────────────┘  │  switch.py      │                        │ │
│  │                        │                 │                        │ │
│  │                        │ • Smart Switch  │                        │ │
│  │                        │   Controls      │                        │ │
│  │                        │                 │                        │ │
│  │                        │  Dynamically    │                        │ │
│  │                        │  created based  │                        │ │
│  │                        │  on gateway     │                        │ │
│  │                        │  configuration  │                        │ │
│  │                        └─────────────────┘                        │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                │ Uses
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    franklinwh Library (v0.4.1+)                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Client (Async)                                                   │  │
│  │  • async def get_stats() -> Stats                                │  │
│  │  • async def _switch_status() -> dict                            │  │
│  │  • async def _mqtt_send(payload) -> dict                         │  │
│  │  • def set_mode(mode: Mode) -> None (sync)                       │  │
│  │  • def set_smart_switch_state(id, state) -> None (sync)          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  TokenFetcher                                                     │  │
│  │  • Manages authentication                                         │  │
│  │  • Handles token refresh                                          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Data Models                                                      │  │
│  │  • Stats (current + totals)                                       │  │
│  │  • Mode enum (TOU=9322, SELF=9323, BACKUP=9324)                  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                                │ MQTT over WSS
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FranklinWH Cloud API                                  │
│                    (wss://...)                                           │
└─────────────────────────────────────────────────────────────────────────┘
                                │
                                │ Data from Gateway
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FranklinWH Gateway (Physical Device)                  │
│                    • Battery management                                  │
│                    • Solar/Grid/Load monitoring                          │
│                    • Smart switch control                                │
└─────────────────────────────────────────────────────────────────────────┘
```

## Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Every 60 seconds (UPDATE_INTERVAL)                                      │
└──────────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
        ┌────────────────────────────────────────────┐
        │  coordinator._async_update_data()          │
        └────────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┬──────────────────┬──────────────┐
                ▼                               ▼                  ▼              ▼
    ┌──────────────────────┐      ┌──────────────────────┐  ┌──────────────┐  ┌─────────────┐
    │ get_stats()          │      │ _fetch_current_mode()│  │ _fetch_      │  │ _fetch_tou_ │
    │                      │      │                      │  │ charging_    │  │ schedule()  │
    │ Returns Stats:       │      │ Calls:               │  │ limited()    │  │             │
    │ • current.solar_     │      │   _switch_status()   │  │              │
    │   production         │      │                      │  │ Gets BMS     │
    │ • current.battery_   │      │ Returns:             │  │ limiting     │
    │   use                │      │ • runingMode (int)   │  │ status       │
    │ • current.grid_use   │      │ • t_amb (float)      │  │              │
    │ • current.home_load  │      │                      │  │ Sets:        │
    │ • current.battery_   │      │ Maps via:            │  │ coordinator. │
    │   soc                │      │   MODE_VALUE_MAP     │  │ charging_    │
    │ • current.grid_      │      │                      │  │ power_       │
    │   status             │      │ Sets:                │  │ limited      │
    │ • current.generator_ │      │ coordinator.         │  │              │
    │   production         │      │   current_mode       │  └──────────────┘
    │ • totals.solar       │      │ coordinator.         │
    │ • totals.battery_    │      │   ambient_temp       │
    │   charge/discharge   │      │                      │
    │ • totals.grid_       │      │ Fallback for unknown:│
    │   import/export      │      │   MODE_TIME_OF_USE   │
    │ • totals.home_use    │      │                      │
    │                      │      │ Known modes:         │
    │ Stored in:           │      │ • 9322, 113349 → TOU │
    │ coordinator.data     │      │ • 9323, 117082 → SELF│
    └──────────────────────┘      │ • 9324, 46540 → BACKUP
                                  └──────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │  Retry Logic           │
                    │  (MAX_RETRIES=2)       │
                    │                        │
                    │  On timeout/offline:   │
                    │  1. Log warning        │
                    │  2. Sleep 3s           │
                    │  3. Retry              │
                    │                        │
                    │  After 3 attempts:     │
                    │  - Stats: Raise        │
                    │    UpdateFailed        │
                    │  - Mode: Set to None   │
                    │  - Charging: Set None  │
                    └────────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │  coordinator.data      │
                    │  updated               │
                    └────────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │  All entities receive  │
                    │  update notification   │
                    │  via CoordinatorEntity │
                    └────────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │  Entity.native_value   │
                    │  properties called     │
                    │                        │
                    │  Return data from:     │
                    │  - coordinator.data    │
                    │  - coordinator props   │
                    └────────────────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │  Home Assistant UI     │
                    │  updates               │
                    └────────────────────────┘
```

## Mode Value Mapping

```
┌─────────────────────────────────────────────────────────────────┐
│  FranklinWH Gateway Reports                                     │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ runingMode (int)
                            ▼
            ┌──────────────────────────────────┐
            │  MODE_VALUE_MAP (coordinator.py) │
            │                                  │
            │  Standard modes:                 │
            │  • 9322  → MODE_TIME_OF_USE      │
            │  • 9323  → MODE_SELF_CONSUMPTION │
            │  • 9324  → MODE_BACKUP           │
            │                                  │
            │  Custom modes (user-specific):   │
            │  • 113349 → MODE_TIME_OF_USE     │
            │    (E-TOU-C customized)          │
            │  • 117082 → MODE_SELF_CONSUMPTION│
            │    (Customized Self Consumption) │
            │  • 46540  → MODE_BACKUP          │
            │    (Customized Emergency Backup) │
            │                                  │
            │  Unknown modes:                  │
            │  • Any other → MODE_TIME_OF_USE  │
            │    (with warning logged)         │
            └──────────────────────────────────┘
                            │
                            ▼
            ┌──────────────────────────────────┐
            │  coordinator.current_mode        │
            │  (string constant)               │
            └──────────────────────────────────┘
                            │
                            ▼
            ┌──────────────────────────────────┐
            │  FranklinWHModeSelect entity     │
            │  displays in Home Assistant UI   │
            └──────────────────────────────────┘
```

## Async/Await Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│  Why We Use Direct Await (Not Executor)                         │
└─────────────────────────────────────────────────────────────────┘

The franklinwh library methods are ASYNC:

┌─────────────────────────────────────────────────────────────────┐
│  franklinwh Library                                             │
│                                                                 │
│  async def get_stats(self) -> Stats:                           │
│      # MQTT communication (already async)                      │
│      return await self._fetch_data()                           │
│                                                                 │
│  async def _switch_status(self) -> dict:                       │
│      # MQTT communication (already async)                      │
│      return await self._fetch_mode()                           │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ CORRECT USAGE
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  FranklinWHCoordinator                                          │
│                                                                 │
│  async def _async_update_data(self) -> Stats:                  │
│      # Await async library methods directly                    │
│      stats = await self._client.get_stats()                    │
│      await self._fetch_current_mode()                          │
│      return stats                                              │
│                                                                 │
│  async def _fetch_current_mode(self) -> None:                  │
│      # Await async library methods directly                    │
│      status = await self._client._switch_status()              │
│      self.current_mode = self._map_mode(status)                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  INCORRECT (Previous Implementation)                            │
│                                                                 │
│  async def _async_update_data(self) -> Stats:                  │
│      # ❌ Using executor on async method returns coroutine     │
│      stats = await self.hass.async_add_executor_job(           │
│          self._client.get_stats  # Returns coroutine object!   │
│      )                                                          │
│      # Result: 'coroutine' object has no attribute 'current'   │
└─────────────────────────────────────────────────────────────────┘

Rule: If library method is "async def" → use "await"
      If library method is "def" (sync) → use executor_job
```

## Entity Availability Logic

```
┌─────────────────────────────────────────────────────────────────┐
│  Sensor Entities                                                │
│                                                                 │
│  Available when:                                                │
│  • coordinator.last_update_success == True                      │
│    (inherited from CoordinatorEntity)                           │
│                                                                 │
│  Special cases:                                                 │
│  • Ambient Temp: Also requires ambient_temp is not None        │
│  • Charge Rate: Always available when coordinator succeeds     │
│  • Time to Full: Always available when coordinator succeeds    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Binary Sensor (Charging Limited)                               │
│                                                                 │
│  Available when:                                                │
│  • coordinator.last_update_success == True                      │
│  • coordinator.charging_power_limited is not None              │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Select Entity (Operating Mode)                                 │
│                                                                 │
│  Available when:                                                │
│  • coordinator.last_update_success == True                      │
│    (mode selection works even if current_mode is None)          │
│                                                                 │
│  This allows users to change mode even when the current         │
│  mode cannot be read from the gateway.                          │
└─────────────────────────────────────────────────────────────────┘
```

## File Structure

```
custom_components/franklinwh/
│
├── __init__.py              # Integration entry point
│   └── async_setup_entry() - Creates coordinator, sets up platforms
│
├── manifest.json            # Integration metadata
│   └── Requires: franklinwh>=0.4.1
│
├── config_flow.py           # Configuration UI (not shown in detail)
│
├── const.py                 # Constants
│   ├── DOMAIN = "franklinwh"
│   ├── UPDATE_INTERVAL = 60s
│   └── Mode constants (MODE_TIME_OF_USE, etc.)
│
├── coordinator.py           # ⭐ Core data management
│   ├── FranklinWHCoordinator
│   ├── MODE_VALUE_MAP
│   ├── Retry logic (MAX_RETRIES=2, RETRY_DELAY=3s)
│   └── Properties: current_charge_rate, time_to_full_charge
│
├── sensor.py                # 17 sensor entities
│   ├── SENSORS (descriptions)
│   ├── FranklinWHSensor (base)
│   ├── FranklinWHAmbientTempSensor
│   ├── FranklinWHChargeRateSensor
│   └── FranklinWHTimeToFullSensor
│
├── binary_sensor.py         # 1 binary sensor
│   └── FranklinWHChargingLimitedSensor
│
├── select.py                # 1 select entity
│   └── FranklinWHModeSelect
│       └── Calls coordinator.async_set_mode()
│
└── switch.py                # Dynamic smart switch entities
    └── FranklinWHSmartSwitch
        └── Calls coordinator.async_set_smart_switch_state()
```

## Error Handling Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│  Error Type                  │  Handling Strategy               │
├──────────────────────────────┼──────────────────────────────────┤
│  DeviceTimeoutException      │  • Retry up to 3 times           │
│  GatewayOfflineException     │  • Wait 3s between retries       │
│                              │  • Log warnings                  │
│                              │  • Fail update after max retries │
├──────────────────────────────┼──────────────────────────────────┤
│  Unknown mode value          │  • Log warning with value        │
│  (e.g., 113349)              │  • Default to MODE_TIME_OF_USE   │
│                              │  • Continue operation            │
│                              │  • Ask user to report to library │
├──────────────────────────────┼──────────────────────────────────┤
│  Mode fetch failure          │  • Log error                     │
│                              │  • Set current_mode = None       │
│                              │  • Continue with sensor updates  │
│                              │  • Mode selection still works    │
├──────────────────────────────┼──────────────────────────────────┤
│  Charging limited fetch fail │  • Log debug message             │
│                              │  • Set charging_limited = None   │
│                              │  • Binary sensor unavailable     │
├──────────────────────────────┼──────────────────────────────────┤
│  Authentication errors       │  • Raise ConfigEntryAuthFailed   │
│                              │  • Trigger re-authentication     │
└──────────────────────────────┴──────────────────────────────────┘
```

## Key Design Decisions

### 1. **Coordinator Pattern**
- Centralized data fetching prevents multiple API calls
- All entities share the same data source
- Update interval (60s) applies to all sensors

### 2. **Custom Mode Mapping**
- Library only knows standard modes (9322, 9323, 9324)
- Integration maps custom modes (113349, 117082, 46540)
- Uses `_switch_status()` to avoid KeyError from library's `get_mode()`

### 3. **Graceful Degradation**
- Mode fetch failure doesn't break sensors
- Unknown modes default to safe value (TOU)
- Mode selection works even when current mode is unknown

### 4. **Retry Logic**
- Transient network issues are retried automatically
- Different handling for critical (stats) vs optional (mode) data
- User sees fewer "unavailable" states

### 5. **Pure Async Pattern**
- Library methods are async, awaited directly
- No executor jobs for async methods
- Faster, more efficient, no coroutine errors

### 6. **Calculated Sensors**
- Charge rate calculated from battery_use (negative = charging)
- Time to full charge uses 15kWh capacity constant
- Real-time values more useful than predictions
