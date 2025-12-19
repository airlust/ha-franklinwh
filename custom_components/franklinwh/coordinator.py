"""DataUpdateCoordinator for FranklinWH Energy Storage."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

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

    async def _ensure_client(self) -> None:
        """Ensure client is initialized."""
        if self._client is None:
            # Client creation does SSL setup, but it's fast enough to not need executor
            self._client = Client(self._token_fetcher, self.gateway_id)

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

                # Success! If we retried, log success
                if attempt > 0:
                    _LOGGER.info("Successfully fetched data after %d retry(ies)", attempt)

                return stats

            except (DeviceTimeoutException, GatewayOfflineException) as err:
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

                    # Also extract ambient temperature from the same status call
                    if "t_amb" in status:
                        self.ambient_temp = status["t_amb"]
                        _LOGGER.debug("Fetched ambient temperature: %s°C", self.ambient_temp)

                    if attempt > 0:
                        _LOGGER.info("Successfully fetched mode after %d retry(ies)", attempt)
                    return
                else:
                    _LOGGER.warning("_switch_status() returned None or missing runingMode")
                    self.current_mode = None
                    self.ambient_temp = None
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
                self.ambient_temp = None
                return

            except Exception as mode_err:
                # Non-retryable error - log but don't fail the entire update
                _LOGGER.error("Failed to fetch current mode: %s. Mode will be unavailable.", mode_err, exc_info=True)
                self.current_mode = None
                self.ambient_temp = None
                return

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
