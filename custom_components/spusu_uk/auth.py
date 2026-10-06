"""Receive preprocessed tokens from Home Assistant IMAP events."""

import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from homeassistant.core import Event, HomeAssistant, callback

from .api import SpusuClient, SpusuError
from .const import AUTH_TIMEOUT, SENDER, SUBJECT


class TokenTimeout(SpusuError):
    """IMAP did not deliver a valid token before the deadline."""


def token_from_custom(value: object) -> str | None:
    """Accept a token or a standalone Spusu URL, never an email body."""
    if isinstance(value, dict):
        value = value.get("token") or value.get("url")
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 4096 or any(char.isspace() for char in value):
        return None
    if "://" in value:
        try:
            url = urlsplit(value)
            if (
                url.scheme != "https"
                or url.netloc != "www.spusu.co.uk"
                or url.path != "/login"
                or url.fragment
            ):
                return None
            tokens = parse_qs(url.query).get("token", [])
            if len(tokens) != 1:
                return None
            value = tokens[0]
        except ValueError:
            return None
    if any(c in value for c in "<>\"'") or any(c.isspace() for c in value):
        return None
    return value or None


class ImapTokenReceiver:
    """Only listen while a login attempt is pending."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._seen: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def authenticate(self, client: SpusuClient, account: str) -> None:
        async with self._lock:
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            started = datetime.now(timezone.utc).replace(microsecond=0)

            @callback
            def receive(event: Event) -> None:
                data = event.data
                if future.done() or event.time_fired < started:
                    return
                if (
                    data.get("entry_id") != self.entry_id
                    or str(data.get("sender", "")).lower() != SENDER
                    or data.get("subject") != SUBJECT
                    or data.get("initial") is not True
                ):
                    return
                uid = data.get("uid")
                date = data.get("date")
                if isinstance(date, str):
                    try:
                        date = datetime.fromisoformat(date)
                    except ValueError:
                        return
                if (
                    not isinstance(date, datetime)
                    or date.tzinfo is None
                    or date < started
                ):
                    return
                if uid is None:
                    return
                key = (str(data.get("folder", "")), str(uid))
                if key in self._seen:
                    return
                token = token_from_custom(data.get("custom"))
                if token:
                    self._seen.add(key)
                    future.set_result(token)

            unsubscribe = self.hass.bus.async_listen("imap_content", receive)
            try:
                async with asyncio.timeout(AUTH_TIMEOUT):
                    await client.request_email(account)
                    token = await future
                    await client.login(token)
            except TimeoutError:
                raise TokenTimeout(
                    "No fresh IMAP token received within five minutes"
                ) from None
            finally:
                unsubscribe()
                if not future.done():
                    future.cancel()
