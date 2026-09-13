# Changelog

All notable changes to the SomToday Home Assistant integration are documented
in this file.

## [0.7.2] - 2026-09-12

### Fixed

- **Lesson `subject` and `teacher` were never populated.** `Lesson.from_api`
  read `vak` and `docentAfkortingen` from the top level of the appointment, but
  SomToday returns objects requested through `additional` nested under
  **`additionalObjects`** (`additionalObjects.vak.naam`,
  `additionalObjects.docentAfkortingen`). `room` (`locatie`) and `lesson_id`
  (`links`) did appear because those are base fields — which is why only
  `subject`/`teacher` were missing on the first-lesson sensors. The parser now
  reads the nested shape and still tolerates a flat payload as a fallback.
- Docs: `architecture.md` §7.2/§7.3 corrected to the `additionalObjects`
  mapping.
- Tests: the appointment fixtures now use the real nested shape, with a
  regression test for `additionalObjects` and one for the flat fallback.
  Total: 271 tests, 100% line coverage, all SomToday HTTP mocked.
- `manifest.json` bumped to `0.7.2`.

## [0.7.1] - 2026-09-12

### Added

- **Local brand images.** `custom_components/sometoday/brand/` now ships
  `icon.png` (256×256), `icon@2x.png` (512×512), `logo.png` and `logo@2x.png`,
  so Home Assistant shows the SomToday icon/logo for the integration instead of
  the placeholder. Local brand images are used by Home Assistant **2026.3+** and
  take precedence over the central `home-assistant/brands` repository, so no
  pull request there is required. The artwork is the official SomToday logo,
  used for identification only.
- `manifest.json` bumped to `0.7.1`.

## [0.7.0] - 2026-09-12

### Added

- **`sensor.first_lesson_of_tomorrow` (architecture §8.1).** A sibling of
  `first_lesson_of_today`: its state is the timezone-aware start timestamp of
  the first lesson on the **local** date of tomorrow, and it is `unknown` when
  there is none. Attributes mirror the today sensor (`subject`, `room`,
  `teacher`, `end`, `lesson_id`) with the day's lesson count exposed as
  `lessons_tomorrow`.
- `sensor.py`: the first-lesson logic now lives in a shared
  `_SomTodayFirstLessonBase` (`_key`, `_day_offset`, `_count_attribute`);
  `SomTodayFirstLessonSensor` (today) and `SomTodayFirstLessonTomorrowSensor`
  (tomorrow) only set those class attributes. Both are registered in
  `ENTITY_CONSTRUCTORS`.
- `strings.json`/`translations`: added the
  `entity.sensor.first_lesson_of_tomorrow` name ("First lesson of tomorrow" /
  "Eerste les morgen") with identical key sets across all three files.
- `README.md`: documented the first-lesson sensor **attributes** in a table,
  including the previously omitted `lesson_id`, added the new entity row and the
  state-stays-in-the-past note.
- Tests (`tests/test_sensor.py`): tomorrow sensor state/attribute mapping
  (earliest-of-tomorrow, today ignored, unsorted input), `None` when tomorrow is
  free, entity metadata and EN/NL translations; the full-setup test now asserts
  both timestamp sensors render. `tests/test_init.py` asserts two sensors are
  forwarded/unloaded. Total: 269 tests, 100% line coverage, all SomToday HTTP
  mocked.
- `manifest.json` bumped to `0.7.0`.

## [0.6.0] - 2026-09-12

### Added

- **`sensor` platform with `first_lesson_of_today` (architecture §8.1).** The
  sensor drives an alarm clock: its state is the timezone-aware start timestamp
  of the first lesson on the **local** date of today. A lesson that already
  started or finished is still returned; the state is `unknown` when there is no
  lesson today (or no coordinator snapshot).
- `sensor.py` (new): `SomTodayFirstLessonSensor` (bound to the coordinator via
  the shared `SomTodayEntity`) with `_attr_translation_key =
  "first_lesson_of_today"`, `_attr_device_class = SensorDeviceClass.TIMESTAMP`
  and unique id `f"{entry.entry_id}_first_lesson_of_today"`. The earliest of
  today's lessons is selected from `coordinator.data.schedule`; datetimes are
  normalised with `dt_util.as_local`, so an offset-less (`naive`) timestamp is
  handled without raising. Attributes are `subject`, `room`, `teacher`, `end`,
  `lesson_id` and `lessons_today` (missing values are omitted; nothing sensitive
  is exposed). The platform is set up from a tuple of entity constructors so the
  remaining §8.1 sensors can be added without touching the platform setup.
- `__init__.py`: `PLATFORMS` now forwards `Platform.SENSOR` in addition to
  `Platform.CALENDAR` (forward/unload already generic).
- `strings.json`/`translations`: added the
  `entity.sensor.first_lesson_of_today` name ("First lesson of today" /
  "Eerste les vandaag") with identical key sets across all three files.
- Tests (`tests/test_sensor.py`, new): state/attribute mapping for several of
  today's lessons, `None` when there is no lesson today, a lesson that already
  started, `+02:00` and naive datetimes, entity metadata (translation key,
  device class, unique id, device info), the entity name in both locales, and
  `unavailable` after a failed coordinator update. `tests/test_init.py` now
  asserts the `sensor` platform is forwarded and unloaded. Total: 265 tests,
  100% line coverage, all SomToday HTTP mocked.
- `manifest.json` bumped to `0.6.0`.

## [0.5.0] - 2026-09-12

### Added

- **Schedule data slice (architecture §5, §6, §7.2, §7.2.1, §8.3).** The
  integration now polls the SomToday schedule and exposes it as a read-only
  calendar entity. Grades, homework and absence are still deferred.
- `coordinator.py` (new): `SomTodayDataUpdateCoordinator` polls
  `/rest/v1/afspraken` for the config entry's student, with
  `SomTodayData(schedule, students, updated_at)`. The window is
  `today - 1 day … today + schedule_days_ahead` (default 14) and the interval
  comes from the `scan_interval` option (default 15 min). Lessons are filtered
  per student (`not lesson.student_ids or student_id in lesson.student_ids`) and
  sorted by start time; the student list is fetched best-effort. Errors map to
  `ConfigEntryAuthFailed` (`SomtodayInvalidAuth`) or `UpdateFailed`
  (`SomTodayError`, `aiohttp.ClientError`), and a rotated refresh token is
  persisted through `hass.config_entries.async_update_entry`.
- `calendar.py` (new): `SomTodayCalendar` is a read-only `CalendarEntity` bound
  to the coordinator. `event` returns the lesson in progress or the next
  upcoming lesson; `async_get_events` serves the requested range from the cached
  schedule or fetches it directly from the API when out of range (without
  writing to the coordinator). Event summaries are `"{subject} ({room})"`
  (room omitted when absent), `location` is the room and `description` is the
  teacher.
- `entity.py` (new): shared `SomTodayEntity` base providing one device per
  config entry (`DeviceInfo` identifiers `{(DOMAIN, entry.entry_id)}`, name
  `SomToday {student_name}`, manufacturer `SomToday`) and
  `_attr_has_entity_name`.
- `api.py`: `async_get_appointments(start, end)` fetches
  `/rest/v1/afspraken` with `begindatum`, `einddatum`, `sort=asc-id` and the
  repeated `additional=vak`, `additional=docentAfkortingen`,
  `additional=leerlingen`. The endpoint is paginated with
  `Range: items=<start>-<start+99>`; pages are merged and the walk stops on a
  short page, when `Content-Range` reports no more items, or at a hard page cap.
  Both `200` and `206` are treated as success. `_send`/`_request_raw` now accept
  extra headers and expose the response so headers can be read.
- `models.py`: `Lesson` dataclass and `parse_lesson`/`parse_lessons` following
  the §7.3 mapping, including `student_ids` from
  `additionalObjects.leerlingen.items[].links[0].id`. Unparseable appointments
  are skipped instead of raising.
- `__init__.py`: builds the coordinator, runs
  `async_config_entry_first_refresh()` and stores it in
  `SomTodayRuntimeData`; `PLATFORMS = [Platform.CALENDAR]`.
- `strings.json`/`translations`: added the `entity.calendar` name
  ("Schedule"/"Rooster") with identical key sets.
- Tests: appointment pagination, `Lesson` parsing, coordinator polling, window,
  per-student filtering and error mapping, calendar `event`/`async_get_events`
  and entity metadata, plus setup/unload. Total: 246 tests, 100% line coverage,
  all SomToday HTTP mocked.
- `manifest.json` bumped to `0.5.0`.

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
