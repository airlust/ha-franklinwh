# FranklinWH Energy Storage Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

This custom integration allows you to monitor and control your FranklinWH Whole Home battery system through Home Assistant.

## Features

- **Real-time Power Monitoring**
  - Solar power production
  - Battery charge/discharge power
  - Grid import/export power
  - Home load consumption
  - Generator power (if equipped)

- **Battery Monitoring**
  - State of charge (SOC)
  - Daily charge/discharge statistics

- **Energy Statistics**
  - Daily solar generation
  - Daily grid import/export
  - Daily consumption totals
  - Energy dashboard integration

- **System Control**
  - Switch between operating modes (Time of Use, Self Consumption, Backup)
  - Control smart circuits (if equipped)

- **Diagnostic Sensors**
  - Grid status monitoring
  - Connection health

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add the URL: `https://github.com/airlust/ha-franklinwh`
6. Select category: "Integration"
7. Click "Add"
8. Find "FranklinWH Energy Storage" in HACS and click "Download"
9. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/franklinwh` directory to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to Settings → Devices & Services
2. Click "Add Integration"
3. Search for "FranklinWH Energy Storage"
4. Enter your credentials:
   - **Email**: Your FranklinWH account email
   - **Password**: Your FranklinWH account password
   - **Gateway ID**: Your gateway Serial Number (found in the FranklinWH app under More → Site Address)

## Entities

### Sensors

#### Power Sensors (Instantaneous)
- `sensor.franklinwh_XXXXXX_solar_power` - Current solar production (W)
- `sensor.franklinwh_XXXXXX_battery_power` - Current battery power (W, negative = charging, positive = discharging)
- `sensor.franklinwh_XXXXXX_grid_power` - Current grid power (W, negative = importing, positive = exporting)
- `sensor.franklinwh_XXXXXX_load_power` - Current home consumption (W)
- `sensor.franklinwh_XXXXXX_generator_power` - Current generator output (W, if equipped)

#### Battery Sensors
- `sensor.franklinwh_XXXXXX_battery_soc` - Battery state of charge (%)

#### Energy Sensors (Daily Totals)
- `sensor.franklinwh_XXXXXX_solar_energy_today` - Solar energy generated today (kWh)
- `sensor.franklinwh_XXXXXX_battery_charge_today` - Battery energy charged today (kWh)
- `sensor.franklinwh_XXXXXX_battery_discharge_today` - Battery energy discharged today (kWh)
- `sensor.franklinwh_XXXXXX_grid_import_today` - Energy imported from grid today (kWh)
- `sensor.franklinwh_XXXXXX_grid_export_today` - Energy exported to grid today (kWh)
- `sensor.franklinwh_XXXXXX_consumption_today` - Total energy consumed today (kWh)

#### Diagnostic Sensors
- `sensor.franklinwh_XXXXXX_grid_status` - Grid connection status (normal/down/offline)

### Controls

#### Operating Mode
- `select.franklinwh_XXXXXX_operating_mode` - Switch between operating modes:
  - **Time of Use**: Optimize based on utility rate schedules
  - **Self Consumption**: Maximize use of solar energy
  - **Backup**: Reserve battery for outages

  The entity also exposes a `profile_name` attribute holding the gateway's own
  name for the active profile, which is usually the rate plan (e.g. `EV2A`).

#### Smart Circuits
- `switch.franklinwh_XXXXXX_circuit_X` - Control individual smart circuits (if equipped)

## Energy Dashboard Integration

This integration is fully compatible with Home Assistant's Energy Dashboard. The energy sensors are automatically configured with the correct device classes and state classes.

To add FranklinWH to your Energy Dashboard:

1. Go to Settings → Dashboards → Energy
2. Configure the following:
   - **Solar Production**: Select `sensor.franklinwh_XXXXXX_solar_energy_today`
   - **Grid Consumption**: Select `sensor.franklinwh_XXXXXX_grid_import_today`
   - **Return to Grid**: Select `sensor.franklinwh_XXXXXX_grid_export_today`
   - **Battery Systems**:
     - Energy in: `sensor.franklinwh_XXXXXX_battery_charge_today`
     - Energy out: `sensor.franklinwh_XXXXXX_battery_discharge_today`

## Update Interval

The integration polls the FranklinWH API every 30 seconds by default to fetch updated data.

## Troubleshooting

### Authentication Errors
- Verify your email and password are correct
- Check if your account is locked (try logging into the FranklinWH app)
- Ensure your Gateway ID is correct (check in the app under More → Site Address)

### Connection Errors
- Verify your Home Assistant has internet access
- Check if the FranklinWH service is operational
- Review Home Assistant logs for detailed error messages

### Smart Circuits Not Appearing
Smart circuit switches will only appear if your FranklinWH system has smart circuits configured. The exact implementation depends on how your system exposes this data through the API.

## Known Limitations

- **Smart Circuits**: The smart circuit implementation is basic and may need adjustments based on your specific system configuration
- **SOC Parameter**: When changing modes, the state-of-charge parameter is set to 100% by default

## Credits

This integration uses the [franklinwh-python](https://github.com/richo/franklinwh-python) library by [@richo](https://github.com/richo).

## License

This project is licensed under the MIT License.

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/airlust/ha-franklinwh/issues).
