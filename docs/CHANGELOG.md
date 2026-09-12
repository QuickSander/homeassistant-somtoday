# Changelog

All notable changes to the SomToday Home Assistant integration are documented
in this file.

## [0.4.0] - 2026-09-12

### Changed

- **Identity model is now one config entry per `(account, student)` (Model A).**
  The unique id is the composite `f"{account_id}:{student_id}"`
  (`const.unique_id_for`), so a parent/guardian account can be added once per
  child while the same student still cannot be added twice (architecture §1.1).
  The old unique id was `account_id`, which allowed only one entry per account.
- `config_flow.py`:
  - `VERSION` bumped to `2`.
  - `_async_identify` now returns the **full** parsed student list and only sets
    `tokens.account_id`; it no longer picks `students[0]` or binds the student.
    `GET /rest/v1/account/me` is now **required**: a failure is retryable
    (`cannot_connect`) instead of falling back to a student id, which keeps the
    composite id stable (no duplicate entries, no false `wrong_account`).
  - `async_step_user` computes the unconfigured students (composite unique id not
    in `_async_current_ids()`) and: shows `no_students` when the list is empty
    (with a fresh PKCE pair), aborts `already_configured` when none remain,
    auto-selects when exactly one remains, and otherwise shows the new
    `async_step_student` dropdown (`SelectSelector`, sorted by display name then
    id).
  - New `_async_finish(student)` binds `student_id`/`student_name`, sets the
    composite unique id and creates the entry; it is shared by the auto-select
    and student-step paths.
  - Reauth now compares `account_id` to `entry.data[account_id]` (not the unique
    id) and aborts `student_removed` when the stored student is no longer in
    `/rest/v1/leerlingen`; `wrong_account` is unchanged. The
    `_new_authorization()`-on-spent-code behaviour is preserved.
  - `async_migrate_entry` recomputes the composite unique id for v1 entries
    (falling back to the old `account_id` when `student_id` is missing) and bumps
    the entry to version 2. `__init__.py` re-exports the hook so Home Assistant
    can find it.
- `const.py`: added the transient `CONF_STUDENT_SELECT` flow key and the pure
  `unique_id_for(account_id, student_id)` helper (no Home Assistant imports).
- `strings.json`/`translations`: added the `student` step
  (`student_select` label) and the `student_removed` abort, and clarified
  `already_configured` ("this student is already configured for this account").
  English, Dutch and `strings.json` expose identical key sets.
- `manifest.json` bumped to `0.4.0`.

### Added

- Tests for the pure `unique_id_for` helper (`tests/test_const.py`) and for the
  new flow behaviour: multiple students show the student step, choosing creates
  the right entry, a second student of the same account succeeds with a distinct
  unique id, duplicate `(account, student)` aborts, reauth `wrong_account` and
  `student_removed`, and v1 → v2 migration (including the no-student fallback).
  Total: 159 tests, 99% line coverage (`config_flow.py` 100%), all SomToday HTTP
  mocked.

### Fixed

- A transient `GET /rest/v1/account/me` failure during setup or reauth is now
  retryable (`cannot_connect`) instead of computing a student-based unique id.
  Previously it could abort reauth with a false `wrong_account` or create a
  duplicate entry for a student that was already configured.

## [0.3.0] - 2026-09-11

### Changed

- **Authentication rewritten to the browser-based authorization-code + PKCE
  flow** (`auth.py`), matching the MIT-licensed `jonisnet/ha-somtoday`
  integration. SomToday removed the school-list endpoint
  (`servers.somtoday.nl/organisaties.json`) in February 2025 and disabled the
  password grant; server-side form scraping is fragile and breaks at SSO/MFA
  schools. The new flow:
  - Home Assistant shows a SomToday authorize URL **without `tenant_uuid`**, so
    SomToday presents its own school picker.
  - The user logs in through their own browser (SSO/MFA work) and pastes the
    failed `somtoday://` redirect (or the DevTools `Location:` header, or a bare
    code) back into the config flow.
  - HA exchanges the code server-side at
    `https://inloggen.somtoday.nl/oauth2/token` using the public
    `somtoday-leerling-native` client and PKCE `S256`.
  - `extract_code()` is forgiving and raises `login_page` / `sso_callback` /
    `state_mismatch` / `no_code` reasons; only HTTP 400 + `error=invalid_grant`
    is a definitive rejection (`SomtodayInvalidAuth`), everything else stays
    retryable.
  - Rotating refresh tokens are preserved (and re-persisted) across refreshes;
    a refresh that omits `somtoday_api_url` keeps the previous value.
- Removed the server-side login code: `SomTodayAuthClient`, `async_get_schools`,
  the PKCE form-scraping steps, the password-grant fallback and the
  school/credential config-flow steps.
- `SomTodayApiClient.async_get_account()` reads `/rest/v1/account/me`; the
  config flow uses it as the unique id (falling back to
  `/rest/v1/leerlingen`). Error responses now log a bounded
  status/body/redirect diagnostic summary (never tokens).
- `models.py`: removed `School`/`parse_schools`; added `Account`/`parse_account`
  and account metadata (`account_id`, `student_id`, `student_name`) on
  `SomTodayTokens` (restored from and persisted to the config entry).
- `config_flow.py`: single paste-based login step (with the authorize URL as an
  `{auth_url}` placeholder and a Chrome DevTools tip), reauth with
  `wrong_account` detection and `async_update_reload_and_abort`, and an options
  flow that reloads via `hass.config_entries.async_schedule_reload`.
- `strings.json`/`translations`: replaced the school/credentials steps with the
  new login step and added the `invalid_url`, `login_page`, `state_mismatch`,
  `sso_callback`, `invalid_auth`, `cannot_connect`, `no_students` and
  `wrong_account` keys.
- `manifest.json` bumped to `0.3.0`.
- Tests rewritten for the new flow (`tests/test_auth.py`,
  `tests/test_config_flow.py`, `tests/test_api.py`, `tests/test_models.py`,
  `tests/test_translations.py`): 140 tests, 99% line coverage, all SomToday HTTP
  mocked.

### Fixed

- **Token-exchange failures are now diagnosable.** `_parse_token_response`
  logs the HTTP status plus the OAuth2 `error`/`error_description` (truncated,
  never the code/verifier/tokens), so a rejected code reveals whether it
  expired, was already redeemed or failed PKCE verification.
- **`redirect_uri` is sent with the code exchange**, matching the authorize
  request, for servers that require it.
- **`extract_code` hardened:** query values stop at quotes/brackets/commas so a
  copied `Location` value cannot smuggle trailing punctuation into the code;
  surrounding quotes are stripped; a Microsoft Entra ID callback
  (`/oidc?...&session_state=...`) is rejected with a dedicated `sso_callback`
  message instead of being exchanged.
- Clearer `invalid_auth` message noting the code may have expired or been used,
  and to paste the redirect immediately after logging in.
- `async_setup_entry` logs `SomToday: authenticated as <student> (account <id>)`
  at INFO once the stored session is refreshed, so a working setup (and a broken
  one) is visible in the log without debug logging. No tokens are logged.

### Removed

- Constants `SCHOOLS_URL`, `TOKEN_URL_SSO`, `CLIENT_ID_SSO`, `USERNAME_FIELD`,
  `PASSWORD_FIELD`, `CONF_TENANT_UUID`, `CONF_SCHOOL_NAME`, `CONF_USERNAME`,
  `CONF_AUTH_METHOD` and `AUTH_METHOD_PKCE`/`AUTH_METHOD_PASSWORD`.
- The `SomTodaySsoNotSupported` exception (the browser flow handles SSO/MFA).

## [0.2.0]

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
