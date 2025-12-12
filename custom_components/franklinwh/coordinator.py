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
        # Client expects TokenFetcher object and handles token refresh automatically
        self._client = Client(self._token_fetcher, self.gateway_id)
        self.current_mode: str | None = None
        self.ambient_temp: float | None = None

    async def _async_update_data(self) -> Stats:
        """Fetch data from FranklinWH with retry logic."""
        last_error = None

        # Retry logic for transient errors
        for attempt in range(MAX_RETRIES + 1):
            try:
                # Fetch stats - Client handles token refresh automatically
                stats = await self.hass.async_add_executor_job(self._client.get_stats)

                # Fetch current mode with same retry logic as stats
                await self._fetch_current_mode()

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
                status = await self.hass.async_add_executor_job(self._client._switch_status)

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
