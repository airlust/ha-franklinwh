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
│  │  • _fetch_battery_capacity() - Sums aPower ratedCapacity (once)   │  │
│  │  • _fetch_tou_schedule_if_needed() - Gets TOU (hourly)            │  │
│  │  • async_refresh_tou_schedule() - Manual TOU refresh              │  │
│  │  • async_set_mode() - Changes operating mode                       │  │
│  │  • async_set_smart_switch_state() - Controls smart switches       │  │
│  │                                                                     │  │
│  │  Properties:                                                        │  │
│  │  • current_charge_rate - Calculated from battery_use              │  │
│  │  • time_to_full_charge - Hours, 0 when full, None when idle       │  │
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
    │ • current.battery_   │      │ Resolves via:        │  │ coordinator. │
    │   soc                │      │   TOU profile list   │  │ charging_    │
    │ • current.grid_      │      │                      │  │ power_       │
    │   status             │      │ Sets:                │  │ limited      │
    │ • current.generator_ │      │ coordinator.         │  │              │
    │   production         │      │   current_mode       │  └──────────────┘
    │ • totals.solar       │      │ coordinator.         │
    │ • totals.battery_    │      │   ambient_temp       │
    │   charge/discharge   │      │                      │
    │ • totals.grid_       │      │ Resolves via:        │
    │   import/export      │      │  getGatewayTouListV2 │
    │ • totals.home_use    │      │  → profile workMode  │
    │                      │      │                      │
    │ Stored in:           │      │ Sets:                │
    │ coordinator.data     │      │ coordinator.         │
    └──────────────────────┘      │   current_mode       │
                                  │   current_mode_name  │
                                  │                      │
                                  │ Unresolved → None,   │
                                  │ state shows unknown  │
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

## Mode Resolution

The gateway identifies its active mode by a numeric `runingMode`. That number is
**not** a stable constant: it is a per-account database id for a TOU profile row.
The same account reports different ids for the same mode on two different
gateways, and ids from separate accounts interleave numerically, which is what a
row id from a shared sequence looks like. No table of such numbers can ever be
complete.

What *is* stable across accounts is `workMode`, the gateway's own mode enum, which
`getGatewayTouListV2` returns alongside every profile. The integration asks the
gateway and reads that enum; it keeps no table of ids at all.

```
┌─────────────────────────────────────────────────────────────────┐
│  FranklinWH Gateway Reports                                     │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ runingMode (int) — a per-account profile id
                            ▼
    ┌────────────────────────────────────────────────────────┐
    │  _resolve_mode_from_tou_list()                         │
    │                                                        │
    │  GET hes-gateway/terminal/tou/getGatewayTouListV2      │
    │    → list of profiles, each with id + workMode + name  │
    │    → currendId names the active profile                │
    │                                                        │
    │  Match runingMode against the profile ids; if it does  │
    │  not appear, use currendId. Then read that profile's   │
    │  workMode:                                             │
    │                                                        │
    │    workMode 1 → MODE_TIME_OF_USE                       │
    │    workMode 2 → MODE_SELF_CONSUMPTION                  │
    │    workMode 3 → MODE_BACKUP                            │
    │                                                        │
    │  Needs no per-account constants, so it works on any    │
    │  account without a code change.                        │
    └────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────────┐
         resolved      transient error    gateway answered,
              │        (backend down)     mode unrecognized
              │             │                     │
              ▼             ▼                     ▼
  ┌──────────────────────┐ ┌──────────────┐ ┌──────────────────────┐
  │ coordinator.         │ │ Re-raised to │ │ current_mode = None  │
  │   current_mode       │ │ the update   │ │ warning logged, HA   │
  │   current_mode_name  │ │ cycle: keep  │ │ state shows unknown  │
  │   (e.g. "EV2A")      │ │ last known,  │ │ (issue #6: never     │
  └──────────────────────┘ │ then go      │ │ guess a real mode)   │
              │            │ unavailable  │ └──────────────────────┘
              │            └──────────────┘
              ▼
        ┌──────────────────────────────────┐
        │  FranklinWHModeSelect entity     │
        │  displays in Home Assistant UI   │
        │  profile_name as an attribute    │
        └──────────────────────────────────┘
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
│   ├── Mode constants (MODE_TIME_OF_USE, etc.)
│   └── WORK_MODE_TO_KEY (gateway workMode enum → mode key)
│
├── coordinator.py           # ⭐ Core data management
│   ├── FranklinWHCoordinator
│   ├── _resolve_mode_from_tou_list() (mode lookup, no id table)
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
│  Mode unresolvable, gateway  │  • Log warning with value        │
│  reachable (e.g. a mode      │  • Set current_mode = None       │
│  newer than this release)    │    (HA state shows "unknown")    │
│                              │  • Never guess a real mode:      │
│                              │    see issue #6                  │
│                              │  • Ask user to report it         │
├──────────────────────────────┼──────────────────────────────────┤
│  Unrecognized workMode       │  • Log warning with profile name │
│                              │  • Set current_mode = None       │
│                              │  • Ask user to report it         │
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

### 2. **Mode Resolution via the Gateway, Not a Table**
- `runingMode` values are per-account database ids, not constants, so a lookup
  table can never cover every account
- Resolve through `getGatewayTouListV2` and read the profile's `workMode`, which
  is stable across accounts
- **No id table is kept at all.** An earlier one grew an entry per bug report and
  helped only the users who had reported theirs. It was also a hazard: because an
  unrecognized `workMode` and a failed request both mean "unresolved", a table
  consulted on failure answers a *new* mode with whatever that id used to mean —
  the mis-mapping of issue #6
- Uses `_switch_status()` to avoid KeyError from library's `get_mode()`

### 3. **Graceful Degradation**
- Mode fetch failure doesn't break sensors
- Unresolvable modes set `current_mode = None` so the HA state reads "unknown";
  they are never guessed at, since a wrong-but-plausible mode hides the problem
  for weeks (issue #6)
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
- Time to full charge uses `battery_capacity`, summed from the gateway's per-unit `ratedCapacity` (falls back to `DEFAULT_BATTERY_CAPACITY` until first fetched)
- Reads `0` at or above `BATTERY_FULL_SOC` (99), since a gateway need not ever report exactly 100, and `unknown` below `MIN_MEANINGFUL_CHARGE_RATE` (0.1 kW), since a balancing trickle is not a charge worth estimating from
- Real-time values more useful than predictions
