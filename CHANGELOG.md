# Changelog

## 0.1.2

- Fix the blank initial setup dialog on Home Assistant 2026.9.4 by giving the IMAP selector an explicit initial value.
- Add a regression test covering the form schema sent to the frontend.

## 0.1.1 — 2026-10-06

- Verified email request, token exchange, and usage against Spusu UK once each.
- Saved sanitized response fixtures and blocked live network access in tests.
- Recognize `productKey` subscription identities and GB/minute/SMS/money unit types.
- Respect current custom spending caps, including zero, and expose next-month/default limits.
- Validate Home Assistant sensor states against the captured usage structure.
