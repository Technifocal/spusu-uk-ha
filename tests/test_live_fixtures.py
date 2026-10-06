"""Offline regressions from the one real Spusu API capture.

These tests never send a network request. Unit labels in usage_live.json were
restored from the public vendor unit enum; see live_provenance.json.
"""

import copy
import json
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.spusu_uk.api import InvalidResponse, SpusuClient
from custom_components.spusu_uk.coordinator import SpusuCoordinator
from custom_components.spusu_uk.models import parse_usage
from custom_components.spusu_uk.sensor import SpusuSensor

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def live_usage():
    return load("usage_live.json")


def replay_response(record, body=None):
    cookies = SimpleCookie()
    for name, metadata in record.get("cookies", {}).items():
        cookies[name] = "fixture-session" if name == "JSESSIONID" else "fixture-route"
        cookies[name]["path"] = metadata["path"]
        cookies[name]["secure"] = metadata["secure"]
        cookies[name]["httponly"] = metadata["httponly"]
    response = Mock(
        status=record["status"],
        cookies=cookies,
        headers={"Content-Type": record.get("content_type", "")},
    )
    response.json = AsyncMock(return_value=body if body is not None else record["body"])
    context = AsyncMock()
    context.__aenter__.return_value = response
    return context


async def test_replay_actual_email_login_and_usage(live_usage):
    session = Mock()
    session.request.side_effect = [
        replay_response(load("live_request_email.json")),
        replay_response(load("live_login.json")),
        replay_response(load("live_usage_response.json"), live_usage),
    ]
    client = SpusuClient(session)
    await client.request_email("fixture-account")
    await client.login("fixture-token")
    metrics = parse_usage(await client.usage())
    assert client.cookie == "fixture-session"
    assert len(metrics) == 36
    assert session.request.call_count == 3
    assert session.request.call_args.kwargs["cookies"] == {
        "JSESSIONID": "fixture-session"
    }
    assert all(
        record["status"] == 200
        for record in (
            load("live_request_email.json"),
            load("live_login.json"),
            load("live_usage_response.json"),
        )
    )


def test_all_real_categories_and_units(live_usage):
    metrics = parse_usage(live_usage)
    key = live_usage["usages"][0]["productKey"]
    assert len({metric.category for metric in metrics.values()}) == 12
    assert metrics[(key, "nationalData", "allowance")].value == 1
    assert metrics[(key, "nationalData", "remaining")].value == 1
    assert metrics[(key, "euRoamingData", "remaining")].unit == "GB"
    assert metrics[(key, "euRoamingVoice", "allowance")].value == 500
    assert metrics[(key, "euRoamingVoice", "usage")].unit == "min"
    assert metrics[(key, "euRoamingSMS", "usage")].unit == "SMS"
    assert metrics[(key, "euInternationalVoice", "remaining")].value == 500
    assert metrics[(key, "nationalVoice", "usage")].unlimited
    assert metrics[(key, "nationalVoice", "allowance")].value is None
    assert metrics[(key, "nationalSMS", "usage")].value == 0
    assert metrics[(key, "nationalSMS", "remaining")].value is None
    assert metrics[(key, "costLimitNationalData", "allowance")].unit == "GBP"


def test_current_spending_caps_override_default_including_zero(live_usage):
    metrics = parse_usage(live_usage)
    key = live_usage["usages"][0]["productKey"]
    capped = metrics[(key, "costLimitNationalVoiceAndSMS", "remaining")]
    assert capped.value == 1
    assert capped.default_allowance == 10
    assert capped.next_month_allowance == 1
    assert capped.maximum_limit == 100
    assert metrics[(key, "costLimitRoamingData", "remaining")].value == 0


def test_product_keys_stable_across_multiple_subscriptions(live_usage):
    other = copy.deepcopy(live_usage["usages"][0])
    other["productKey"] = "another-fixture-product"
    live_usage["usages"].append(other)
    expected = parse_usage(live_usage)
    live_usage["usages"].reverse()
    assert parse_usage(live_usage) == expected
    assert len(expected) == 72


def test_public_unit_enum_and_fixture_provenance(live_usage):
    provenance = load("live_provenance.json")
    assert provenance["live_api_requests"] == {"email": 1, "login_token": 1, "usage": 1}
    assert {
        raw["balance"]["unitType"]
        for raw in live_usage["usages"][0]["balances"].values()
    } == set(provenance["public_unit_enum"].values())
    assert load("live_login.json")["cookies"]["JSESSIONID"]["value"] == "[REDACTED]"


async def test_real_balance_sensor_device_classes(hass, entry, live_usage):
    client = Mock()
    coordinator = SpusuCoordinator(hass, entry, client, Mock())
    coordinator.data = parse_usage(live_usage)
    key = live_usage["usages"][0]["productKey"]
    for category, device_class in (
        ("nationalData", SensorDeviceClass.DATA_SIZE),
        ("euRoamingVoice", SensorDeviceClass.DURATION),
        ("costLimitNationalVoiceAndSMS", SensorDeviceClass.MONETARY),
    ):
        metric = coordinator.data[(key, category, "remaining")]
        sensor = SpusuSensor(coordinator, entry, metric)
        assert sensor.device_class == device_class
        assert sensor.available
        if metric.unit == "GBP":
            assert sensor.state_class is None
            assert sensor.extra_state_attributes["next_month_allowance"] == 1
    await coordinator.async_shutdown()


def test_malformed_unit_type_rejected(live_usage):
    live_usage["usages"][0]["balances"]["nationalData"]["balance"]["unitType"] = {}
    with pytest.raises(InvalidResponse, match="unit type"):
        parse_usage(live_usage)
