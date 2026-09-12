# Test report — SomToday Home Assistant plugin

**Component under test:** Schedule data slice (**v0.5.0**, with the **S1** fix,
the reviewer fixes **N1/N2/N3/N5/N7**, and the **B1** regression fix):
`api.py` (`async_get_appointments` + `Range` pagination, 401/403 mapping),
`models.py` (`Lesson`, `parse_lesson`, `parse_lessons`), `coordinator.py`
(`SomTodayDataUpdateCoordinator`: fresh fetch window vs. cached data window,
token persistence, per-student scoping), `entity.py` (`SomTodayEntity`),
`calendar.py` (`SomTodayCalendar`), `__init__.py` (coordinator wiring +
`PLATFORMS = [Platform.CALENDAR]`) and the `entity.calendar` translations.
**Date:** 2026-09-12 (final re-run after the B1 fix)
**Tester:** tester-agent
**Environment:**
`/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv`
(Python 3.14.7, Home Assistant 2026.9.1, pytest 9.0.3, pytest-asyncio 1.4.0,
pytest-homeassistant-custom-component 0.13.364, aioresponses 0.7.9,
pytest-cov 7.1.0, ruff 0.16.7)

> This report builds on the previously approved **v0.3.0 browser
> authorization-code + PKCE** slice and the **v0.4.0 Model A identity** slice
> (one config entry per `(account, student)`), which are unchanged and still
> green. It covers the **v0.5.0 schedule slice**, including **S1** (naive
> lesson datetimes), the reviewer findings **N1** (coordinator sort), **N2**
> (401/403 escalation), **N3** (cache-window drift), **N5** (reactive token
> rotation) and **N7** (swallowed student-list auth rejection), and the **B1**
> regression (the fetch window was frozen after the first poll). All SomToday
> HTTP is mocked (`FakeSession` / `FakeResponse`); the real API is never
> contacted.

---

## Summary

| Metric | Value |
|--------|-------|
| Test files | 10 (`test_api`, `test_auth`, `test_calendar`, `test_config_flow`, `test_const`, `test_coordinator`, `test_init`, `test_manifest`, `test_models`, `test_translations`) + `conftest.py` |
| Tests collected | **246** |
| Passed | **246** |
| Failed | **0** |
| Xfailed | **0** |
| Skipped | **0** |
| Line coverage (whole integration) | **100%** (935 statements, 0 missed) |
| Branch coverage (whole integration) | **99%** (234 branches, 4 partial) |
| Schedule-slice modules | `coordinator.py` 100%/100%, `calendar.py` 100%/100%, `entity.py` 100%/100%, `models.py` 100%/100%, `api.py` 100% line / 99% branch |
| Lint (`ruff check custom_components tests`) | **clean** (`All checks passed!`) |
| Real SomToday API calls | **none** (all HTTP via `FakeSession`/`FakeResponse`) |

Commands used:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m coverage erase
$V/python -m pytest tests/ -v --cov=custom_components.sometoday --cov-report=term-missing
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch --cov-report=term-missing
$V/python -m ruff check custom_components tests
```

Exact results: `246 passed in 2.31s` (0 failed, 0 xfailed, 0 skipped); line
`TOTAL 935 0 100%`; branch `TOTAL 935 0 234 4 99%`;
`All checks passed!` (ruff exit 0).

Per-file test counts (collected): `test_auth.py` 54, `test_models.py` 56,
`test_config_flow.py` 45, `test_api.py` 42, `test_coordinator.py` 22,
`test_calendar.py` 15, `test_translations.py` 4, `test_init.py` 4,
`test_const.py` 3, `test_manifest.py` 1.

**Gate (minimum 80% coverage): PASS** — 100% line / 99% branch, zero
failures, zero xfails, zero skips.

---

## B1 re-verification (frozen fetch window)

**B1 is FIXED.** The previous N3 fix made `schedule_window` return the cached
`_data_window`, but `_async_update_data` also read `schedule_window` for its
fetch window, so the fetch range froze after the first poll. The fix splits the
two concerns in `coordinator.py`:

- `_current_window()` (`coordinator.py:102-112`) recomputes
  `(today-1, today+schedule_days_ahead)` from `dt_util.now()` on every call;
  `_async_update_data` now uses it (`coordinator.py:116`).
- `schedule_window` (`coordinator.py:90-100`) remains the **cached-data**
  accessor: it returns `_data_window` (captured at the last successful fetch)
  and falls back to `_current_window()` only before the first poll.

B1 was re-verified **independently** with a temporary 10-scenario probe
(removed after the run), not by reusing the engineer's test. The probe ran under
the `hass` fixture's `US/Pacific` (`-07:00`) timezone.

| Probe | Scenario | Observed | Verdict |
|-------|----------|----------|---------|
| B1-P1 | Two polls one day apart (`schedule_days_ahead=3`) | First fetches `(day1-1, day1+3)`, second `(day2-1, day2+3)`; windows advance | FIXED |
| B1-P2 | "Now" moves to day2 with **no** poll | `schedule_window` stays at the day1 cache; `_current_window()` returns the day2 range | Correct split |
| B1-P3 | `schedule_window` before any poll | Equals `_current_window()` (now-based fallback) | Correct |
| B1-P4 | Failed poll on day2 after a day1 success | Cache window stays day1; a later successful day2 poll advances it | Correct |
| B1-P5 | Out-of-range `async_fetch_schedule(...)` after a poll | `schedule_window` (cache) unchanged; only the explicit fetch runs | Correct |
| B1-P6 | Calendar cache check after midnight with no poll | A day beyond the **cached** window still triggers an out-of-range fetch, even though a freshly recomputed window would have covered it | Correct (N3 preserved) |
| B1-R1 | N1: mixed naive/aware sort | No `TypeError`; sorted by `dt_util.as_local(start)` | Still FIXED |
| B1-R2 | N2: 401 vs 403 at the coordinator | `SomtodayInvalidAuth` → `ConfigEntryAuthFailed`; `SomTodayApiError` → `UpdateFailed` | Still FIXED |
| B1-R3 | N5: token rotated during the fetch | New token persisted | Still FIXED |
| B1-R4 | N7: student-list `SomtodayInvalidAuth` | Escalates to `ConfigEntryAuthFailed` | Still FIXED |

The engineer's regression test `test_consecutive_polls_advance_the_window`
covers B1-P1. The tester added
`test_schedule_window_does_not_advance_between_polls` to lock in the
cached-vs-fresh split (B1-P2), which the existing N3 tests did not assert when
the day changes without a poll. No new gap was introduced by the fix; the whole
suite (including all prior N/S findings' tests) is green.

---

## Reviewer-finding re-verification (N1/N2/N3/N5/N7)

Re-verified independently with a temporary 14-scenario probe in the previous
run; the relevant scenarios were re-run as B1-R1–B1-R4 above and remain fixed.
Summary of the current behaviour:

- **N1 — FIXED.** `_filter_lessons` sorts with `dt_util.as_local(lesson.start)`
  (`coordinator.py:147`); a mixed naive/aware payload is ordered by the
  normalised instant and cannot raise.
- **N2 — FIXED.** `api._async_decode` maps a surviving 401 to
  `SomtodayInvalidAuth` (→ `ConfigEntryAuthFailed`/reauth) and a 403 to the
  retryable `SomTodayApiError` (→ `UpdateFailed`). `_request_raw` refreshes only
  on 401, so 403 is never retried. Verified at `/leerlingen`, paginated
  `/afspraken` and the coordinator.
- **N3 — FIXED.** `schedule_window` is captured at the last successful fetch
  (`_data_window`), so the calendar's cache check does not drift across midnight
  or after a failed poll (B1-P2/P4/P6).
- **N5 — FIXED.** The refresh token is persisted at the **end** of the poll,
  capturing a rotation performed reactively inside the fetch.
- **N7 — FIXED.** `_async_get_students` re-raises `SomtodayInvalidAuth` while
  still swallowing transient errors.

### S1 (naive lesson datetimes) — still fixed
`calendar.py` normalises with `dt_util.as_local` in `_current_or_next_lesson`
and `_event_from_lesson`; covered by
`test_event_with_naive_lesson_datetime` and
`test_async_get_events_with_naive_lesson_datetime`.

---

## Schedule-slice verification

Every requested scenario was reproduced from the production code and the
passing suite, not from test names alone.

| Required scenario | Test(s) | Verdict |
|-------------------|---------|---------|
| Appointment params: `begindatum`, `einddatum`, `sort=asc-id`, repeated `additional=vak`/`docentAfkortingen`/`leerlingen` | `test_get_appointments_single_page_200` | PASS |
| Pagination — single page `200` | `test_get_appointments_single_page_200`, `test_get_appointments_plain_list_payload` | PASS |
| Pagination — `206` multi-page merge (no double count) | `test_get_appointments_paginates_two_pages` (150 items, 2 calls) | PASS |
| Pagination — short page stops the walk | `test_get_appointments_stops_on_short_page`, `test_get_appointments_206_single_page` | PASS |
| Pagination — full page + `Content-Range` total ends the walk | `test_get_appointments_stops_when_content_range_is_complete` | PASS |
| Pagination — total `*` keeps walking, hard cap bounds it | `test_get_appointments_hard_page_cap`, `test_get_appointments_star_total_then_short_page` | PASS |
| Pagination — malformed `Content-Range` degrades gracefully | `test_get_appointments_malformed_content_range_continues` | PASS |
| Pagination — `Range` header first vs later pages | `test_get_appointments_single_page_200` (`items=0-99`), `test_get_appointments_paginates_two_pages` (`items=100-199`) | PASS |
| Pagination — persistent 401 → definitive; 403 → retryable (N2) | `test_get_appointments_persistent_401_is_definitive`, `test_get_appointments_403_is_retryable` | PASS |
| Pagination — unexpected 2xx status rejected | `test_get_appointments_unexpected_success_status` | PASS |
| Pagination — page body read error → `SomTodayConnectionError` | `test_get_appointments_body_read_error` | PASS |
| Pagination — every page released | `test_get_appointments_releases_pages` | PASS |
| `Lesson` parsing — every field + `student_ids` | `test_parse_lesson_documented_shape`, `test_parse_lesson_tolerates_odd_student_objects` | PASS |
| `Lesson` — missing/invalid dates skipped, not raised | `test_parse_lesson_unparseable_dates_skipped` (5 cases) | PASS |
| Datetime parsing — `+02:00`, `Z`, mixed offsets | `test_parse_lesson_documented_shape`, `test_parse_lesson_z_suffix_timezone`, `test_parse_lesson_offset_timezones_represent_same_instant` | PASS |
| Naive (offset-less) datetimes — `event` / `async_get_events` (S1) | `test_event_with_naive_lesson_datetime`, `test_async_get_events_with_naive_lesson_datetime` | PASS |
| Mixed naive/aware sort does not crash (N1) | `test_update_data_mixed_naive_aware_sorts`, probes B1-R1 | PASS |
| 401/403 escalation (N2) | `test_get_students_persistent_401_is_definitive`, `test_get_students_auth_error`, `test_get_appointments_persistent_401_is_definitive`, `test_get_appointments_403_is_retryable`, probes B1-R2 | PASS |
| Fetch window advances across days (B1) | `test_consecutive_polls_advance_the_window`, probe B1-P1 | PASS |
| Cached window does not advance between polls (B1/N3) | `test_schedule_window_does_not_advance_between_polls` **(new)**, `test_schedule_window_tracks_the_last_fetch`, probes B1-P2/P3 | PASS |
| Window survives a failed poll (N3) | `test_schedule_window_survives_failed_poll`, probe B1-P4 | PASS |
| Token rotated during the poll is persisted (N5) | `test_update_data_persists_token_rotated_during_fetch`, probe B1-R3 | PASS |
| Student-list auth rejection escalates (N7) | `test_update_data_escalates_students_invalid_auth`, probe B1-R4 | PASS |
| Per-student filtering — other-student lesson dropped | `test_update_data_filters_per_student` (`other` dropped), `test_async_fetch_schedule_filters_and_sorts` | PASS |
| Per-student filtering — no-`student_ids` / empty-`student_ids` kept | `test_update_data_filters_per_student` | PASS |
| Window dates incl. `schedule_days_ahead` option | `test_update_data_window_dates` (7), `test_update_data_default_window` (14), `test_schedule_window_reflects_days_ahead` (3) | PASS |
| Coordinator — successful poll + sorted snapshot | `test_update_data_success` | PASS |
| Coordinator — error mapping | `test_update_data_invalid_auth`, `test_update_data_somtoday_error`, `test_update_data_client_error` | PASS |
| Coordinator — rotated-token persistence / no-op | `test_update_data_persists_rotated_token`, `test_update_data_keeps_token_when_not_rotated` | PASS |
| Coordinator — student list is best-effort | `test_update_data_keeps_previous_students_on_failure`, `test_update_data_students_failure_without_snapshot` | PASS |
| Coordinator — poll interval option/default | `test_update_interval_from_options`, `test_update_interval_default` | PASS |
| Calendar `event` — current, next, none, room omitted | `test_event_returns_current_lesson`, `test_event_returns_next_lesson`, `test_event_returns_none_after_last_lesson`, `test_event_without_room_omits_parentheses` | PASS |
| Calendar `async_get_events` — cache | `test_async_get_events_from_cache`, `test_async_get_events_filters_outside_range`, `test_async_get_events_empty_cache` | PASS |
| Calendar `async_get_events` — out-of-range fetch (cache untouched) | `test_async_get_events_out_of_range_fetches`, probe B1-P5/P6 | PASS |
| Calendar `async_get_events` — cache/out-of-range boundaries | `test_async_get_events_full_window_uses_cache`, `test_async_get_events_window_end_boundary_fetches`, `test_async_get_events_without_snapshot` | PASS |
| Entity device/unique id + read-only (N8) | `test_calendar_entity_metadata`, `test_calendar_is_read_only` | PASS |
| Setup/unload with the calendar platform | `test_setup_entry_creates_coordinator_and_calendar`, `test_unload_entry_unloads_calendar` | PASS |
| Setup first refresh does not make a real network call | independent probe (traps `aiohttp.ClientSession._request`/`get`/`post`; setup still LOADED) | PASS |
| Calendar entity translations load (EN/NL) | `test_calendar_entity_translations_load`, `test_translation_files_have_matching_keys` | PASS |

---

## Test cases

### Component: REST API (`tests/test_api.py`, 42 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_get_appointments_single_page_200` | Whole list in one 200 page; params + `Range: items=0-99` + auth header | PASS |
| `test_get_appointments_paginates_two_pages` | 206 pages merge; `Range` advances to `items=100-199` | PASS |
| `test_get_appointments_stops_on_short_page` | A page shorter than 100 ends the walk | PASS |
| `test_get_appointments_stops_when_content_range_is_complete` | Full page with `Content-Range: …/100` ends the walk | PASS |
| `test_get_appointments_206_single_page` | A short 206 page is complete | PASS |
| `test_get_appointments_hard_page_cap` | Unterminated `*` list bounded by the cap | PASS |
| `test_get_appointments_star_total_then_short_page` | `*` total keeps walking until a short page | PASS |
| `test_get_appointments_malformed_content_range_continues` | Unparsable header degrades to short-page stop | PASS |
| `test_get_appointments_plain_list_payload` | Bare list page tolerated | PASS |
| `test_get_appointments_full_page_without_content_range_continues` | Missing `Content-Range` keeps walking | PASS |
| `test_get_appointments_releases_pages` | Every page released | PASS |
| `test_get_appointments_401_refreshes_and_retries` | One reactive refresh + retry | PASS |
| `test_get_appointments_persistent_401_is_definitive` | Surviving 401 on a page → `SomtodayInvalidAuth` (N2) | PASS |
| `test_get_appointments_403_is_retryable` | 403 on a page → `SomTodayApiError` (N2) | PASS |
| `test_get_appointments_error_status` | 5xx page → `SomTodayApiError` | PASS |
| `test_get_appointments_unexpected_success_status` | 201 page → `SomTodayApiError` | PASS |
| `test_get_appointments_invalid_payload` | `{"items": "nope"}` → `SomTodayApiError` | PASS |
| `test_get_appointments_non_sequence_payload` | Scalar page payload → `SomTodayApiError` | PASS |
| `test_get_appointments_non_json_body` | Non-JSON page → `SomTodayApiError` | PASS |
| `test_get_appointments_body_read_error` | Transport error reading a page → `SomTodayConnectionError` | PASS |
| `test_get_appointments_does_not_filter_students` | Client returns all; scoping is the coordinator's job | PASS |
| `test_get_students_parses_items` | `{"items": [...]}` parsed; params + auth header | PASS |
| `test_get_students_auth_error` | 403 → `SomTodayApiError` (retryable, N2) | PASS |
| `test_get_students_persistent_401_is_definitive` | Surviving 401 → `SomtodayInvalidAuth` (N2) | PASS |
| `test_get_students_401_refreshes_and_retries` | One refresh + retry on 401 | PASS |
| `test_get_students_401_retry_still_401` | Retry rejected again → auth error after one refresh | PASS |
| `test_get_students_401_refresh_failure_propagates` | Failing refresh propagates | PASS |
| `test_get_students_rate_limit` | 429 → `SomTodayRateLimitError` | PASS |
| `test_get_students_server_error` | 5xx → `SomTodayApiError` | PASS |
| `test_get_students_connection_error` | Network error → `SomTodayConnectionError` | PASS |
| `test_get_students_invalid_json` | Malformed payload → `SomTodayApiError` | PASS |
| `test_get_students_releases_*` (2) | 401 and final responses released | PASS |
| `test_get_students_non_json_body`, `_body_read_error` | Body-decode failures mapped | PASS |
| `test_error_response_releases_and_logs_diagnostics`, `_text_read_error` | Error diagnostics released/bounded | PASS |
| `test_build_headers_without_tokens`, `test_send_post_uses_session_post`, `test_release_ignores_response_without_release` | Header/transport helpers | PASS |
| `test_get_account_parses`, `test_get_account_invalid_payload` | `/account/me` parsing | PASS |

### Component: coordinator (`tests/test_coordinator.py`, 22 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_update_data_success` | Parsed lessons + students + aware timestamp | PASS |
| `test_update_data_filters_per_student` | Other-student dropped; unscoped/empty kept; sorted | PASS |
| `test_update_data_mixed_naive_aware_sorts` | Mixed naive/aware payload sorts without raising (N1) | PASS |
| `test_update_data_window_dates` / `_default_window` | `schedule_days_ahead` and default windows | PASS |
| `test_schedule_window_reflects_days_ahead` | Window property honours the option | PASS |
| `test_consecutive_polls_advance_the_window` **(new, B1)** | Each poll recomputes the fetch window from today | PASS |
| `test_schedule_window_does_not_advance_between_polls` **(new, B1/N3)** | Cached window stays put; fetch window advances | PASS |
| `test_schedule_window_tracks_the_last_fetch` | Window reflects the fetched range, not "now" (N3) | PASS |
| `test_schedule_window_survives_failed_poll` | Failed poll keeps the last successful window (N3) | PASS |
| `test_update_interval_from_options` / `_default` | Poll interval option/default | PASS |
| `test_update_data_invalid_auth` | `SomtodayInvalidAuth` → `ConfigEntryAuthFailed` | PASS |
| `test_update_data_somtoday_error` | `SomTodayError` → `UpdateFailed` | PASS |
| `test_update_data_client_error` | `aiohttp.ClientError` → `UpdateFailed` | PASS |
| `test_update_data_escalates_students_invalid_auth` | Student-list auth rejection → `ConfigEntryAuthFailed` (N7) | PASS |
| `test_update_data_keeps_previous_students_on_failure` | Transient student failure keeps snapshot | PASS |
| `test_update_data_students_failure_without_snapshot` | No snapshot → empty list | PASS |
| `test_update_data_persists_rotated_token` | Rotated token written back | PASS |
| `test_update_data_persists_token_rotated_during_fetch` | Rotation during the fetch is persisted (N5) | PASS |
| `test_update_data_keeps_token_when_not_rotated` | No-op rotation leaves entry untouched | PASS |
| `test_async_fetch_schedule_filters_and_sorts` | Out-of-range fetch applies the same scope | PASS |

### Component: calendar (`tests/test_calendar.py`, 15 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_event_returns_current_lesson` | In-progress lesson with all mapped fields | PASS |
| `test_event_returns_next_lesson` | Next upcoming lesson | PASS |
| `test_event_returns_none_after_last_lesson` | `None` after the last lesson | PASS |
| `test_event_without_room_omits_parentheses` | Summary/location when room absent | PASS |
| `test_event_with_naive_lesson_datetime` | S1: offset-less lesson no longer crashes `event` | PASS |
| `test_async_get_events_with_naive_lesson_datetime` | S1: offset-less lesson → tz-aware event | PASS |
| `test_async_get_events_from_cache` | In-window range served from cache | PASS |
| `test_async_get_events_filters_outside_range` | Overlap filter applied | PASS |
| `test_async_get_events_out_of_range_fetches` | Out-of-range fetch; cache untouched | PASS |
| `test_async_get_events_empty_cache` | Empty cache → no events | PASS |
| `test_async_get_events_without_snapshot` | `coordinator.data is None` → no events | PASS |
| `test_async_get_events_full_window_uses_cache` | Exact window boundaries use the cache | PASS |
| `test_async_get_events_window_end_boundary_fetches` | Range past the window fetches | PASS |
| `test_calendar_entity_metadata` | Unique id + shared device | PASS |
| `test_calendar_is_read_only` | No create/update/delete features advertised (N8) | PASS |

### Components carried over (approved v0.3.0 / v0.4.0 slices, unchanged)

| Component | Tests | Result |
|-----------|-------|--------|
| `tests/test_auth.py` — PKCE, code extraction, exchange, refresh, holder | 54 | PASS |
| `tests/test_config_flow.py` — user/student/reauth/options/migration | 45 | PASS |
| `tests/test_models.py` — `Account`/`Student`/`SomTodayTokens`/`Lesson` | 56 | PASS |
| `tests/test_translations.py` — key parity + EN/NL config & calendar entity | 4 | PASS |
| `tests/test_init.py` — setup/unload, retry, reauth | 4 | PASS |
| `tests/test_const.py` — composite unique id | 3 | PASS |
| `tests/test_manifest.py` — domain/version/`config_flow`/`iot_class` | 1 | PASS |

---

## Coverage

Line coverage (`--cov-report=term-missing`):

```text
Name                                         Stmts   Miss  Cover   Missing
--------------------------------------------------------------------------
custom_components/sometoday/__init__.py         47      0   100%
custom_components/sometoday/api.py             162      0   100%
custom_components/sometoday/auth.py            151      0   100%
custom_components/sometoday/calendar.py         58      0   100%
custom_components/sometoday/config_flow.py     155      0   100%
custom_components/sometoday/const.py            35      0   100%
custom_components/sometoday/coordinator.py      74      0   100%
custom_components/sometoday/entity.py           13      0   100%
custom_components/sometoday/exceptions.py        7      0   100%
custom_components/sometoday/models.py          233      0   100%
--------------------------------------------------------------------------
TOTAL                                          935      0   100%
```

Branch coverage (`--cov-branch --cov-report=term-missing`):

```text
Name                                         Stmts   Miss Branch BrPart  Cover   Missing
----------------------------------------------------------------------------------------
custom_components/sometoday/__init__.py         47      0      4      1    98%   84->91
custom_components/sometoday/api.py             162      0     44      2    99%   370->373, 375->381
custom_components/sometoday/auth.py            151      0     40      1    99%   81->exit
custom_components/sometoday/calendar.py         58      0     12      0   100%
custom_components/sometoday/config_flow.py     155      0     40      0   100%
custom_components/sometoday/const.py            35      0      0      0   100%
custom_components/sometoday/coordinator.py      74      0      6      0   100%
custom_components/sometoday/entity.py           13      0      0      0   100%
custom_components/sometoday/exceptions.py        7      0      0      0   100%
custom_components/sometoday/models.py          233      0     88      0   100%
----------------------------------------------------------------------------------------
TOTAL                                          935      0    234      4    99%
```

| File | Stmts | Missed | Branches | Partial | Line | Branch |
|------|------:|-------:|---------:|--------:|-----:|-------:|
| `__init__.py` | 47 | 0 | 4 | 1 | 100% | 98% |
| `api.py` | 162 | 0 | 44 | 2 | 100% | 99% |
| `auth.py` | 151 | 0 | 40 | 1 | 100% | 99% |
| `calendar.py` | 58 | 0 | 12 | 0 | 100% | 100% |
| `config_flow.py` | 155 | 0 | 40 | 0 | 100% | 100% |
| `const.py` | 35 | 0 | 0 | 0 | 100% | 100% |
| `coordinator.py` | 74 | 0 | 6 | 0 | 100% | 100% |
| `entity.py` | 13 | 0 | 0 | 0 | 100% | 100% |
| `exceptions.py` | 7 | 0 | 0 | 0 | 100% | 100% |
| `models.py` | 233 | 0 | 88 | 0 | 100% | 100% |
| **Total** | **935** | **0** | **234** | **4** | **100%** | **99%** |

The four remaining partial branches are pre-existing defensive guards,
unrelated to the schedule slice (all inside `_log_error_summary`/auth
diagnostics):

- `__init__.py:84->91` — `auth.tokens is None` guard.
- `api.py:370->373` — `response.headers` not a `Mapping` in `_log_error_summary`.
- `api.py:375->381` — response object without a `text` attribute.
- `auth.py:81->exit` — `_release()` on a response without `release`.

The schedule slice is at **100% line and 100% branch** for `coordinator.py`,
`calendar.py`, `entity.py` and `models.py`; `api.py` is 100% line / 99% branch
(the two partials above are diagnostic helpers).

---

## Findings

### Fixed (independently re-verified)

| ID | Finding | Evidence | Status |
|----|---------|----------|--------|
| **B1** | Fetch window frozen after the first poll (regression from the N3 fix) | `_current_window()` recomputes per poll; `schedule_window` stays the cached accessor. `test_consecutive_polls_advance_the_window`, `test_schedule_window_does_not_advance_between_polls`, probes B1-P1–B1-P6 | **FIXED** |
| **N1** | Mixed naive/aware lesson timestamps crashed the coordinator sort | `_filter_lessons` normalises with `dt_util.as_local`; `test_update_data_mixed_naive_aware_sorts`, probe B1-R1 | **FIXED** |
| **N2** | Persistent data-API 401/403 never escalated | 401 → `SomtodayInvalidAuth` → `ConfigEntryAuthFailed`; 403 → `SomTodayApiError` → `UpdateFailed`; 4 API + 2 coordinator tests, probe B1-R2 | **FIXED** |
| **N3** | Cache window derived from "now", drifted across midnight/after failure | `schedule_window` returns `_data_window` captured at fetch time; `test_schedule_window_tracks_the_last_fetch`, `test_schedule_window_survives_failed_poll`, probes B1-P2/P4/P6 | **FIXED** |
| **N5** | Reactive token rotation not persisted until the next poll | Token persisted at the end of `_async_update_data`; `test_update_data_persists_token_rotated_during_fetch`, probe B1-R3 | **FIXED** |
| **N7** | `_async_get_students` swallowed `SomtodayInvalidAuth` | Re-raised before the transient catch; `test_update_data_escalates_students_invalid_auth`, probe B1-R4 | **FIXED** |
| **S1** | Naive lesson datetimes crashed the calendar | Two permanent calendar tests | **FIXED** |
| **N8** | "Read-only" calendar claim not asserted | `test_calendar_is_read_only` asserts no create/update/delete features | **FIXED (test quality)** |

### N9 — Documentation drift — **PARTIAL, OPEN (Info, docs)**
Residual drift remains (not fixable from the tester role):

- **`docs/architecture.md:503` (§5.1) is inconsistent with the implemented N2
  behaviour.** The table still says `401` / `403` from the data API →
  `SomTodayAuthError` → "still failing → `ConfigEntryAuthFailed`". The code maps
  a 403 to the retryable `SomTodayApiError` → `UpdateFailed` (intentional). The
  401 row is consistent (a narrower `SomtodayInvalidAuth`). The 403 row needs an
  architecture-doc amendment.
- **`docs/architecture.md:921-925`** still labels the coordinator and entity
  test suites "(future work)"; both now exist.
- **`README.md:92-93`** still says the options "only take effect once the
  coordinator and entities are added in a later release"; they take effect in
  v0.5.0.
- **`docs/CHANGELOG.md:53`** records "235 tests"; the suite is now 246 (the
  count moves with every test change and is inherently prone to drift).

### Open, non-blocking (from the reviewer)

- **N4 — Out-of-range calendar fetches bypass coordinator error handling
  (Low).** `calendar._lessons_for_range` calls `coordinator.async_fetch_schedule`
  directly, so `SomtodayInvalidAuth`/`SomTodayError`/`aiohttp.ClientError` can
  escape `async_get_events`. Unchanged; not tested (would require a production
  change).
- **N6 — Out-of-range fetches are not cached (Low, load).** Every out-of-window
  `async_get_events` issues a fresh paginated request. Unchanged.
- **S2 / N11 — Paginated items are not de-duplicated (Info).** Trusts server
  `Range` offsets; overlapping pages would double-count, bounded by the cap. No
  repro with a well-behaved mock.
- **S3 — Mixed naive/aware inverted interval (Info).** A malformed payload that
  inverts the interval after local normalisation would fail `CalendarEvent`
  validation. The reachable mixed case (N1) is fixed; the inverted-interval case
  remains unreachable with well-formed data.
- **N10 — Link selection uses the first link regardless of `rel` (Info,
  carry-over M2).** Follows architecture §7.3 (`links[0].id`); confirm against a
  live payload.
- **Carry-overs:** `T4` (`/account/me` omits `additional=restricties`),
  `T6/R7` (concurrent forced refreshes not deduplicated), `T7–T9`
  (low-probability paste edge cases), `F2` (migrated v1 entry without a student
  id is un-reauthable, Low), `F3` (`config.error.wrong_account` unused, Info),
  `F4` (`_async_current_ids(include_ignore=True)`, Info). `T3/R4` is closed by
  N2. None of the remaining items affect the schedule slice.

---

## Blockers

1. **Real-account validation is prohibited.** The live shape of
   `/rest/v1/afspraken` pagination (exact `Content-Range` syntax and whether a
   single-student account populates `additionalObjects.leerlingen`) can only be
   confirmed against a real account. Tests use the documented and defensive
   shapes.
2. **No live multi-student account.** Per-student scoping is verified against
   mocked `additionalObjects.leerlingen.items[].links[0].id` payloads only.
3. **Live confirmation of offset-less timestamps is impossible here.** The S1/N1
   fixes are defensive; both are covered by mocked probes and permanent tests.
4. **Architecture §5.1 403 row needs an owner decision.** The code intentionally
   treats 403 as retryable; the architecture table still says reauth. The tester
   cannot modify `architecture.md`; the architect/engineer should amend §5.1
   (and remove the "future work" labels) to close N9.

No test requires a production change to pass, and no test was removed or
weakened.

---

## Changes made by the tester (this run)

**No production code was modified.** The engineer fixed B1 and added
`test_consecutive_polls_advance_the_window`; the tester re-verified B1
independently, re-checked N1/N2/N5/N7, added one regression test, and updated
this report. The temporary 10-scenario probe was removed.

| Action | Detail |
|--------|--------|
| `test_coordinator.py` +1 | `test_schedule_window_does_not_advance_between_polls` — locks in the cached-vs-fresh window split (B1-P2), which the N3 tests did not assert when the day changes without a poll |
| Probe (temporary, removed) | 10 scenarios B1-P1–B1-P6 + B1-R1–B1-R4: consecutive-poll window advance, cached window frozen between polls, pre-first-poll fallback, failed-poll retention, out-of-range fetch isolation, calendar cache check after midnight, plus N1/N2/N5/N7 re-checks |
| Report rewritten | B1 marked fixed; summary, matrices, coverage, findings, blockers and verdict updated; S2/S3/N4/N6/N9/N10/N11 and carry-overs kept current |
| Production code | untouched |
| Tests removed | none |

### Test-quality assessment and gate

| Criterion | Result |
|-----------|--------|
| Minimum 80% coverage | **Met** — 100% line, 99% branch; schedule modules 100% line/branch except api 99% branch (diagnostic guards) |
| All tests pass | **Met** — 246 passed, 0 failed, 0 xfailed, 0 skipped |
| Error scenarios tested | **Met** — 401/403 definitive-vs-retryable, auth/rate-limit/5xx/2xx-odd/non-JSON/body-read/connection, malformed & `*` pagination, hard cap, coordinator error mapping, mixed naive/aware sort, window advance/failure, token rotation, calendar out-of-range, missing snapshot, naive datetimes |
| No production code modified | **Met** |
| No test removed or weakened | **Met** — one regression test added by the engineer, one by the tester |

**Final verdict:** the v0.5.0 schedule slice is independently validated. The
**B1 regression is genuinely fixed**: `_async_update_data` recomputes the fetch
window from `dt_util.now()` on every poll (so it advances across days), while
`schedule_window` remains the cached-data accessor captured at the last
successful fetch (so the calendar's cache check cannot drift across midnight or
after a failed poll). The reviewer findings **N1, N2, N3, N5, N7** and **S1**
remain fixed, and no new gap was introduced. The whole integration is at **100%
line / 99% branch** with **246/246 tests passing and zero xfails/skips**.
Remaining items are non-blocking: **N4/N6** (Low), **S2/S3/N10/N11** and the
carry-overs (Info), and the residual **N9** documentation drift — chiefly the
architecture §5.1 403 row, which needs an owner amendment to match the
now-intentional retryable behaviour. **The 80% gate is met with room to spare.**
