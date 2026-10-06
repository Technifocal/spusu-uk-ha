import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from homeassistant.core import callback

from custom_components.spusu_uk.auth import (
    ImapTokenReceiver,
    TokenTimeout,
    token_from_custom,
)
from custom_components.spusu_uk.const import SENDER, SUBJECT


@pytest.mark.parametrize(
    "value,expected",
    [
        ("opaque-token", "opaque-token"),
        ("abc/123+==", "abc/123+=="),
        ("https://www.spusu.co.uk/login?token=abc%2F123%2B%3D%3D", "abc/123+=="),
        ({"token": "abc"}, "abc"),
        ({"url": "https://www.spusu.co.uk/login?token=abc%3D"}, "abc="),
        ("https://www.spusu.co.uk/login?token=abc&token=def", None),
        ("https://evil.test/login?token=abc", None),
        ("https://www.spusu.co.uk@evil.test/login?token=abc", None),
        ("Email body with a token", None),
        (True, None),
        (None, None),
        ({}, None),
        ("<html>", None),
    ],
)
def test_custom_interface(value, expected):
    assert token_from_custom(value) == expected


def event_data(**changes):
    return {
        "entry_id": "imap-test",
        "sender": SENDER,
        "subject": SUBJECT,
        "initial": True,
        "uid": "42",
        "folder": "INBOX",
        "date": datetime.now(timezone.utc),
        "custom": {"token": "one-time-token"},
        **changes,
    }


async def test_listener_precedes_request_and_is_removed(hass, client):
    @callback
    def request(_):
        hass.bus.async_fire("imap_content", event_data())

    client.request_email.side_effect = request
    receiver = ImapTokenReceiver(hass, "imap-test")
    await receiver.authenticate(client, "account")
    client.login.assert_awaited_once_with("one-time-token")
    assert "imap_content" not in hass.bus.async_listeners()


@pytest.mark.parametrize(
    "changes",
    [
        {"entry_id": "wrong"},
        {"sender": "wrong@example.test"},
        {"subject": "Wrong"},
        {"initial": False},
        {"date": datetime.now(timezone.utc) - timedelta(days=1)},
        {"date": None},
        {"date": "invalid"},
        {"date": datetime.now()},
        {"custom": None},
        {"uid": None},
    ],
)
async def test_invalid_event_ignored(hass, client, changes):
    client.request_email.side_effect = lambda _: hass.bus.async_fire(
        "imap_content", event_data(**changes)
    )
    with patch("custom_components.spusu_uk.auth.AUTH_TIMEOUT", 0.02):
        with pytest.raises(TokenTimeout):
            await ImapTokenReceiver(hass, "imap-test").authenticate(client, "account")
    client.login.assert_not_awaited()
    assert "imap_content" not in hass.bus.async_listeners()


async def test_duplicate_uid_and_cancellation(hass, client):
    receiver = ImapTokenReceiver(hass, "imap-test")
    client.request_email.side_effect = lambda _: hass.bus.async_fire(
        "imap_content", event_data()
    )
    await receiver.authenticate(client, "account")
    with patch("custom_components.spusu_uk.auth.AUTH_TIMEOUT", 0.02):
        with pytest.raises(TokenTimeout):
            await receiver.authenticate(client, "account")
    assert client.login.await_count == 1
    client.request_email.side_effect = None
    task = asyncio.create_task(receiver.authenticate(client, "account"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "imap_content" not in hass.bus.async_listeners()


async def test_failed_email_request_cleans_listener(hass, client):
    from custom_components.spusu_uk.api import ConnectionFailure

    client.request_email.side_effect = ConnectionFailure("offline")
    with pytest.raises(ConnectionFailure):
        await ImapTokenReceiver(hass, "imap-test").authenticate(client, "account")
    assert "imap_content" not in hass.bus.async_listeners()


async def test_same_receiver_serializes_mail_requests(hass, client):
    receiver = ImapTokenReceiver(hass, "imap-test")
    first = asyncio.Event()
    calls = 0

    async def request(_):
        nonlocal calls
        calls += 1
        if calls == 1:
            first.set()
        else:
            hass.bus.async_fire("imap_content", event_data(uid="43"))

    client.request_email.side_effect = request
    one = asyncio.create_task(receiver.authenticate(client, "account-a"))
    await first.wait()
    two = asyncio.create_task(receiver.authenticate(client, "account-b"))
    await asyncio.sleep(0)
    assert calls == 1
    hass.bus.async_fire("imap_content", event_data())
    await asyncio.gather(one, two)
    assert calls == 2
