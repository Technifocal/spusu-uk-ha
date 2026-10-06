import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.spusu_uk.api import ConnectionFailure, SessionExpired
from custom_components.spusu_uk.auth import TokenTimeout
from custom_components.spusu_uk.coordinator import SpusuCoordinator
from custom_components.spusu_uk.models import parse_usage
from custom_components.spusu_uk.sensor import SpusuSensor


def make_coordinator(hass, entry, client, usage):
    receiver = Mock(authenticate=AsyncMock())
    coordinator = SpusuCoordinator(hass, entry, client, receiver)
    coordinator.data = parse_usage(usage)
    metric = coordinator.data[("synthetic-line-a", "nationalData", "remaining")]
    return coordinator, receiver, SpusuSensor(coordinator, entry, metric)


async def test_expiry_preserves_values_only_while_renewing(hass, entry, client, usage):
    coordinator, receiver, sensor = make_coordinator(hass, entry, client, usage)
    waiting, release = asyncio.Event(), asyncio.Event()

    async def renew(*_):
        waiting.set()
        await release.wait()
        client.cookie = "new-cookie"

    receiver.authenticate.side_effect = renew
    client.usage.side_effect = [SessionExpired("expired"), usage]
    task = asyncio.create_task(coordinator.async_refresh())
    await waiting.wait()
    assert coordinator.renewing and sensor.available
    assert sensor.native_value == 37.5
    assert sensor.extra_state_attributes["renewing_session"] is True
    release.set()
    await task
    assert not coordinator.renewing and sensor.available
    assert entry.data["session_cookie"] == "new-cookie"
    receiver.authenticate.assert_awaited_once()
    await coordinator.async_shutdown()


@pytest.mark.parametrize(
    "error", [ConnectionFailure("offline"), ConnectionFailure("HTTP 500")]
)
async def test_outage_unavailable_without_login(hass, entry, client, usage, error):
    coordinator, receiver, sensor = make_coordinator(hass, entry, client, usage)
    client.usage.side_effect = error
    await coordinator.async_refresh()
    assert not sensor.available
    assert not coordinator.renewing
    receiver.authenticate.assert_not_awaited()
    await coordinator.async_shutdown()


async def test_renewal_timeout_unavailable_and_no_email_loop(
    hass, entry, client, usage
):
    coordinator, receiver, sensor = make_coordinator(hass, entry, client, usage)
    entry.async_start_reauth_if_available = Mock()
    client.usage.side_effect = SessionExpired("expired")
    receiver.authenticate.side_effect = TokenTimeout("timeout")
    await coordinator.async_refresh()
    assert not sensor.available and coordinator.auth_failed
    entry.async_start_reauth_if_available.assert_called_once()
    await coordinator.async_refresh()
    receiver.authenticate.assert_awaited_once()
    await coordinator.async_shutdown()


async def test_network_failure_after_renewal_is_outage(hass, entry, client, usage):
    coordinator, receiver, sensor = make_coordinator(hass, entry, client, usage)
    client.usage.side_effect = [SessionExpired("expired"), ConnectionFailure("offline")]
    await coordinator.async_refresh()
    assert not sensor.available and not coordinator.auth_failed
    await coordinator.async_shutdown()


async def test_valid_cookie_never_requests_email(hass, entry, client, usage):
    coordinator, receiver, sensor = make_coordinator(hass, entry, client, usage)
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    receiver.authenticate.assert_not_awaited()
    assert sensor.available
    await coordinator.async_shutdown()


async def test_missing_metric_and_changed_units_unavailable(hass, entry, client, usage):
    coordinator, _, sensor = make_coordinator(hass, entry, client, usage)
    coordinator.data = {}
    assert not sensor.available
    coordinator.data = parse_usage(usage)
    coordinator.last_update_success = False
    assert not sensor.available
    await coordinator.async_shutdown()


async def test_unload_cancels_token_wait_and_removes_listener(
    hass, entry, client, usage
):
    from custom_components.spusu_uk.auth import ImapTokenReceiver

    receiver = ImapTokenReceiver(hass, "imap-test")
    coordinator = SpusuCoordinator(hass, entry, client, receiver)
    coordinator.data = parse_usage(usage)
    client.usage.side_effect = SessionExpired("expired")
    started = asyncio.Event()

    async def email(*_):
        started.set()

    client.request_email.side_effect = email
    task = asyncio.create_task(coordinator.async_refresh())
    await started.wait()
    assert "imap_content" in hass.bus.async_listeners()
    await coordinator.async_shutdown()
    assert "imap_content" not in hass.bus.async_listeners()
    assert not coordinator.renewing
    assert task.done()


async def test_malformed_response_is_unavailable_without_login(
    hass, entry, client, usage
):
    coordinator, receiver, sensor = make_coordinator(hass, entry, client, usage)
    client.usage.return_value = {"usages": []}
    await coordinator.async_refresh()
    assert not sensor.available
    receiver.authenticate.assert_not_awaited()
    await coordinator.async_shutdown()
