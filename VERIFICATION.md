# Verification

Checked on 2026-10-06 against Home Assistant Core 2026.9.4 and Python 3.14.
Integration version: **0.1.1**.

## Actual Spusu API calls

Each of these requests was made **once**, with no retries:

| Request | Actual result |
| --- | --- |
| POST `/imoscmsapi/authentication/onetimelink/email` | HTTP 200, empty response body |
| POST `/imoscmsapi/authentication/login/token/` | HTTP 200, `JSESSIONID` cookie returned |
| GET `/imoscmsapi/customerarea/usage` | HTTP 200, JSON with 1 subscription and 12 balance categories |

The integration's actual REST client performed these calls. Its initial usage
parser successfully produced 36 numeric metric definitions from the real response.
The live snapshot confirmed `productKey` subscription identifiers, `unitType`
metadata, boolean unlimited allowances with no numeric value, and custom current-
and next-month spending limits. The implementation now handles those fields.
National data and EU roaming data both had allowance 1 and usage 0 in this snapshot.

## Saved fixtures and future tests

The response metadata and sanitized bodies are saved in `tests/fixtures/` and used
by `test_live_fixtures.py` and the actual Home Assistant sensor-runtime test.
Personal identifiers, billing dates, token and cookie values are redacted.
Allowance, usage, and spending-limit numbers are preserved.

The initial sanitizer also redacted public `unitType` and currency strings. The
original HTTP envelope is preserved unchanged in `live_usage_response.json`;
`usage_live.json` restores the enum labels using the vendor's public JavaScript
and UK currency documentation. `live_provenance.json` records these sources and
this transformation. The restored labels are public metadata, not a second live
account capture. No additional authenticated requests were made to correct this.

The test suite blocks actual aiohttp requests. Routine tests must use saved
fixtures instead of requesting new emails or contacting the live Spusu account.

## Offline checks

- Automated tests: **81 passed**.
- Recorded response replay, category coverage, public unit enum mapping, custom
  spending caps including zero, unlimited allowances, and stable product identifiers: passed.
- Actual Home Assistant sensor loading with both synthetic and live-derived fixtures,
  registry identifiers, renewal states, outage availability, unload, and reload: passed.
- Ruff lint and formatting checks: passed.
- Official `script.hassfest` validator at Home Assistant tag `2026.9.4`:
  **1 integration, 0 invalid integrations**.
- One test warning comes from Home Assistant's own deprecated HTTP application
  inheritance; no integration test failures.

## Limits of live verification

The user supplied the token directly. The user's IMAP installation was not accessed
or changed, and the complete automatic IMAP delivery path has not been exercised
live. Expired/invalid sessions, renewal, outages, and multiple subscriptions remain
mocked test scenarios rather than additional real account requests.

## Setup dialog compatibility fix (0.1.2)

On Home Assistant Core 2026.9.4, the initial setup dialog was reproduced as blank.
The browser reported `Selector config_entry not supported in initial form data`.
The IMAP selector now supplies an explicit empty default, so the frontend does
not try to infer an unsupported initial value. Reauthentication already supplies
a default. No additional Spusu API calls were made during this investigation.

The exact `computeInitialHaFormData` and selector initializer from frontend tag
20260826.7 were executed locally: the original schema throws the reported error,
and the corrected schema initializes both account and IMAP fields successfully.
A regression test checks the serialized form schema, including the empty default.
The corrected dialog still needs confirmation after installation on the user's
Home Assistant instance; local initializer validation is not a full browser test.
