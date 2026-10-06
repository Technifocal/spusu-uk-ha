import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryError

from custom_components.spusu_uk import (
    async_setup_entry,
    async_unload_entry,
    get_receiver,
)
from custom_components.spusu_uk.diagnostics import async_get_config_entry_diagnostics
from custom_components.spusu_uk.sensor import async_setup_entry as setup_sensors


async def test_setup_unload_dynamic_sensors_and_diagnostics(
    hass, entry, imap_entry, client, usage
):
    entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    with (
        patch("custom_components.spusu_uk.SpusuClient", return_value=client),
        patch("custom_components.spusu_uk.async_get_clientsession"),
    ):
        assert await async_setup_entry(hass, entry)
    coordinator = entry.runtime_data
    added = Mock()
    await setup_sensors(hass, entry, added)
    sensors = added.call_args.args[0]
    assert len(sensors) == 9
    assert len({sensor.unique_id for sensor in sensors}) == 9
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert "synthetic-account" not in str(diagnostics)
    assert "old-session" not in str(diagnostics)
    assert diagnostics["metric_count"] == 9
    assert await async_unload_entry(hass, entry)
    await coordinator.async_shutdown()


async def test_missing_imap_fails_before_spusu(hass, entry):
    with pytest.raises(ConfigEntryError):
        await async_setup_entry(hass, entry)


async def test_same_mailbox_uses_shared_receiver(hass):
    assert get_receiver(hass, "mailbox") is get_receiver(hass, "mailbox")
    assert get_receiver(hass, "other") is not get_receiver(hass, "mailbox")


@pytest.mark.parametrize(
    "fixture_name,expected_count,expected_remaining",
    [("synthetic", 9, 37.5), ("live", 36, 1.0)],
)
async def test_real_home_assistant_loader_and_sensor_states(
    hass, entry, imap_entry, client, fixture_name, expected_count, expected_remaining
):
    if fixture_name == "live":
        import json
        from pathlib import Path

        client.usage.return_value = json.loads(
            (Path(__file__).parent / "fixtures/usage_live.json").read_text()
        )
    from homeassistant import loader
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.setup import async_setup_component

    loader.async_setup(hass)
    from homeassistant.helpers import area_registry, device_registry, entity_registry

    device_registry.async_setup(hass)
    await area_registry.async_load(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    integration = await loader.async_get_integration(hass, "spusu_uk")
    assert integration.manifest["config_flow"] is True
    assert not integration.is_built_in
    assert await async_setup_component(hass, "sensor", {})
    entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    with (
        patch("custom_components.spusu_uk.SpusuClient", return_value=client),
        patch("custom_components.spusu_uk.async_get_clientsession"),
    ):
        async with entry.setup_lock:
            assert await async_setup_entry(hass, entry)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    await hass.async_block_till_done()
    states = hass.states.async_all("sensor")
    assert len(states) == expected_count
    remaining = [
        state
        for state in states
        if state.attributes.get("friendly_name", "").endswith("National data remaining")
    ]
    assert len(remaining) == 1 and float(remaining[0].state) == expected_remaining
    from custom_components.spusu_uk.api import ConnectionFailure, SessionExpired

    coordinator = entry.runtime_data
    started, release = asyncio.Event(), asyncio.Event()

    async def renew(*_):
        started.set()
        await release.wait()

    coordinator.receiver.authenticate = AsyncMock(side_effect=renew)
    client.usage.side_effect = [SessionExpired("expired"), client.usage.return_value]
    renewal = asyncio.create_task(coordinator.async_refresh())
    await started.wait()
    actual = hass.states.get(remaining[0].entity_id)
    assert float(actual.state) == expected_remaining
    assert actual.attributes["renewing_session"] is True
    release.set()
    await renewal
    assert (
        hass.states.get(remaining[0].entity_id).attributes["renewing_session"] is False
    )
    client.usage.side_effect = ConnectionFailure("offline")
    await entry.runtime_data.async_refresh()
    assert hass.states.get(remaining[0].entity_id).state == "unavailable"
    assert await async_unload_entry(hass, entry)
    await entry._async_process_on_unload(hass)
    await hass.async_block_till_done()

    assert hass.states.get(remaining[0].entity_id).state == "unavailable"
    assert hass.states.get(remaining[0].entity_id).attributes["restored"] is True
    client.usage.side_effect = None
    entry._async_set_state(hass, ConfigEntryState.SETUP_IN_PROGRESS, None)
    with (
        patch("custom_components.spusu_uk.SpusuClient", return_value=client),
        patch("custom_components.spusu_uk.async_get_clientsession"),
    ):
        async with entry.setup_lock:
            assert await async_setup_entry(hass, entry)
    entry._async_set_state(hass, ConfigEntryState.LOADED, None)
    await hass.async_block_till_done()
    assert float(hass.states.get(remaining[0].entity_id).state) == expected_remaining
    assert await async_unload_entry(hass, entry)
    await entry._async_process_on_unload(hass)
