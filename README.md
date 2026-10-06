# Spusu UK for Home Assistant

A custom integration using Spusu UK's email-link authentication and usage API.
It requests login emails only at initial setup or after Spusu explicitly rejects
an existing session. Home Assistant's built-in IMAP integration supplies the token.
There is no mailbox client, email-body parser, email-fetch action, or webhook here.

## Install with HACS

Push this project to the **public** GitHub repository
[`Technifocal/spusu-uk-ha`](https://github.com/Technifocal/spusu-uk-ha). HACS does not support
private repositories; see its [private repository FAQ](https://hacs.dev/docs/faq/private_repositories/).

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Enter `https://github.com/Technifocal/spusu-uk-ha` and choose category **Integration**.
3. Add it, find **Spusu UK**, and download it.
4. Restart Home Assistant.
5. Prepare your existing IMAP integration as described below, then go to
   **Settings → Devices & services → Add integration → Spusu UK**.
6. Enter your phone/customer number and select your IMAP entry. Leave the progress
   dialog open while the login email arrives.

HACS installs and updates the integration files. You must still configure IMAP's
custom event data to deliver the token. With no GitHub release, HACS downloads the
repository's default branch. The repository uses the standard
`custom_components/spusu_uk` layout; do not move its files to the repository root.

## Manual installation

1. Copy `custom_components/spusu_uk` to your Home Assistant configuration directory,
   alongside any other integrations in `custom_components`.
2. Restart Home Assistant.
3. Prepare the existing IMAP integration's custom event data as described below.
4. Go to **Settings → Devices & services → Add integration → Spusu UK**.
5. Enter your international phone number or customer number and select the IMAP entry.
   Submitting sends one login email. Leave the progress dialog open while IMAP delivers
   the token; authentication has a five-minute timeout.

Tested against Home Assistant Core **2026.9.4**, using Python **3.14**.
No additional runtime packages are installed by this integration.

## IMAP token handoff

Use an existing, working Home Assistant IMAP entry monitoring the mailbox that
receives the Spusu login emails. Its search must include:

- Sender: `office@spusu.co.uk`
- Subject: `spusu - Login via e-mail address`

In the built-in IMAP entry's options, configure its **Custom event data template**
to return the login token or the standalone login URL. Token extraction belongs
in your existing Home Assistant IMAP configuration, outside this integration.
This project does not implement or ship an email extractor.

The `custom` field accepts any one of these shapes:

```json
"opaque-token"
```

```json
{"token": "opaque-token"}
```

```json
{"url": "https://www.spusu.co.uk/login?token=opaque-token"}
```

The full URL must use exactly `https://www.spusu.co.uk/login`, with a single `token`
query argument. An email body, HTML, or a link to another host is not accepted.
There is no need to enable the IMAP email `text` or `headers` event fields.
The IMAP custom template can process the full message without the text event's
2,048-byte truncation.

The receiver also checks `entry_id`, sender, subject, `initial`, message UID,
and the email's timestamp. Old messages and duplicate UIDs are ignored. A message
without a timezone-aware timestamp cannot complete authentication. Requests using
the same IMAP entry are serialized so two accounts cannot race for a token.

See the [built-in IMAP documentation](https://www.home-assistant.io/integrations/imap/#using-events)
for configuring the custom event template. Avoid enabling IMAP debug logging while
tokens are being delivered: IMAP's own debug logs may include custom event data.
Spusu's diagnostics and logs never include tokens, cookies, or message content.

## Authentication and polling

The integration sends the account identifier to:

- `POST /imoscmsapi/authentication/onetimelink/email`
- `POST /imoscmsapi/authentication/login/token/` with the IMAP-supplied token
- `GET /imoscmsapi/customerarea/usage` with `JSESSIONID`

Usage is polled every **900 seconds** through one shared coordinator per account.
The session is stored in Home Assistant's configuration entry and verified on
restart. Configuration-entry storage is Home Assistant's normal `.storage` storage,
not an encrypted credential vault; protect configuration backups accordingly.
The emailed token is not persisted.

An HTTP 401/403 or a redirect to Spusu's own login page triggers renewal. Timeouts,
connection errors, rate limits, server errors, and malformed JSON do not trigger
login emails. There is no speculative login on a timer.

During automatic renewal, previously available numeric sensor readings remain
visible, with `renewing_session: true`. On successful renewal the next usage response
updates them. Ordinary outages make the sensors unavailable; they do not expose
cached values as current readings. If a previous outage already made a sensor
unavailable, starting renewal does not make its stale reading available again.

Failed renewal stops automatic login attempts and invokes Home Assistant's
reauthentication flow. Submitting that flow explicitly requests one new login
email. Initial setup creates no sensors until valid usage has been obtained.
Unloading an entry cancels an in-flight token wait and removes its listener.

## Sensors

Each subscription's supported balance categories get allowance, usage, and remaining
sensors, with `remaining = allowance - usage`. The national data category uses GB
as specified in the supplied connection example. The live response's `unitType` enum is supported:
`GB` → GB, `MINUTE` → min, `SMS` → SMS, and `MONEY` → GBP for this UK integration.
Explicit unit/currency metadata takes precedence. Unknown units are not guessed.
The enum is defined in [Spusu's public client](https://www.spusu.co.uk/imoscmsV2542962/assets/store.DXBAsRVT.js).

Sensors have distinct identifiers for the subscription, balance category, and
metric. New supported categories discovered in later responses add sensors.
Missing values or categories become unavailable instead of being converted to zero.
Explicit unlimited balances (`unlimited: true` or `value: "unlimited"`) expose the
numeric usage with `unlimited: true`; allowance and remaining have no fabricated
numeric value and are unavailable. Negative values are not silently interpreted
as unlimited, since that encoding has not been verified.

Supported response shape:

```text
usages[]
  productKey                        (observed subscription identifier)
  subscriptionId / id / phoneNumber  (supported alternate identifiers)
  balances.<category>.balance.value
  balances.<category>.balance.unitType
  balances.<category>.balance.unit    (optional explicit unit override)
  balances.<category>.customLimitCurrentMonth / customLimitNextMonth
  balances.<category>.usage
```

For spending-cap categories, a supplied `customLimitCurrentMonth` takes precedence
over the tariff's default `balance.value`, including an explicit zero cap. Sensors
also expose `default_allowance`, `next_month_allowance`, and `maximum_limit` attributes.
Monetary cap snapshots have no statistics state class, to avoid treating them as
accumulating totals. No spending-limit modification actions are implemented.

A single unnamed subscription is assigned a stable account-local `primary` identity.
Multiple subscriptions without identifiers are rejected rather than using list
positions that might swap sensor identities. Unsupported structures are reported
as unavailable without starting another login.

## Development and verification status

Install `requirements-test.txt` into a Python 3.14 virtual environment and run
`python -m pytest` from this directory. Tests use real Home Assistant classes with
mocked API calls and cover authentication, config flows, polling, availability,
subscription identities, diagnostics, and unloading.

**Live Spusu authentication and usage were verified on 2026-10-06.** The email
request, token exchange, and usage fetch each ran exactly once and returned HTTP 200.
The live usage response contains 12 categories: national data/voice/SMS, EU roaming
data/voice/SMS, EU international voice, and five spending-cap categories.

The captured responses are saved under `tests/fixtures/`:

- `live_request_email.json`: actual email-request result.
- `live_login.json`: actual login result, with cookie values redacted.
- `live_usage_response.json`: original sanitized usage HTTP envelope.
- `usage_live.json`: replay fixture retaining actual allowance/usage values and
  anonymized identifiers. Its unit labels were restored from the vendor's public
  enum after the first sanitizer over-redacted that public metadata.
- `live_provenance.json`: capture provenance, redaction details, and unit sources.
- `usage_synthetic.json`: supplementary artificial edge-case data, not a live response.

The **80 tests** replay these recorded results or mock edge cases. Live HTTP requests
are blocked by an automatic test fixture. Do not reauthenticate or fetch another
live response for routine development. Account numbers, tokens, session cookies,
and email content are not included in the saved fixtures.

The live check used a token supplied by the user. Delivery through the user's
Home Assistant IMAP installation, real session expiration, and other subscriptions
have not been exercised live; their handling is covered by automated mocked tests.
See `VERIFICATION.md` for the precise boundary between live and offline verification.
