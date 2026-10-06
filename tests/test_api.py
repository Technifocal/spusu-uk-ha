from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from custom_components.spusu_uk.api import (
    ConnectionFailure,
    InvalidResponse,
    InvalidToken,
    SessionExpired,
    SpusuClient,
)


def response_session(status=200, data=None, cookies=None, headers=None):
    response = Mock(
        status=status, cookies=SimpleCookie(cookies or ""), headers=headers or {}
    )
    response.json = AsyncMock(return_value=data)
    context = AsyncMock()
    context.__aenter__.return_value = response
    session = Mock()
    session.request.return_value = context
    return session, response


async def test_cookie_capture_and_explicit_cookie(usage):
    session, response = response_session(cookies="JSESSIONID=new-session", data=usage)
    client = SpusuClient(session, "old-session")
    await client.login("opaque-token")
    assert client.cookie == "new-session"
    assert await client.usage() == usage
    args, kwargs = session.request.call_args
    assert args == ("GET", "https://www.spusu.co.uk/imoscmsapi/customerarea/usage")
    assert kwargs["cookies"] == {"JSESSIONID": "new-session"}
    assert kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    "status,error",
    [
        (401, SessionExpired),
        (403, SessionExpired),
        (429, ConnectionFailure),
        (500, ConnectionFailure),
    ],
)
async def test_usage_errors(status, error):
    session, _ = response_session(status)
    with pytest.raises(error):
        await SpusuClient(session, "cookie").usage()


@pytest.mark.parametrize(
    "location,expired",
    [
        ("/login", True),
        ("https://www.spusu.co.uk/login?other=1", True),
        ("https://evil.test/login", False),
        ("/other", False),
    ],
)
async def test_login_redirect(location, expired):
    session, _ = response_session(302, headers={"Location": location})
    with pytest.raises(SessionExpired if expired else ConnectionFailure):
        await SpusuClient(session, "cookie").usage()


@pytest.mark.parametrize("status,cookie", [(400, ""), (401, ""), (200, "")])
async def test_invalid_token(status, cookie):
    session, _ = response_session(status, cookies=cookie)
    with pytest.raises(InvalidToken):
        await SpusuClient(session).login("token")


async def test_malformed_and_transport_errors():
    session, response = response_session(data={})
    client = SpusuClient(session, "cookie")
    with pytest.raises(InvalidResponse):
        await client.usage()
    response.json.side_effect = ValueError("private body")
    with pytest.raises(InvalidResponse, match="not JSON"):
        await client.usage()
    session.request.side_effect = aiohttp.ClientError("secret URL token")
    with pytest.raises(ConnectionFailure) as error:
        await client.usage()
    assert "secret" not in str(error.value)


async def test_email_request_not_retried_and_no_cookie():
    session, _ = response_session()
    await SpusuClient(session, "existing-cookie").request_email("account")
    assert session.request.call_count == 1
    assert session.request.call_args.kwargs["json"] == {
        "phoneNumberOrCustomerNumber": "account"
    }
    assert "cookies" not in session.request.call_args.kwargs
