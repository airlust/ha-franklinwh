"""DataUpdateCoordinator for FranklinWH Energy Storage."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from franklinwh import Client, Stats, TokenFetcher
from franklinwh.client import DeviceTimeoutException, GatewayOfflineException

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .const import CONF_GATEWAY_ID, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


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

    async def _async_update_data(self) -> Stats:
        """Fetch data from FranklinWH."""
        # Fetch stats - Client handles token refresh automatically
        try:
            stats = await self.hass.async_add_executor_job(self._client.get_stats)
            return stats
        except DeviceTimeoutException as err:
            raise UpdateFailed(f"Device timeout: {err}") from err
        except GatewayOfflineException as err:
            raise UpdateFailed(f"Gateway offline: {err}") from err
        except Exception as err:
            _LOGGER.exception("Failed to fetch stats from gateway")
            raise UpdateFailed(f"Failed to update data: {err}") from err

    async def async_set_mode(self, mode: str, soc: int = 100) -> None:
        """Set the operating mode."""
        try:
            await self.hass.async_add_executor_job(
                self._client.set_mode, mode, soc
            )
            # Request immediate refresh
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.exception("Failed to set mode")
            raise UpdateFailed(f"Failed to set mode: {err}") from err

    async def async_set_smart_switch_state(self, switch_id: str, state: bool) -> None:
        """Set smart switch state."""
        try:
            await self.hass.async_add_executor_job(
                self._client.set_smart_switch_state, switch_id, state
            )
            # Request immediate refresh
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.exception("Failed to set smart switch state")
            raise UpdateFailed(f"Failed to set smart switch state: {err}") from err
