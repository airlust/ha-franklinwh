"""DataUpdateCoordinator for FranklinWH Energy Storage."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

import httpx
from franklinwh import Client, Mode, Stats, TokenFetcher
from franklinwh.client import DeviceTimeoutException, GatewayOfflineException

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .const import CONF_GATEWAY_ID, DOMAIN, UPDATE_INTERVAL, MODE_TIME_OF_USE, MODE_SELF_CONSUMPTION, MODE_BACKUP

_LOGGER = logging.getLogger(__name__)

# Retry configuration for transient errors
MAX_RETRIES = 2
RETRY_DELAY = 3  # seconds

# Map numeric mode values from API to our mode keys
# The franklinwh library only knows about standard modes: 9322, 9323, 9324
# but gateways can return different values for customized modes
MODE_VALUE_MAP = {
    # Standard modes
    9322: MODE_TIME_OF_USE,
    9323: MODE_SELF_CONSUMPTION,
    9324: MODE_BACKUP,
    # Customized modes (observed on user's gateway)
    113349: MODE_TIME_OF_USE,       # E-TOU-C (customized Time of Use)
    117082: MODE_SELF_CONSUMPTION,  # Customized Self Consumption
    46540: MODE_BACKUP,              # Customized Emergency Backup
}


class FranklinWHCoordinator(DataUpdateCoordinator[Stats]):
    """Class to manage fetching FranklinWH data."""

    def __init__(
        self,
        hass: HomeAssistant,
        email: str,
        password: str,
        gateway_id: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.email = email
        self.password = password
        self.gateway_id = gateway_id
        self._token_fetcher = TokenFetcher(email, password)
        # Client will be created in first update to avoid blocking I/O in __init__
        self._client: Client | None = None
        self.current_mode: str | None = None
        self.ambient_temp: float | None = None
        self.charging_power_limited: bool | None = None
        self.battery_capacity: float = 15.0  # kWh - will be updated from device info
        self.tou_schedule: dict | None = None  # TOU rate schedule data
        self._last_tou_fetch: float = 0  # Timestamp of last TOU fetch

    async def _ensure_client(self) -> None:
        """Ensure client is initialized."""
        if self._client is None:
            # Client creation does SSL setup, run in executor to avoid blocking
            self._client = await self.hass.async_add_executor_job(
                Client, self._token_fetcher, self.gateway_id
            )

    async def _async_update_data(self) -> Stats:
        """Fetch data from FranklinWH with retry logic."""
        # Ensure client is initialized (first time only)
        if self._client is None:
            await self._ensure_client()

        last_error = None

        # Retry logic for transient errors
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Fetch stats - library method is async, await it directly
                stats = await self._client.get_stats()

                # Fetch current mode with same retry logic as stats
                await self._fetch_current_mode()

                # Fetch charging power limited status
                await self._fetch_charging_limited()

                # Fetch ambient temperature from _status endpoint
                await self._fetch_ambient_temp()

                # Fetch TOU schedule once per hour (don't fail if it errors)
                await self._fetch_tou_schedule_if_needed()

                # Success! If we retried, log success
                if attempt > 0:
                    _LOGGER.info("Successfully fetched data after %d retry(ies)", attempt)

                return stats

            except (DeviceTimeoutException, GatewayOfflineException, httpx.ReadTimeout, httpx.ConnectTimeout) as err:
                last_error = err

                # If we have retries left, wait and try again
                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Transient error fetching data (attempt %d/%d): %s. Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES + 1,
                        err,
                        RETRY_DELAY,
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                # Out of retries, fail the update
                _LOGGER.error("Failed to fetch data after %d attempts: %s", MAX_RETRIES + 1, err)
                raise UpdateFailed(f"Failed after {MAX_RETRIES + 1} attempts: {err}") from err

            except Exception as err:
                # Non-retryable error (auth, etc.)
                _LOGGER.exception("Failed to fetch stats from gateway")
                raise UpdateFailed(f"Failed to update data: {err}") from err

        # Should never reach here, but just in case
        raise UpdateFailed(f"Failed to update data: {last_error}") from last_error

    async def _fetch_current_mode(self) -> None:
        """Fetch current operating mode with retry logic.

        Uses _switch_status() directly instead of get_mode() to avoid
        KeyError when gateway returns unsupported mode values.
        """
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                # Call _switch_status() directly to get raw mode value
                # This avoids the KeyError that get_mode() raises for unknown modes
                # Note: _switch_status might be async, await it directly
                status = await self._client._switch_status()

                if status and "runingMode" in status:
                    raw_mode = status["runingMode"]
                    _LOGGER.debug("Fetched raw mode value: %s", raw_mode)

                    # Map the numeric mode to our mode key, with fallback for unknown modes
                    if raw_mode in MODE_VALUE_MAP:
                        self.current_mode = MODE_VALUE_MAP[raw_mode]
                        _LOGGER.debug("Mapped mode %s to %s", raw_mode, self.current_mode)
                    else:
                        # Unknown mode - default to time_of_use as a safe fallback
                        _LOGGER.warning(
                            "Unknown mode value %s from gateway. Treating as time_of_use. "
                            "Please report this to https://github.com/richo/franklinwh-python/issues",
                            raw_mode
                        )
                        self.current_mode = MODE_TIME_OF_USE

                    if attempt > 0:
                        _LOGGER.info("Successfully fetched mode after %d retry(ies)", attempt)
                    return
                else:
                    _LOGGER.warning("_switch_status() returned None or missing runingMode")
                    self.current_mode = None
                    return

            except (DeviceTimeoutException, GatewayOfflineException) as err:
                last_error = err

                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Timeout fetching mode (attempt %d/%d): %s. Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES + 1,
                        err,
                        RETRY_DELAY,
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                # Out of retries - log but don't fail the entire update
                _LOGGER.error("Failed to fetch mode after %d attempts: %s. Mode will be unavailable.", MAX_RETRIES + 1, err)
                self.current_mode = None
                return

            except Exception as mode_err:
                # Non-retryable error - log but don't fail the entire update
                _LOGGER.error("Failed to fetch current mode: %s. Mode will be unavailable.", mode_err, exc_info=True)
                self.current_mode = None
                return

    async def _fetch_ambient_temp(self) -> None:
        """Fetch ambient temperature from _status endpoint."""
        try:
            if self._client is None:
                self.ambient_temp = None
                return

            # Call _status() to get raw status data including t_amb
            status = await self._client._status()

            if status and "t_amb" in status:
                self.ambient_temp = status["t_amb"]
                _LOGGER.debug("Fetched ambient temperature: %s°C", self.ambient_temp)
            else:
                self.ambient_temp = None
                _LOGGER.debug("No ambient temperature in _status response")

        except Exception as err:
            _LOGGER.debug("Failed to fetch ambient temperature: %s", err)
            self.ambient_temp = None

    async def _fetch_charging_limited(self) -> None:
        """Fetch charging power limited status from entrance info."""
        try:
            if self._client is None:
                self.charging_power_limited = None
                return
            # Build the payload to fetch entrance info
            # This contains the chargingPowerLimited flag
            payload = self._client._build_payload(
                201,
                {"gatewayId": self.gateway_id}
            )
            response = await self._client._mqtt_send(payload)

            if response and "result" in response:
                result = response["result"]
                if "chargingPowerLimited" in result:
                    self.charging_power_limited = result["chargingPowerLimited"]
                else:
                    self.charging_power_limited = None
            else:
                self.charging_power_limited = None

        except Exception as err:
            _LOGGER.debug("Failed to fetch charging limited status: %s", err)
            self.charging_power_limited = None

    async def _fetch_tou_schedule_if_needed(self) -> None:
        """Fetch TOU schedule only if it's been more than an hour since last fetch."""
        import time
        current_time = time.time()
        time_since_last_fetch = current_time - self._last_tou_fetch

        # Fetch if never fetched (0) or if more than 1 hour has passed
        if self._last_tou_fetch == 0 or time_since_last_fetch >= 3600:
            await self._fetch_tou_schedule()
            self._last_tou_fetch = current_time

    async def _fetch_tou_schedule(self) -> None:
        """Fetch TOU rate schedule from gateway."""
        try:
            if self._client is None:
                self.tou_schedule = None
                return

            # Use _get() method for hes-gateway endpoints (not _mqtt_send)
            # This endpoint doesn't require gatewayId in the payload
            url = self._client.url_base + "hes-gateway/terminal/tou/getTouDispatchDetail"
            _LOGGER.info("Fetching TOU schedule from API...")
            response = await self._client._get(url, None)

            if response and "result" in response:
                self.tou_schedule = response["result"]
                _LOGGER.info("Fetched TOU schedule successfully")

                # Log schedule structure for debugging
                if "strategyList" in self.tou_schedule:
                    _LOGGER.info("TOU schedule has %d season(s)", len(self.tou_schedule["strategyList"]))
                    for season in self.tou_schedule["strategyList"]:
                        _LOGGER.info("  Season months: %s", season.get("month"))
                        if "dayTypeVoList" in season and season["dayTypeVoList"]:
                            day_type = season["dayTypeVoList"][0]
                            if "detailVoList" in day_type:
                                _LOGGER.info("  Periods in this season:")
                                for period in day_type["detailVoList"]:
                                    _LOGGER.info("    %s: %s-%s (waveType=%s, rate_peak=%s, rate_valley=%s)",
                                                 period.get("name"),
                                                 period.get("startHourTime"),
                                                 period.get("endHourTime"),
                                                 period.get("waveType"),
                                                 period.get("eleticRatePeak"),
                                                 period.get("eleticRateValley"))
            else:
                self.tou_schedule = None
                _LOGGER.warning("No TOU schedule data in response")

        except Exception as err:
            _LOGGER.error("Failed to fetch TOU schedule: %s", err)
            self.tou_schedule = None

    async def async_refresh_tou_schedule(self) -> None:
        """Manually refresh TOU schedule (called by button entity)."""
        _LOGGER.info("Manual TOU schedule refresh requested")
        await self._fetch_tou_schedule()
        import time
        self._last_tou_fetch = time.time()
        # Request coordinator refresh to update all entities
        await self.async_request_refresh()

    @property
    def current_charge_rate(self) -> float | None:
        """Calculate current charge rate in kW (positive value when charging)."""
        if not self.data or not self.data.current:
            return None

        battery_power = self.data.current.battery_use
        # Negative battery_use means charging, return as positive charge rate
        if battery_power is not None and battery_power < 0:
            return abs(battery_power)
        return 0.0

    @property
    def time_to_full_charge(self) -> float | None:
        """Calculate time to full charge in hours."""
        if not self.data or not self.data.current:
            return None

        current_soc = self.data.current.battery_soc
        charge_rate = self.current_charge_rate

        if current_soc is None or charge_rate is None or charge_rate == 0:
            return None

        if current_soc >= 100:
            return 0.0

        # Calculate remaining capacity and time
        remaining_capacity = (100 - current_soc) / 100 * self.battery_capacity
        time_hours = remaining_capacity / charge_rate

        return time_hours

    def _get_current_season(self) -> dict | None:
        """Get the current season's TOU schedule based on current month."""
        if not self.tou_schedule or "strategyList" not in self.tou_schedule:
            return None

        from homeassistant.util import dt as dt_util
        current_month = dt_util.now().month

        for season in self.tou_schedule["strategyList"]:
            months_str = season.get("month", "")
            if months_str:
                months = [int(m) for m in months_str.split(",")]
                if current_month in months:
                    return season

        return None

    def _get_current_rate_period(self) -> dict | None:
        """Get the current rate period details."""
        season = self._get_current_season()
        if not season or "dayTypeVoList" not in season:
            return None

        from datetime import datetime
        from homeassistant.util import dt as dt_util
        current_time = dt_util.now().time()
        _LOGGER.info("Looking for TOU period at current time: %s", current_time)

        # Get the first day type (usually "Every day")
        day_type = season["dayTypeVoList"][0]
        if "detailVoList" not in day_type:
            return None

        # Log all periods for debugging
        _LOGGER.info("Available TOU periods:")
        for p in day_type["detailVoList"]:
            _LOGGER.info("  %s: %s - %s (waveType=%s)",
                         p.get("name"),
                         p.get("startHourTime"),
                         p.get("endHourTime"),
                         p.get("waveType"))

        # Find the current time period
        for period in day_type["detailVoList"]:
            start_str = period.get("startHourTime", "")
            end_str = period.get("endHourTime", "")

            if not start_str or not end_str:
                continue

            # Handle 24:00 (end of day) by converting to 23:59:59
            if end_str == "24:00":
                end_str = "23:59"

            # Parse time strings (format: "HH:MM")
            start_parts = start_str.split(":")
            end_parts = end_str.split(":")

            if len(start_parts) == 2 and len(end_parts) == 2:
                start_time = datetime.strptime(start_str, "%H:%M").time()
                end_time = datetime.strptime(end_str, "%H:%M").time()

                _LOGGER.info("Checking period %s: %s <= %s <= %s?",
                             period.get("name"), start_time, current_time, end_time)

                # Handle periods that cross midnight
                if end_time < start_time:
                    if current_time >= start_time or current_time < end_time:
                        _LOGGER.info("Matched period (crosses midnight): %s", period.get("name"))
                        return {**period, **day_type}
                else:
                    # Use <= for end time to include the exact end minute
                    if start_time <= current_time <= end_time:
                        _LOGGER.info("Matched period: %s", period.get("name"))
                        return {**period, **day_type}

        _LOGGER.warning("No matching TOU period found for time %s", current_time)
        return None

    @property
    def tou_current_period(self) -> str | None:
        """Get the current TOU period name (e.g., 'on-peak', 'off-peak')."""
        period = self._get_current_rate_period()
        return period.get("name") if period else None

    @property
    def tou_current_rate(self) -> float | None:
        """Get the current electricity rate in $/kWh."""
        period = self._get_current_rate_period()
        if not period:
            return None

        wave_type = period.get("waveType")
        if wave_type == 2:  # Peak
            return period.get("eleticRatePeak")
        elif wave_type == 0:  # Off-peak/Valley
            return period.get("eleticRateValley")
        elif wave_type == 1:  # Shoulder
            return period.get("eleticRateShoulder")

        return None

    def _get_next_rate_period(self) -> dict | None:
        """Get the next rate period details."""
        season = self._get_current_season()
        if not season or "dayTypeVoList" not in season:
            return None

        from homeassistant.util import dt as dt_util
        from datetime import datetime
        current_time = dt_util.now().time()

        day_type = season["dayTypeVoList"][0]
        if "detailVoList" not in day_type:
            return None

        periods = day_type["detailVoList"]

        # Find next period
        for i, period in enumerate(periods):
            start_str = period.get("startHourTime", "")
            if not start_str:
                continue

            start_time = datetime.strptime(start_str, "%H:%M").time()

            if current_time < start_time:
                return period

        # If no future period today, return first period of tomorrow
        if periods:
            return periods[0]

        return None

    @property
    def tou_next_period_start(self) -> str | None:
        """Get the start time of the next rate period."""
        period = self._get_next_rate_period()
        return period.get("startHourTime") if period else None

    @property
    def tou_next_period_name(self) -> str | None:
        """Get the name of the next rate period (e.g., 'on-peak', 'off-peak')."""
        period = self._get_next_rate_period()
        return period.get("name") if period else None

    @property
    def tou_next_period_rate(self) -> float | None:
        """Get the electricity rate for the next period in $/kWh."""
        period = self._get_next_rate_period()
        if not period:
            _LOGGER.info("No next period found for rate")
            return None

        _LOGGER.info("Next period data: %s", period)

        wave_type = period.get("waveType")
        if wave_type == 2:  # Peak
            return period.get("eleticRatePeak")
        elif wave_type == 0:  # Off-peak/Valley
            return period.get("eleticRateValley")
        elif wave_type == 1:  # Shoulder
            return period.get("eleticRateShoulder")

        return None

    @property
    def tou_utility_company(self) -> str | None:
        """Get the utility company name."""
        if not self.tou_schedule or "template" not in self.tou_schedule:
            return None
        return self.tou_schedule["template"].get("electricCompany")

    @property
    def tou_rate_plan(self) -> str | None:
        """Get the rate plan name."""
        if not self.tou_schedule or "template" not in self.tou_schedule:
            return None
        return self.tou_schedule["template"].get("gridType")

    async def async_set_mode(self, mode: Mode) -> None:
        """Set the operating mode with retry logic."""
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                await self.hass.async_add_executor_job(
                    self._client.set_mode, mode
                )
                # Success! Request immediate refresh to get updated data
                await self.async_request_refresh()

                if attempt > 0:
                    _LOGGER.info("Successfully set mode after %d retry(ies)", attempt)
                return

            except (DeviceTimeoutException, GatewayOfflineException) as err:
                last_error = err

                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Timeout setting mode (attempt %d/%d): %s. Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES + 1,
                        err,
                        RETRY_DELAY,
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                _LOGGER.error("Failed to set mode after %d attempts: %s", MAX_RETRIES + 1, err)
                raise UpdateFailed(f"Failed to set mode after {MAX_RETRIES + 1} attempts: {err}") from err

            except Exception as err:
                _LOGGER.exception("Failed to set mode")
                raise UpdateFailed(f"Failed to set mode: {err}") from err

        raise UpdateFailed(f"Failed to set mode: {last_error}") from last_error

    async def async_set_smart_switch_state(self, switch_id: str, state: bool) -> None:
        """Set smart switch state with retry logic."""
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                await self.hass.async_add_executor_job(
                    self._client.set_smart_switch_state, switch_id, state
                )
                # Success! Request immediate refresh
                await self.async_request_refresh()

                if attempt > 0:
                    _LOGGER.info("Successfully set smart switch state after %d retry(ies)", attempt)
                return

            except (DeviceTimeoutException, GatewayOfflineException) as err:
                last_error = err

                if attempt < MAX_RETRIES:
                    _LOGGER.warning(
                        "Timeout setting smart switch (attempt %d/%d): %s. Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES + 1,
                        err,
                        RETRY_DELAY,
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                _LOGGER.error("Failed to set smart switch after %d attempts: %s", MAX_RETRIES + 1, err)
                raise UpdateFailed(f"Failed to set smart switch after {MAX_RETRIES + 1} attempts: {err}") from err

            except Exception as err:
                _LOGGER.exception("Failed to set smart switch state")
                raise UpdateFailed(f"Failed to set smart switch state: {err}") from err

        raise UpdateFailed(f"Failed to set smart switch state: {last_error}") from last_error
