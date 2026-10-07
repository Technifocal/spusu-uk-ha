"""Spusu REST requests. This module never connects to an email server."""

from typing import Any
from urllib.parse import urljoin, urlsplit

import aiohttp

from .const import BASE_URL, REQUEST_TIMEOUT


class SpusuError(Exception):
    """A sanitized upstream error."""


class SessionExpired(SpusuError):
    """The upstream explicitly rejected the session."""


class InvalidToken(SpusuError):
    """The supplied token was rejected."""


class ConnectionFailure(SpusuError):
    """A network or server failure."""


class InvalidResponse(SpusuError):
    """The upstream response does not match the expected format."""


class SpusuClient:
    """Use explicit cookies with a dedicated session and a disabled cookie jar."""

    def __init__(
        self, session: aiohttp.ClientSession, cookie: str | None = None
    ) -> None:
        self.session = session
        self.cookie = cookie

    async def request_email(self, account: str) -> None:
        await self._request(
            "POST",
            "/imoscmsapi/authentication/onetimelink/email",
            payload={"phoneNumberOrCustomerNumber": account},
        )

    async def login(self, token: str) -> None:
        cookie = await self._request(
            "POST",
            "/imoscmsapi/authentication/login/token/",
            payload={"token": token},
            login=True,
        )
        if not cookie:
            raise InvalidToken("Login did not return a session")
        self.cookie = cookie

    async def usage(self) -> dict[str, Any]:
        if not self.cookie:
            raise SessionExpired("No session")
        return await self._request(
            "GET",
            "/imoscmsapi/customerarea/usage",
            authenticated=True,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        login: bool = False,
        authenticated: bool = False,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "allow_redirects": False,
            "timeout": aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        }
        if payload is not None:
            kwargs["json"] = payload
        if authenticated:
            kwargs["cookies"] = {"JSESSIONID": self.cookie}
        try:
            async with self.session.request(
                method, BASE_URL + path, **kwargs
            ) as response:
                if authenticated and response.status in (401, 403):
                    raise SessionExpired("Session rejected")
                if authenticated and response.status in (301, 302, 303, 307, 308):
                    location = urlsplit(
                        urljoin(BASE_URL, response.headers.get("Location", ""))
                    )
                    if (
                        location.hostname == "www.spusu.co.uk"
                        and location.path.rstrip("/") == "/login"
                    ):
                        raise SessionExpired("Redirected to login")
                if login and response.status in (400, 401, 403):
                    raise InvalidToken(
                        f"Token exchange returned HTTP {response.status}"
                    )
                if not 200 <= response.status < 300:
                    raise ConnectionFailure(f"Spusu HTTP {response.status}")
                if login:
                    cookie = response.cookies.get("JSESSIONID")
                    return cookie.value if cookie else None
                if not authenticated:
                    return None
                try:
                    data = await response.json()
                except (ValueError, aiohttp.ContentTypeError):
                    raise InvalidResponse("Usage was not JSON") from None
                if not isinstance(data, dict) or not isinstance(
                    data.get("usages"), list
                ):
                    raise InvalidResponse("Missing usage list")
                cookie = response.cookies.get("JSESSIONID")
                if cookie and cookie.value:
                    self.cookie = cookie.value
                return data
        except (aiohttp.ClientError, TimeoutError):
            # Do not propagate URLs, payloads, cookies, or upstream response bodies.
            raise ConnectionFailure("Unable to contact Spusu") from None
