"""Test real HA classes with mocked network I/O. No live Spusu requests."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntries, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    instance.config_entries = ConfigEntries(instance, {})
    frame.async_setup(instance)
    yield instance
    await instance.async_stop()


@pytest.fixture
def entry(hass):
    value = ConfigEntry(
        domain="spusu_uk",
        title="Spusu UK",
        unique_id="synthetic-account",
        version=1,
        minor_version=1,
        source="user",
        options={},
        data={
            "account": "synthetic-account",
            "imap_entry_id": "imap-test",
            "session_cookie": "old-session",
        },
        discovery_keys={},
        subentries_data=[],
    )
    hass.config_entries._entries[value.entry_id] = value
    return value


@pytest.fixture
def imap_entry(hass):
    value = ConfigEntry(
        domain="imap",
        title="Test IMAP",
        unique_id="synthetic-mailbox",
        entry_id="imap-test",
        version=1,
        minor_version=1,
        source="user",
        data={},
        options={},
        discovery_keys={},
        subentries_data=[],
    )
    hass.config_entries._entries[value.entry_id] = value
    return value


@pytest.fixture
def usage():
    return json.loads(
        (Path(__file__).parent / "fixtures/usage_synthetic.json").read_text()
    )


@pytest.fixture
def client(usage):
    value = Mock()
    value.cookie = "old-session"
    value.usage = AsyncMock(return_value=usage)
    value.request_email = AsyncMock()
    value.login = AsyncMock()
    return value


@pytest.fixture(autouse=True)
def forbid_live_http_in_tests(monkeypatch):
    import aiohttp

    monkeypatch.setattr(
        aiohttp.ClientSession,
        "_request",
        AsyncMock(
            side_effect=AssertionError("Network disabled: replay saved API fixtures")
        ),
    )
