import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp import DummyCookieJar
from homeassistant.data_entry_flow import AbortFlow, FlowResultType
from homeassistant.helpers import config_validation as cv
from probatio import to_field_list

from custom_components.spusu_uk.api import (
    ConnectionFailure,
    InvalidResponse,
    InvalidToken,
)
from custom_components.spusu_uk.auth import TokenTimeout
from custom_components.spusu_uk.config_flow import SpusuConfigFlow


def flow_for(hass):
    flow = SpusuConfigFlow()
    flow.hass = hass
    flow.flow_id = "test-flow"
    flow.handler = "spusu_uk"
    flow.context = {"source": "user"}
    return flow


async def test_user_form_and_validation(hass, imap_entry):
    flow = flow_for(hass)
    result = await flow.async_step_user()
    assert result["type"] == FlowResultType.FORM
    assert result["data_schema"]({"account": "test", "imap_entry_id": "imap-test"})
    result = await flow.async_step_user(
        {"account": "bad account", "imap_entry_id": "imap-test"}
    )
    assert result["errors"] == {"account": "invalid_account"}
    result = await flow.async_step_user({"account": "test", "imap_entry_id": "missing"})
    assert result["errors"] == {"imap_entry_id": "invalid_imap"}


async def test_duplicate_account_stops_before_email(hass, entry, imap_entry):
    flow = flow_for(hass)
    with pytest.raises(AbortFlow, match="already_configured"):
        await flow.async_step_user(
            {"account": "synthetic-account", "imap_entry_id": "imap-test"}
        )


async def test_initial_auth_progress_and_create_entry(hass, imap_entry, client):
    flow = flow_for(hass)

    async def deliver(*_):
        await asyncio.sleep(0)

    receiver = Mock(authenticate=AsyncMock(side_effect=deliver))
    client.cookie = "validated-session"
    with (
        patch(
            "custom_components.spusu_uk.config_flow.SpusuClient", return_value=client
        ),
        patch("custom_components.spusu_uk.config_flow.async_create_clientsession"),
        patch(
            "custom_components.spusu_uk.config_flow.get_receiver", return_value=receiver
        ),
    ):
        result = await flow.async_step_user(
            {"account": "test", "imap_entry_id": "imap-test"}
        )
        assert result["type"] == FlowResultType.SHOW_PROGRESS
        await flow._task
        result = await flow.async_step_authenticate()
        assert result["step_id"] == "finish"
        result = await flow.async_step_finish()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["session_cookie"] == "validated-session"
    receiver.authenticate.assert_awaited_once()
    client.usage.assert_awaited_once()


@pytest.mark.parametrize(
    "error,message",
    [
        (TokenTimeout("timeout"), "token_timeout"),
        (InvalidToken("invalid"), "invalid_token"),
        (InvalidResponse("bad"), "invalid_response"),
        (ConnectionFailure("offline"), "cannot_connect"),
    ],
)
async def test_flow_failures_without_automatic_retry(
    hass, imap_entry, client, error, message
):
    flow = flow_for(hass)
    receiver = Mock(authenticate=AsyncMock(side_effect=error))
    with (
        patch(
            "custom_components.spusu_uk.config_flow.SpusuClient", return_value=client
        ),
        patch("custom_components.spusu_uk.config_flow.async_create_clientsession"),
        patch(
            "custom_components.spusu_uk.config_flow.get_receiver", return_value=receiver
        ),
    ):
        await flow.async_step_user({"account": "test", "imap_entry_id": "imap-test"})
        await flow._task
        assert (await flow.async_step_authenticate())["step_id"] == "retry"
        result = await flow.async_step_retry()
        assert result["errors"] == {"base": message}
    receiver.authenticate.assert_awaited_once()


async def test_reauth_updates_existing_entry(hass, entry, imap_entry):
    flow = flow_for(hass)
    flow.context = {"source": "reauth", "entry_id": entry.entry_id}
    result = await flow.async_step_reauth(dict(entry.data))
    assert result["step_id"] == "reauth_confirm"
    flow._data["session_cookie"] = "renewed-session"
    with patch.object(
        flow,
        "async_update_reload_and_abort",
        return_value={"type": FlowResultType.ABORT, "reason": "reauth_successful"},
    ) as update:
        result = await flow.async_step_finish()
    assert result["reason"] == "reauth_successful"
    update.assert_called_once_with(entry, data_updates=flow._data)


async def test_user_form_serialized_initial_imap_value(hass):
    """HA's frontend needs a default for an unsupported selector initializer."""
    result = await flow_for(hass).async_step_user()
    fields = to_field_list(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    account, imap = fields
    assert account["name"] == "account"
    assert account["type"] == "string"
    assert imap["name"] == "imap_entry_id"
    assert imap["required"] is True
    assert imap["selector"] == {"config_entry": {"integration": "imap"}}
    # computeInitialHaFormData uses this before its selector initializer, which
    # throws for config_entry in frontend 20260826.7 (HA Core 2026.9.4).
    assert "default" in imap
    assert imap["default"] == ""


@pytest.mark.parametrize(
    "error", [None, InvalidToken("HTTP 401"), asyncio.CancelledError()]
)
async def test_flow_cookie_isolation_and_cleanup(hass, client, error):
    flow = flow_for(hass)
    flow._data = {"account": "test", "imap_entry_id": "imap-test"}
    receiver = Mock(authenticate=AsyncMock(side_effect=error))
    with (
        patch(
            "custom_components.spusu_uk.config_flow.SpusuClient", return_value=client
        ),
        patch(
            "custom_components.spusu_uk.config_flow.async_create_clientsession"
        ) as create,
        patch(
            "custom_components.spusu_uk.config_flow.get_receiver", return_value=receiver
        ),
    ):
        if isinstance(error, asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await flow._authenticate()
        else:
            await flow._authenticate()
    jar = create.call_args.kwargs["cookie_jar"]
    assert isinstance(jar, DummyCookieJar)
    jar.update_cookies({"JSESSIONID": "foreign-account-session"})
    assert len(jar) == 0
    assert create.call_args.kwargs["auto_cleanup"] is False
    client.session.detach.assert_called_once()
