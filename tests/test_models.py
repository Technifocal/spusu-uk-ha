import copy

import pytest

from custom_components.spusu_uk.api import InvalidResponse
from custom_components.spusu_uk.models import parse_usage


def test_values_units_and_unlimited(usage):
    metrics = parse_usage(usage)
    assert metrics[("synthetic-line-a", "nationalData", "remaining")].value == 37.5
    assert metrics[("synthetic-line-a", "nationalData", "allowance")].unit == "GB"
    assert metrics[("synthetic-line-a", "nationalCalls", "usage")].unit == "min"
    assert metrics[("synthetic-line-a", "nationalSms", "remaining")].value is None
    assert metrics[("synthetic-line-a", "nationalSms", "usage")].unlimited
    assert metrics[("synthetic-line-a", "nationalSms", "usage")].value == 4


def test_multiline_reordering_is_stable(usage):
    other = copy.deepcopy(usage["usages"][0])
    other["subscriptionId"] = "synthetic-line-b"
    usage["usages"].append(other)
    before = parse_usage(usage)
    usage["usages"].reverse()
    assert parse_usage(usage) == before


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"usages": []},
        {"usages": [None]},
        {"usages": [{"balances": {}}]},
        {"usages": [{"balances": {}}, {"balances": {}}]},
    ],
)
def test_invalid_response(data):
    with pytest.raises(InvalidResponse):
        parse_usage(data)


def test_missing_values_do_not_fabricate_zero(usage):
    raw = usage["usages"][0]["balances"]["nationalData"]
    del raw["usage"]
    metrics = parse_usage(usage)
    assert metrics[("synthetic-line-a", "nationalData", "usage")].value is None
    assert metrics[("synthetic-line-a", "nationalData", "remaining")].value is None


def test_no_unit_guess_for_other_categories(usage):
    del usage["usages"][0]["balances"]["nationalCalls"]["balance"]["unit"]
    assert (
        parse_usage(usage)[("synthetic-line-a", "nationalCalls", "usage")].unit is None
    )


def test_duplicate_subscription_rejected(usage):
    usage["usages"].append(copy.deepcopy(usage["usages"][0]))
    with pytest.raises(InvalidResponse, match="Duplicate"):
        parse_usage(usage)
