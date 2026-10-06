"""Constants for Spusu UK."""

from datetime import timedelta

DOMAIN = "spusu_uk"
CONF_ACCOUNT = "account"
CONF_IMAP_ENTRY = "imap_entry_id"
CONF_SESSION = "session_cookie"
SENDER = "office@spusu.co.uk"
SUBJECT = "spusu - Login via e-mail address"
BASE_URL = "https://www.spusu.co.uk"
UPDATE_INTERVAL = timedelta(seconds=900)
AUTH_TIMEOUT = 300
REQUEST_TIMEOUT = 30
