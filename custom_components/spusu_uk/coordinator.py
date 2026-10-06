"""Poll usage and renew rejected sessions without hiding readings mid-renewal."""

import asyncio
import logging
from contextlib import suppress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SessionExpired, SpusuClient, SpusuError
from .auth import ImapTokenReceiver
from .const import CONF_ACCOUNT, CONF_SESSION, DOMAIN, UPDATE_INTERVAL
from .models import Metric, parse_usage

_LOGGER = logging.getLogger(__name__)


class SpusuCoordinator(DataUpdateCoordinator[dict[tuple[str, str, str], Metric]]):
    """One coordinator per account, with one in-flight update at a time."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SpusuClient,
        receiver: ImapTokenReceiver,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.receiver = receiver
        self.renewing = False
        self.auth_failed = False
        self._update_task: asyncio.Task | None = None

    def _save_cookie(self) -> None:
        if (
            self.client.cookie
            and self.config_entry.data.get(CONF_SESSION) != self.client.cookie
        ):
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_SESSION: self.client.cookie},
            )

    async def async_shutdown(self) -> None:
        """Cancel a pending token wait as well as scheduled polling."""
        await super().async_shutdown()
        task = self._update_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _async_update_data(self) -> dict[tuple[str, str, str], Metric]:
        self._update_task = asyncio.current_task()
        try:
            return await self._fetch_usage()
        finally:
            self._update_task = None

    async def _fetch_usage(self) -> dict[tuple[str, str, str], Metric]:
        if self.auth_failed:
            raise ConfigEntryAuthFailed("Session renewal requires reauthentication")
        try:
            try:
                response = await self.client.usage()
            except SessionExpired:
                self.renewing = True
                self.async_update_listeners()
                try:
                    await self.receiver.authenticate(
                        self.client, self.config_entry.data[CONF_ACCOUNT]
                    )
                    self._save_cookie()
                except SpusuError:
                    self.auth_failed = True
                    raise ConfigEntryAuthFailed(
                        "Unable to renew Spusu session"
                    ) from None
                finally:
                    # Do not notify while the update still holds old data; the
                    # coordinator publishes success/failure when this returns.
                    self.renewing = False
                try:
                    response = await self.client.usage()
                except SessionExpired:
                    self.auth_failed = True
                    raise ConfigEntryAuthFailed(
                        "Renewed Spusu session was rejected"
                    ) from None
            metrics = parse_usage(response)
            self._save_cookie()
            return metrics
        except SpusuError as err:
            raise UpdateFailed(str(err)) from None
