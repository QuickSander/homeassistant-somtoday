# Changelog

All notable changes to the SomToday Home Assistant integration are documented
in this file.

## [Unreleased]

### Added

- OAuth2 authentication layer (`auth.py`):
  - Server-side PKCE authorization-code flow mimicking the SomToday
    app/webapp (school session, username/password form steps, code exchange).
  - Legacy `grant_type=password` fallback for SSO-only schools.
  - Proactive token refresh with an `asyncio.Lock`, rotating refresh-token
    support and reactive-safe `async_ensure_valid()`. Refresh reuses the client
    ID and token endpoint of the login method (PKCE vs. password grant).
  - Injectable `aiohttp.ClientSession` so the flow is fully mockable.
  - School discovery via `organisaties.json` (`async_get_schools`).
- Typed models (`models.py`): `SomTodayTokens` (expiry helpers, token-response
  and config-entry parsing) and `School` (with `oidcurls`/SSO detection).
- Exception hierarchy (`exceptions.py`) matching architecture section 5.1.
- Constants (`const.py`) for config keys, defaults, OAuth2 endpoints, client
  IDs and PKCE parameters.
- `manifest.json` with a version key, `strings.json` and English/Dutch
  translations (`translations/en.json`, `translations/nl.json`) for the
  authentication, student, reauth and options steps.
- `requirements_test.txt` with the test dependencies.
- Unit tests for the authentication client and models (100% line and branch
  coverage for that layer). All SomToday HTTP traffic is mocked. See
  `docs/test-report.md`.
- Config flow (`config_flow.py`): school discovery, credential validation,
  student selection, reauth and the options flow (poll interval + feature
  toggles).
- Integration setup (`__init__.py`): builds the auth and API clients, validates
  the stored refresh token on setup (`ConfigEntryAuthFailed`/`ConfigEntryNotReady`
  mapping), persists rotated refresh tokens and exposes `entry.runtime_data`.
  Entity platforms are intentionally empty in this slice.
- Minimal REST API client (`api.py`): injectable session, authenticated requests,
  reactive refresh-and-retry on `401`, error mapping and
  `async_get_students()`.
- `Student` model and `parse_students()` in `models.py` for
  `/rest/v1/leerlingen`.
- Config flow and API client tests (`tests/test_config_flow.py`,
  `tests/test_api.py`), translation parity tests (`tests/test_translations.py`),
  a manifest test (`tests/test_manifest.py`) and a `pytest.ini` with
  `asyncio_mode = auto` for the Home Assistant test plugin (127 tests, 99% line
  coverage; the auth layer stays at 100%). All SomToday HTTP traffic is mocked.
  See `docs/test-report.md`.
- Deployment assets: a `README.md` with manual and HACS install steps,
  configuration, options, privacy notes and troubleshooting, plus `hacs.json`
  metadata for installation as a HACS custom repository.

### Fixed

- School discovery (`async_get_schools`) now maps invalid JSON and error HTTP
  statuses to `SomTodayApiError`/`SomTodayRateLimitError` instead of leaking a
  raw `ValueError` (review B1/F1).
- Token refresh preserves a tenant-specific `api_url`/`tenant` when the refresh
  response omits them, instead of resetting them to defaults (review B2/F2).
- The refresh host and client ID are now restorable across restarts: each login
  records `auth_method`, `as_entry_data()` persists it, and the client
  constructor consumes it (review B3, architecture section 12.2).
- Authorize HTTP errors are no longer misclassified as SSO-only. Only a real
  redirect to an external IdP triggers the password-grant fallback; 4xx and 5xx
  map to `SomTodayAuthError`/`SomTodayApiError` (review B4).
- Aligned token-endpoint status mapping with architecture section 5.1: 5xx to
  `SomTodayApiError`, 429 to `SomTodayRateLimitError` (review N2/N3), and
  reset the cookie jar at the start of each login attempt (review N6).
- Reauth now reloads the config entry via `async_update_reload_and_abort`, so an
  entry stuck in `SETUP_ERROR` recovers to `LOADED` instead of staying broken
  (review B1).
- The API client releases the rejected first response before the reactive `401`
  refresh-and-retry (review B2), and the auth client releases every response
  (authorize, login-session, form and token) on both success and error paths
  (review B2/N5).
