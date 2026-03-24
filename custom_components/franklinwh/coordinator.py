"""DataUpdateCoordinator for FranklinWH Energy Storage."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import inspect
import random
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

# Per-attempt retry delays for the main stats refresh
UPDATE_RETRY_DELAYS = [5, 15]  # seconds between update retries

# Optional safety knob: number of consecutive failed update cycles to tolerate
# while returning cached data (prevents entities flipping to "unavailable").
MAX_STALE_CYCLES = 10

# Adaptive polling/backoff (applies after an update fully fails, i.e. after retries)
MAX_BACKOFF_INTERVAL = timedelta(minutes=5)
BACKOFF_FACTOR = 2.0
BACKOFF_JITTER_PCT = 0.10  # +/- 10%

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


async def _async_resolve(value: Any) -> Any:
    """Resolve nested awaitables returned by franklinwh client methods.

    Some franklinwh versions return coroutine objects even after awaiting client calls.
    This helper awaits repeatedly until a concrete value is returned (or depth limit reached).
    """
    depth = 0
    while inspect.isawaitable(value) and depth < 5:
        value = await value
        depth += 1
    return value


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
        # Serialize all franklinwh client network calls to avoid overlapping
        # requests (which can trigger token/auth edge cases).
        self._client_lock = asyncio.Lock()
        self.current_mode: str | None = None
        self.ambient_temp: float | None = None
        self.charging_power_limited: bool | None = None
        self.battery_capacity: float = 15.0  # kWh - will be updated from device info
        self.tou_schedule: dict | None = None  # TOU rate schedule data
        self._last_tou_fetch: float = 0  # Timestamp of last TOU fetch

        # Adaptive polling/backoff state
        self._consecutive_update_failures: int = 0
        self._base_update_interval: timedelta = UPDATE_INTERVAL
        self._max_backoff_interval: timedelta = MAX_BACKOFF_INTERVAL

    async def _ensure_client(self) -> None:
        """Ensure client is initialized."""
        if self._client is None:
            # Client creation does SSL setup, run in executor to avoid blocking
            self._client = await self.hass.async_add_executor_job(
                Client, self._token_fetcher, self.gateway_id
            )

    def _set_update_interval(self, new_interval: timedelta, reason: str) -> None:
        """Update coordinator polling interval (adaptive backoff)."""
        # Prefer DataUpdateCoordinator's rescheduler if available so the new
        # interval takes effect immediately (not just after a restart).
        if self.update_interval != new_interval:
            if hasattr(self, "async_set_update_interval"):
                try:
                    self.async_set_update_interval(new_interval)
                except Exception:
                    # Fall back to simple assignment if HA's API differs.
                    self.update_interval = new_interval
            else:
                self.update_interval = new_interval

            _LOGGER.info("Polling interval set to %s (%s)", new_interval, reason)

    def _compute_backoff_interval(self) -> timedelta:
        """Compute next polling interval using exponential backoff + jitter."""
        base_seconds = self._base_update_interval.total_seconds()
        max_seconds = self._max_backoff_interval.total_seconds()

        # First failed update => base * 1, second => base * 2, third => base * 4, ...
        exp_seconds = base_seconds * (BACKOFF_FACTOR ** max(0, self._consecutive_update_failures - 1))
        exp_seconds = min(exp_seconds, max_seconds)

        jitter = exp_seconds * BACKOFF_JITTER_PCT
        exp_seconds = exp_seconds + random.uniform(-jitter, jitter)

        # Clamp and ensure we never go below base
        exp_seconds = max(base_seconds, min(exp_seconds, max_seconds))
        return timedelta(seconds=exp_seconds)

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
                async with self._client_lock:
                    stats = await _async_resolve(self._client.get_stats())

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

                # Reset adaptive backoff on success
                if self._consecutive_update_failures > 0:
                    self._consecutive_update_failures = 0
                    self._set_update_interval(self._base_update_interval, "recovered")

                return stats

            except (DeviceTimeoutException, GatewayOfflineException, httpx.ReadTimeout, httpx.ConnectTimeout) as err:
                last_error = err

                # If we have retries left, wait and try again
                if attempt < MAX_RETRIES:
                    idx = min(attempt, len(UPDATE_RETRY_DELAYS) - 1)
                    delay = UPDATE_RETRY_DELAYS[idx]
                    _LOGGER.warning(
                        "Transient error fetching data (attempt %d/%d): %s. Retrying in %d seconds...",
                        attempt + 1,
                        MAX_RETRIES + 1,
                        err,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                # Out of retries, apply adaptive backoff and either return cached data or fail the update
                self._consecutive_update_failures += 1
                backoff_interval = self._compute_backoff_interval()
                self._set_update_interval(
                    backoff_interval,
                    f"backoff after {self._consecutive_update_failures} failed update(s)",
                )

                # If we have cached data, keep entities available by returning stale values.
                # After MAX_STALE_CYCLES consecutive failed update cycles, mark unavailable.
                if self.data is not None:
                    if self._consecutive_update_failures <= MAX_STALE_CYCLES:
                        _LOGGER.warning(
                            "Gateway refresh timed out after %d attempts; keeping last known values (failure count=%d)",
                            MAX_RETRIES + 1,
                            self._consecutive_update_failures,
                        )
                        return self.data

                    _LOGGER.error(
                        "Exceeded max stale cycles (%d); marking unavailable",
                        MAX_STALE_CYCLES,
                    )

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
                async with self._client_lock:
                    status = await _async_resolve(self._client._switch_status())

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
            async with self._client_lock:
                status = await _async_resolve(self._client._status())

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
            async with self._client_lock:
                response = await _async_resolve(self._client._mqtt_send(payload))

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
            async with self._client_lock:
                response = await _async_resolve(self._client._get(url, None))

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
                # Merge day_type to include rate fields
                return {**period, **day_type}

        # If no future period today, return first period of tomorrow
        if periods:
            return {**periods[0], **day_type}

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
            return None

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
                # set_mode is async, await it directly (not via executor)
                async with self._client_lock:
                    await _async_resolve(self._client.set_mode(mode))
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
                # set_smart_switch_state is async, await it directly (not via executor)
                async with self._client_lock:
                    await _async_resolve(self._client.set_smart_switch_state(switch_id, state))
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
