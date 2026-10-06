"""Spusu UK custom integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SpusuClient
from .auth import ImapTokenReceiver
from .const import CONF_IMAP_ENTRY, CONF_SESSION, DOMAIN
from .coordinator import SpusuCoordinator

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def get_receiver(hass: HomeAssistant, imap_entry_id: str) -> ImapTokenReceiver:
    """Serialize token requests using the same mailbox, including config flows."""
    receivers = hass.data.setdefault(DOMAIN, {})
    if imap_entry_id not in receivers:
        receivers[imap_entry_id] = ImapTokenReceiver(hass, imap_entry_id)
    return receivers[imap_entry_id]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    imap = hass.config_entries.async_get_entry(entry.data[CONF_IMAP_ENTRY])
    if imap is None or imap.domain != "imap":
        raise ConfigEntryError("Selected IMAP integration no longer exists")
    client = SpusuClient(async_get_clientsession(hass), entry.data.get(CONF_SESSION))
    coordinator = SpusuCoordinator(
        hass, entry, client, get_receiver(hass, imap.entry_id)
    )
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
