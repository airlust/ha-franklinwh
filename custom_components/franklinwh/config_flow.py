"""Config flow for FranklinWH Energy Storage integration."""
from __future__ import annotations

import logging
from typing import Any

from franklinwh import Client, TokenFetcher
from franklinwh.client import InvalidCredentialsException, AccountLockedException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_GATEWAY_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_GATEWAY_ID): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    token_fetcher = TokenFetcher(data[CONF_EMAIL], data[CONF_PASSWORD])

    try:
        token = await hass.async_add_executor_job(token_fetcher.get_token)
    except InvalidCredentialsException as err:
        raise InvalidAuth from err
    except AccountLockedException as err:
        raise AccountLocked from err
    except Exception as err:
        _LOGGER.exception("Unexpected exception during authentication")
        raise CannotConnect from err

    # Create client and test connection
    client = Client(token, data[CONF_GATEWAY_ID])

    try:
        stats = await hass.async_add_executor_job(client.get_stats)
    except Exception as err:
        _LOGGER.exception("Failed to fetch stats from gateway")
        raise CannotConnect from err

    # Return info that you want to store in the config entry.
    return {
        "title": f"FranklinWH ({data[CONF_GATEWAY_ID]})",
        "gateway_id": data[CONF_GATEWAY_ID],
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FranklinWH Energy Storage."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except AccountLocked:
                errors["base"] = "account_locked"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Set unique ID to prevent duplicate entries
                await self.async_set_unique_id(user_input[CONF_GATEWAY_ID])
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class AccountLocked(HomeAssistantError):
    """Error to indicate the account is locked."""
