"""UI setup and reauthentication through existing IMAP events."""

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    ConfigEntrySelector,
    ConfigEntrySelectorConfig,
)

from . import get_receiver
from .api import (
    ConnectionFailure,
    InvalidResponse,
    InvalidToken,
    SpusuClient,
    SpusuError,
)
from .auth import TokenTimeout
from .const import CONF_ACCOUNT, CONF_IMAP_ENTRY, CONF_SESSION, DOMAIN
from .models import parse_usage


class SpusuConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._task: asyncio.Task | None = None
        self._error: str | None = None
        self._reauth_entry = None

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            account = str(user_input[CONF_ACCOUNT]).strip()
            imap = self.hass.config_entries.async_get_entry(user_input[CONF_IMAP_ENTRY])
            if not account or len(account) > 64 or any(c.isspace() for c in account):
                errors[CONF_ACCOUNT] = "invalid_account"
            elif imap is None or imap.domain != "imap":
                errors[CONF_IMAP_ENTRY] = "invalid_imap"
            else:
                await self.async_set_unique_id(account)
                self._abort_if_unique_id_configured()
                self._data = {CONF_ACCOUNT: account, CONF_IMAP_ENTRY: imap.entry_id}
                return await self.async_step_authenticate()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ACCOUNT): str,
                    # HA 2026.9's frontend cannot infer an initial value for
                    # config_entry selectors; an explicit empty default renders it.
                    vol.Required(CONF_IMAP_ENTRY, default=""): ConfigEntrySelector(
                        ConfigEntrySelectorConfig(integration="imap")
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        self._data = {
            CONF_ACCOUNT: entry_data[CONF_ACCOUNT],
            CONF_IMAP_ENTRY: entry_data[CONF_IMAP_ENTRY],
        }
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            imap = self.hass.config_entries.async_get_entry(user_input[CONF_IMAP_ENTRY])
            if imap is None or imap.domain != "imap":
                errors[CONF_IMAP_ENTRY] = "invalid_imap"
            else:
                self._data[CONF_IMAP_ENTRY] = imap.entry_id
                return await self.async_step_authenticate()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IMAP_ENTRY, default=self._data[CONF_IMAP_ENTRY]
                    ): ConfigEntrySelector(
                        ConfigEntrySelectorConfig(integration="imap")
                    ),
                }
            ),
            errors=errors,
        )

    async def _authenticate(self) -> None:
        client = SpusuClient(async_get_clientsession(self.hass))
        try:
            await get_receiver(self.hass, self._data[CONF_IMAP_ENTRY]).authenticate(
                client, self._data[CONF_ACCOUNT]
            )
            parse_usage(await client.usage())
            self._data[CONF_SESSION] = client.cookie
        except TokenTimeout:
            self._error = "token_timeout"
        except InvalidToken:
            self._error = "invalid_token"
        except InvalidResponse:
            self._error = "invalid_response"
        except ConnectionFailure:
            self._error = "cannot_connect"
        except SpusuError:
            self._error = "authentication_failed"

    async def async_step_authenticate(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(
                self._authenticate(), "Spusu UK authentication"
            )
        if not self._task.done():
            return self.async_show_progress(
                step_id="authenticate",
                progress_action="waiting_for_token",
                progress_task=self._task,
            )
        self._task.result()
        return self.async_show_progress_done(
            next_step_id="retry" if self._error else "finish"
        )

    async def async_step_retry(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._task = None
            self._error = None
            return await self.async_step_authenticate()
        return self.async_show_form(
            step_id="retry", data_schema=vol.Schema({}), errors={"base": self._error}
        )

    async def async_step_finish(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry, data_updates=self._data
            )
        return self.async_create_entry(title="Spusu UK", data=self._data)
