# Test report — SomToday Home Assistant plugin

## v0.8.0 — Grades slice (current)

**Component under test:** Grades slice (**v0.8.0**): `models.py` (`Grade`,
`_as_float`, `parse_grade`, `parse_grades`), `api.py`
(`async_get_grades`, `GRADES_PATH`), `coordinator.py` (`SomTodayData.grades`,
the `enable_grades` opt-out and the non-fatal `_async_get_grades`),
`sensor.py` (`SomTodayAverageGradeSensor`, `SomTodayLatestGradeSensor`,
`SomTodayGradesCountSensor`), `manifest.json` 0.8.0 and the three new
`entity.sensor.*` translation keys. The previously approved v0.3.0 (auth),
v0.4.0 (identity), v0.5.0 (schedule/calendar) and v0.6.0/v0.7.0 (first-lesson
sensors, brand images, `additionalObjects` parser fix) slices are unchanged
and still green.
**Date:** 2026-09-13.
**Tester:** tester-agent.
**Environment:**
`/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv`
(Python 3.14.7, Home Assistant 2026.9.1, pytest 9.0.3, pytest-asyncio 1.4.0,
pytest-homeassistant-custom-component 0.13.364, aioresponses 0.7.9,
pytest-cov 7.1.0, ruff 0.16.8).

All SomToday HTTP is mocked (`FakeSession` / `FakeResponse` or
`unittest.mock.patch`); the real API is never contacted.

### Summary

| Metric | Value |
|--------|-------|
| Test files | 11 + `conftest.py` |
| Tests collected | **313** |
| Passed | **313** |
| Failed | **0** |
| Xfailed / Skipped | **0 / 0** |
| Line coverage (whole integration) | **100%** (1199 statements, 0 missed) |
| Branch coverage (whole integration) | **99%** (318 branches, 10 partial, all pre-existing diagnostic guards) |
| Grades modules | `models.py` **100% line / 100% branch**, `coordinator.py` **100% / 100%**, `sensor.py` **100% line / 97% branch** (167 statements, 46 branches) |
| Lint (`ruff check custom_components tests`) | **clean** (`All checks passed!`, exit 0) |
| Real SomToday API calls | **none** (all HTTP mocked) |

**Gate (minimum 80% coverage): PASS** — 100% line, zero failures.

### Test cases (v0.8.0)

| Area | Test | Goal | Result |
|------|------|------|--------|
| `models.py` | `test_parse_grade_documented_shape` | Map the real payload (string grade, date, `type`, `vak`) | PASS |
| `models.py` | `test_parse_grade_reads_subject_from_nested_additional_objects` | Tolerate `additionalObjects.vak` | PASS |
| `models.py` | `test_grade_value_falls_back_to_result` / `test_grade_non_numeric_result_is_none` / `test_grade_empty_string_result_is_none` | `geldendResultaat` fallback, `"V"` and `""` → `None` | PASS |
| `models.py` | `test_grade_numeric_result_is_accepted` / `test_grade_decimal_comma_is_tolerated` | int/float and `"7,5"` coercion | PASS |
| `models.py` | `test_grade_average_column_detection` | `*GemiddeldeKolom` flagged, `Toetskolom` not | PASS |
| `models.py` | `test_grade_counts_reflects_telt_niet_mee` / `test_grade_not_made_flag` | `teltNietmee` → `counts`; `toetsNietGemaakt` → `not_made` | PASS |
| `models.py` | `test_parse_grade_missing_id_returns_none` / `test_parse_grades_skips_unparseable_entries` | Malformed rows are skipped | PASS |
| `models.py` | `test_parse_grades_items_shape` / `plain_list_shape` / `empty` / `invalid_payloads` | Both payload shapes; `TypeError` on non-list | PASS |
| `api.py` | `test_get_grades_url_params_and_range` | URL, `additional=toetssoortnaam`, `Range: items=0-99`, bearer | PASS |
| `api.py` | `test_get_grades_paginates_two_pages` / `empty` | `Range` walker merges pages | PASS |
| `api.py` | `test_get_grades_403_is_retryable` / `error_status` / `401_refreshes_and_retries` | Error mapping and reactive refresh | PASS |
| `coordinator.py` | `test_update_data_fetches_and_parses_grades` | Grades fetched, parsed and scoped per student | PASS |
| `coordinator.py` | `test_update_data_skips_grades_when_disabled` | `enable_grades=False` skips the call | PASS |
| `coordinator.py` | `test_update_data_keeps_previous_grades_on_failure` / `grades_failure_without_snapshot` / `grades_failure_does_not_fail_the_poll` | Non-fatal failure keeps the snapshot and the schedule | PASS |
| `coordinator.py` | `test_update_data_grades_invalid_auth_escalates` | Auth rejection still triggers reauth | PASS |
| `sensor.py` | `test_average_grade_overall_and_per_subject` / `rounds_to_one_decimal` | Overall mean + per-subject `averages` map | PASS |
| `sensor.py` | `test_average_grade_excludes_average_columns_and_non_counting` | Average columns / non-counting / not-made excluded | PASS |
| `sensor.py` | `test_latest_grade_state_and_subject` / `falls_back_to_abbreviation` | Latest grade reports its subject | PASS |
| `sensor.py` | `test_grades_count_counts_only_valid_grades` | Count excludes average/non-counting rows | PASS |
| `sensor.py` | `test_grade_sensors_handle_a_missing_snapshot` / `handle_a_grade_without_a_date` / `helpers_skip_gradeless_rows` | Edge cases (no snapshot, no date, no value) | PASS |
| `test_init.py` | `test_setup_entry_creates_coordinator_and_entities` / `unload_entry_unloads_platforms` | Platform now creates 5 sensors / 6 entities total | PASS |
| `test_translations.py` | `test_translation_files_have_matching_keys` | `strings.json`/`en`/`nl` keys stay in sync | PASS |

Per-file test counts (collected): `test_models.py` 77, `test_auth.py` 54,
`test_api.py` 48, `test_config_flow.py` 45, `test_sensor.py` 34,
`test_coordinator.py` 28, `test_calendar.py` 15, `test_translations.py` 4,
`test_init.py` 4, `test_const.py` 3, `test_manifest.py` 1.

### Findings

- **No open defects.** The grades slice meets the acceptance criteria:
  per-subject average (`averages` attribute) and `latest_grade` carrying its
  `subject` are both covered directly.
- Non-fatal grades behaviour is verified: a grades `SomTodayError` leaves
  `schedule` populated and keeps the previous `grades`; a
  `SomtodayInvalidAuth` still escalates to `ConfigEntryAuthFailed`.

---

# Historical test report — v0.6.0 first-lesson sensor slice

**Component under test:** First-lesson sensor slice (**v0.6.0**) including the
**S4** fix: `sensor.py` (`SomTodayFirstLessonSensor`, single-`now` derived
state), `__init__.py` (`PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]`) and
the `entity.sensor.first_lesson_of_today` translations, plus the carried-over
approved slices.
**Date:** 2026-09-12 (S4 re-verification and final re-run)
**Tester:** tester-agent
**Environment:**
`/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv`
(Python 3.14.7, Home Assistant 2026.9.1, pytest 9.0.3, pytest-asyncio 1.4.0,
pytest-homeassistant-custom-component 0.13.364, aioresponses 0.7.9,
pytest-cov 7.1.0, ruff 0.16.7)

> This report builds on the previously approved **v0.3.0 browser
> authorization-code + PKCE** slice, the **v0.4.0 Model A identity** slice (one
> config entry per `(account, student)`) and the **v0.5.0 schedule + calendar**
> slice (including the S1/N1/N2/N3/N5/N7/B1 fixes), which are unchanged and
> still green. It covers the **v0.6.0 `first_lesson_of_today` sensor** and the
> **S4 fix** (state/attributes derived from a single "now"). All SomToday HTTP
> is mocked (`FakeSession` / `FakeResponse` or `unittest.mock.patch`); the real
> API is never contacted.

---

## Summary

| Metric | Value |
|--------|-------|
| Test files | 11 (`test_api`, `test_auth`, `test_calendar`, `test_config_flow`, `test_const`, `test_coordinator`, `test_init`, `test_manifest`, `test_models`, `test_sensor`, `test_translations`) + `conftest.py` |
| Tests collected | **265** |
| Passed | **265** |
| Failed | **0** |
| Xfailed | **0** |
| Skipped | **0** |
| Line coverage (whole integration) | **100%** (994 statements, 0 missed) |
| Branch coverage (whole integration) | **99%** (248 branches, 4 partial) |
| Sensor-slice module | `sensor.py` **100% line / 100% branch** (59 statements, 14 branches, 0 missed/partial) |
| Lint (`ruff check custom_components tests`) | **clean** (`All checks passed!`, exit 0) |
| Real SomToday API calls | **none** (all HTTP mocked) |

Commands used:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m coverage erase
$V/python -m pytest tests/ -v --cov=custom_components.sometoday --cov-report=term-missing
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch --cov-report=term-missing
$V/python -m ruff check custom_components tests
```

Exact results: `265 passed in 1.95s` (line run) / `265 passed in 2.27s` (branch
run); 0 failed, 0 xfailed, 0 skipped. Line `TOTAL 994 0 100%`; branch
`TOTAL 994 0 248 4 99%`; `All checks passed!` (ruff exit 0).

Per-file test counts (collected): `test_auth.py` 54, `test_models.py` 56,
`test_config_flow.py` 45, `test_api.py` 42, `test_coordinator.py` 22,
`test_sensor.py` **19**, `test_calendar.py` 15, `test_translations.py` 4,
`test_init.py` 4, `test_const.py` 3, `test_manifest.py` 1.

**Gate (minimum 80% coverage): PASS** — 100% line / 99% branch, zero
failures, zero xfails, zero skips.

---

## S4 re-verification (single "now" for state and attributes)

**S4 is FIXED.** The v0.6.0 fix removes the two independent `dt_util.now()`
calls from the properties and replaces them with a single cached snapshot:

- `_refresh_derived(now)` (`sensor.py:107-132`) computes `_first_lesson` and
  `_today_lessons` once for one `now`.
- `__init__` (`sensor.py:66`) captures the snapshot at construction.
- `_handle_coordinator_update` (`sensor.py:98-105`) recomputes the snapshot
  from a fresh `dt_util.now()` **before** delegating to
  `super()._handle_coordinator_update()` (which writes the state).
- `native_value` (`sensor.py:68-73`) and `extra_state_attributes`
  (`sensor.py:75-96`) only read the cached fields; neither calls `now()`.

S4 was re-verified **independently** with a temporary 5-scenario probe (removed
after the run), not by reusing the engineer's test. The probe ran under the
`hass` fixture's `US/Pacific` (`-07:00`) timezone.

| Probe | Scenario | Observed | Verdict |
|-------|----------|----------|---------|
| S4-P1 | **Exact original repro**: entity built on day1; patch `sensor.dt_util.now` with `side_effect=[day1, day2]`; read `native_value` then `extra_state_attributes` | `native_value` = day1 09:00; attributes `{end: day1 10:00, lessons_today: 1, lesson_id: "1", …}`; `now` call count = **0** | **FIXED** |
| S4-P2 | Properties must not consult `now()` at all | `mock_now.call_count == 0` across both reads | **FIXED** |
| S4-P3 | Coordinator update with a fresh `now` = day2 (schedule holds a day1 and a day2 lesson) | State and attributes switch to the day2 08:00 lesson (`lessons_today: 1`) | Correct |
| S4-P4 | Coordinator update after `coordinator.data = None` | `native_value` and attributes both reset to `None` | Correct |
| S4-P5 | No-regression sweep: earliest-of-today (unsorted), attributes, `last_update_success = False` availability | Earliest selected; attributes correct; `available is False` | Correct |

Under the **old** implementation, S4-P1 produced `native_value = day1 09:00`
while `extra_state_attributes = None` (the state and attributes disagreed).
The fix makes both reads use the same snapshot, so a local-midnight rollover
between the two reads can no longer desync them.

The engineer's regression test `test_state_and_attributes_use_a_single_now`
covers the single-`now` behaviour. The tester added
`test_coordinator_update_rolls_over_to_the_new_day`, which the engineer's
`test_coordinator_update_recomputes_the_first_lesson` did **not** cover: that
test swaps the schedule within the same day, whereas the new test proves the
override re-derives the **day** from a fresh `now`. No new gap was introduced by
the fix; the whole suite (including all prior N/S findings' tests) is green.

---

## First-lesson sensor verification (v0.6.0)

Every requested scenario was reproduced from the production code and the
passing suite, not from test names alone. The S4 rows were additionally probed
with a temporary script that was removed after the run (see
[S4 re-verification](#s4-re-verification-single-now-for-state-and-attributes)).

| Required scenario | Test(s) / probe | Verdict |
|-------------------|-----------------|---------|
| Earliest of today selected from multiple lessons (unsorted input) | `test_first_lesson_state_and_attributes` | PASS |
| A lesson that already started/finished is still returned | `test_lesson_already_started_is_still_returned` (start = local midnight) | PASS |
| No lessons today — only tomorrow | `test_no_lessons_today_returns_none` | PASS |
| No lessons today — only yesterday | `test_only_yesterday_lesson_returns_none` | PASS |
| Empty schedule (data present, list empty) | `test_empty_schedule_returns_none` | PASS |
| `coordinator.data is None` | `test_without_snapshot_returns_none` | PASS |
| Timezone `+02:00` → same instant, no raise | `test_aware_plus_two_lesson_yields_same_instant` | PASS |
| Timezone `Z` (UTC) → same instant, no raise | `test_z_suffix_lesson_yields_same_instant` | PASS |
| Timezone naive (offset-less) → normalised, no raise | `test_naive_lesson_is_handled` | PASS |
| `native_value` is a timezone-aware `datetime` (TIMESTAMP contract) | `test_z_suffix_lesson_yields_same_instant` (`isinstance`), `test_aware_plus_two_…` (`tzinfo`) | PASS |
| `lessons_today` count (only today's lessons) | `test_first_lesson_state_and_attributes` (2 today, 1 tomorrow), `test_missing_attributes_are_omitted` (1) | PASS |
| Missing lesson fields omitted from attributes | `test_missing_attributes_are_omitted` | PASS |
| `device_class`, unique id, device info | `test_first_lesson_entity_metadata` | PASS |
| Entity name loads from the translation key in EN/NL | `test_first_lesson_name_translations` | PASS |
| Translation key parity (`strings.json` / EN / NL) | `test_translation_files_have_matching_keys` | PASS |
| Unavailable after a failed coordinator update | `test_unavailable_when_update_failed`, probe S4-P5 | PASS |
| Lesson crossing midnight (starts 23:30 today, ends tomorrow) counts for its start day | `test_lesson_crossing_midnight_counts_for_its_start_day` | PASS |
| Lesson that started before local midnight is not counted for today | `test_lesson_started_yesterday_is_not_today` | PASS |
| Full platform setup renders a valid UTC ISO `TIMESTAMP` state + friendly name | `test_sensor_state_renders_after_setup` (integration) | PASS |
| **S4:** state and attributes share one `now` across a forced day rollover | `test_state_and_attributes_use_a_single_now`, probe S4-P1/P2 | **FIXED** |
| Coordinator update recomputes the first lesson from the new schedule | `test_coordinator_update_recomputes_the_first_lesson` | PASS |
| Coordinator update re-derives the **day** from a fresh `now` | `test_coordinator_update_rolls_over_to_the_new_day` **(new)**, probe S4-P3 | PASS |
| DST spring-forward: lessons around the `02:00→03:00` jump keep their local date and instant | temporary probe (Europe/Amsterdam, 2026-03-29) | PASS |

---

## Test cases

### Component: sensor (`tests/test_sensor.py`, 19 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_first_lesson_state_and_attributes` | Earliest of today's lessons is the state; all attributes mapped; unsorted input handled | PASS |
| `test_no_lessons_today_returns_none` | Only other-day lessons → `None` state and attributes | PASS |
| `test_lesson_already_started_is_still_returned` | A lesson at/after its start is still today's first | PASS |
| `test_missing_attributes_are_omitted` | Unset `subject`/`room`/`teacher`/`lesson_id` omitted; `end` + count kept | PASS |
| `test_empty_schedule_returns_none` | Empty-but-present schedule is distinct from a missing snapshot | PASS |
| `test_only_yesterday_lesson_returns_none` | A lesson on a past day is not today's first | PASS |
| `test_lesson_crossing_midnight_counts_for_its_start_day` | Late-today lesson counts for today; `end` spills to tomorrow | PASS |
| `test_lesson_started_yesterday_is_not_today` | Day is derived from the lesson *start*; yesterday's spillover is excluded | PASS |
| `test_aware_plus_two_lesson_yields_same_instant` | `+02:00` offset keeps the instant and normalises local | PASS |
| `test_z_suffix_lesson_yields_same_instant` | UTC `Z` form keeps the instant; `native_value` is an aware `datetime` | PASS |
| `test_naive_lesson_is_handled` | Offset-less start/end normalised without raising | PASS |
| `test_without_snapshot_returns_none` | `coordinator.data is None` → `None` state and attributes | PASS |
| `test_first_lesson_entity_metadata` | `has_entity_name`, translation key, `TIMESTAMP`, unique id, device info | PASS |
| `test_first_lesson_name_translations` | Name loads from the key in EN and NL | PASS |
| `test_unavailable_when_update_failed` | `last_update_success = False` → `available is False` | PASS |
| `test_sensor_state_renders_after_setup` (integration) | Real platform setup serialises the `TIMESTAMP` to UTC ISO + friendly name | PASS |
| `test_state_and_attributes_use_a_single_now` (engineer, S4) | A day rollover between the two reads does not desync state/attributes | PASS |
| `test_coordinator_update_recomputes_the_first_lesson` (engineer) | A new snapshot recomputes the first lesson and count | PASS |
| `test_coordinator_update_rolls_over_to_the_new_day` **(new)** | A coordinator update with a fresh `now` re-derives the local day | PASS |

### Components carried over (approved v0.3.0 / v0.4.0 / v0.5.0 slices, unchanged)

| Component | Tests | Result |
|-----------|-------|--------|
| `tests/test_auth.py` — PKCE, code extraction, exchange, refresh, holder | 54 | PASS |
| `tests/test_models.py` — `Account`/`Student`/`SomTodayTokens`/`Lesson` | 56 | PASS |
| `tests/test_config_flow.py` — user/student/reauth/options/migration | 45 | PASS |
| `tests/test_api.py` — pagination, 401/403 mapping, error paths | 42 | PASS |
| `tests/test_coordinator.py` — polling, scoping, windows, error mapping, tokens | 22 | PASS |
| `tests/test_calendar.py` — `event`, `async_get_events`, cache/out-of-range | 15 | PASS |
| `tests/test_translations.py` — key parity + EN/NL config, calendar and sensor names | 4 | PASS |
| `tests/test_init.py` — setup/unload, retry, reauth, sensor platform forwarded | 4 | PASS |
| `tests/test_const.py` — composite unique id | 3 | PASS |
| `tests/test_manifest.py` — domain/version/`config_flow`/`iot_class` | 1 | PASS |

`tests/test_init.py` (engineer, v0.6.0) asserts both the `sensor` and `calendar`
platforms are forwarded/unloaded (the two entity ids are collected and asserted
`unavailable` after unload).

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
custom_components/sometoday/sensor.py           59      0   100%
--------------------------------------------------------------------------
TOTAL                                          994      0   100%
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
custom_components/sometoday/sensor.py           59      0     14      0   100%
----------------------------------------------------------------------------------------
TOTAL                                          994      0    248      4    99%
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
| `sensor.py` | 59 | 0 | 14 | 0 | 100% | 100% |
| **Total** | **994** | **0** | **248** | **4** | **100%** | **99%** |

The four remaining partial branches are the same pre-existing defensive guards
as in the v0.5.0 report, all unrelated to the sensor slice:

- `__init__.py:84->91` — `auth.tokens is None` guard.
- `api.py:370->373` — `response.headers` not a `Mapping` in `_log_error_summary`.
- `api.py:375->381` — response object without a `text` attribute.
- `auth.py:81->exit` — `_release()` on a response without `release`.

The v0.6.0 sensor slice (including the S4 fix) is at **100% line and 100%
branch**.

---

## Findings

### Fixed

| ID | Finding | Severity | Evidence | Status |
|----|---------|----------|----------|--------|
| **S4** | `native_value` and `extra_state_attributes` each called `dt_util.now()`, so a local-midnight rollover between the two reads could desync them (state = today's timestamp while attributes = `None`, or vice versa). | Info (self-corrected on the next poll) | One cached snapshot in `_refresh_derived(now)`; properties never call `now()` (probe call count 0); exact `side_effect=[day1, day2]` repro stays consistent; `_handle_coordinator_update` re-derives from a fresh `now`. Permanent tests: `test_state_and_attributes_use_a_single_now`, `test_coordinator_update_recomputes_the_first_lesson`, `test_coordinator_update_rolls_over_to_the_new_day`; probes S4-P1–S4-P5. | **FIXED** |

### New, non-blocking

| ID | Finding | Severity | Evidence | Status |
|----|---------|----------|----------|--------|
| **S5** | `_handle_coordinator_update` (`sensor.py:98`) overrides the base `CoordinatorEntity._handle_coordinator_update`, which is decorated with `@callback`, but the override was not decorated. | **Info** (HA style only; no functional impact). | Source inspection of `sensor.py` vs. `homeassistant.helpers.update_coordinator.CoordinatorEntity._handle_coordinator_update`. | **FIXED** — the override now carries `@callback`. |

### Verified not bugs

- **Cross-midnight lessons.** A lesson is assigned to the local date of its
  **start**, matching architecture §8.1. A 23:30→00:30 lesson counts for today;
  one that started yesterday does not. Both boundaries are pinned by tests.
- **DST / locale midnight.** A spring-forward probe (Europe/Amsterdam,
  2026-03-29) selected the correct earliest lesson and counted both lessons for
  the local date with no exception. `dt_util.now()` and `dt_util.as_local` both
  read the same `DEFAULT_TIME_ZONE`, so the day filter and normalisation agree.
- **Stale "now" between polls.** The snapshot is refreshed by
  `_handle_coordinator_update` on every successful poll (default every 15 min);
  the state is only written at those points anyway, so caching `now` does not
  add staleness beyond the normal poll interval.
- **`native_value` type.** `dt_util.as_local(...)` always returns a
  timezone-aware `datetime`; HA's `sensor` state property requires exactly that
  for `SensorDeviceClass.TIMESTAMP`. The integration test confirms the rendered
  state is a UTC ISO string.
- **`end` attribute type.** HA's `homeassistant.helpers.json.JSONEncoder`
  serialises `datetime` to `isoformat()`, so recorder/websocket export is safe.
- **Sensor created without data.** `async_config_entry_first_refresh()` runs
  before the platforms are forwarded; a failed first refresh aborts setup, so
  the entity is only created with a snapshot. On a later failed poll the
  `CoordinatorEntity` reports `available = False`.

### Carried over (unchanged by this slice)

- **Fixed and still green:** `B1` (frozen fetch window), `N1` (mixed naive/aware
  sort), `N2` (401/403 escalation), `N3` (cache-window drift), `N5` (reactive
  token rotation), `N7` (student-list auth rejection), `S1` (naive calendar
  datetimes), `N8` (read-only calendar assertion).
- **Open, non-blocking:** `N4` (out-of-range calendar fetches bypass coordinator
  error handling, Low), `N6` (out-of-range fetches not cached, Low/load),
  `S2`/`N11` (paginated items not de-duplicated, Info), `S3` (mixed naive/aware
  inverted interval, Info, unreachable with well-formed data), `N10` (link
  selection ignores `rel`, Info), and the carry-overs `T4`, `T6/R7`, `T7–T9`,
  `F2`, `F3`, `F4`. None affect the sensor slice.
- **N9 — documentation drift — still PARTIAL, OPEN (Info).** Residual drift
  after v0.6.0:
  - `docs/architecture.md:939` still says "Sensor/binary_sensor tests are still
    future work"; the sensor tests now exist (binary_sensor remains future).
  - `README.md:7-11` still says "Current status: authentication + schedule
    (v0.5.0)" and "There are no sensors yet"; v0.6.0 adds the sensor.
  - `docs/CHANGELOG.md:35` records "256 tests"; the suite is now 265 (test
    counts drift with every test change).
  The tester may not edit production/docs outside this report, so these need an
  owner amendment.

---

## Blockers

1. **Real-account validation is prohibited.** The live shape of
   `/rest/v1/afspraken` and whether a single-student account populates
   `additionalObjects.leerlingen` can only be confirmed against a real account.
   Tests use the documented and defensive shapes.
2. **Live confirmation of offset-less timestamps is impossible here.** The
   `+02:00`/`Z`/naive handling is defensive and covered by mocked probes and
   permanent tests.
3. **S5 (style) needs an owner decision.** Decorating the override with
   `@callback` is optional and non-functional; the tester did not change
   production code.

No test requires a production change to pass, and no test was removed or
weakened.

---

## Changes made by the tester (this run)

**No production code was modified.** The engineer fixed S4 and added two
regression tests; the tester independently re-verified S4 with a temporary
probe, added one test for a genuine gap, and updated this report.

| Action | Detail |
|--------|--------|
| `tests/test_sensor.py` +1 | `test_coordinator_update_rolls_over_to_the_new_day` — proves the overridden `_handle_coordinator_update` re-derives the local day from a fresh `now` (the engineer's test only swapped the schedule within the same day) |
| Probe (temporary, removed) | 5 scenarios S4-P1–S4-P5: exact day-rollover repro, "properties never call `now()`" call-count, coordinator-update rollover, snapshot cleared, no-regression sweep |
| Report rewritten | Summary, S4 re-verification matrix, sensor verification matrix, test cases, coverage, findings (S4 FIXED, new S5), blockers and verdict updated for the S4 fix |
| Production code | untouched |
| Tests removed | none |

### Test-quality assessment and gate

| Criterion | Result |
|-----------|--------|
| Minimum 80% coverage | **Met** — 100% line, 99% branch; `sensor.py` 100% line/branch |
| All tests pass | **Met** — 265 passed, 0 failed, 0 xfailed, 0 skipped |
| Error scenarios tested | **Met** — unavailable on coordinator failure, no-snapshot, empty schedule, naive/`Z`/offset datetimes, missing attributes, cross-midnight and DST boundaries, forced day rollover |
| No production code modified | **Met** |
| No test removed or weakened | **Met** — 1 test added by the tester (plus the engineer's 2) |

**Final verdict:** the v0.6.0 `first_lesson_of_today` sensor slice is
independently validated and **finding S4 is genuinely fixed**. The state and
attributes are now derived from one cached "now" (`_refresh_derived`), refreshed
by `__init__` and by the overridden `_handle_coordinator_update`; the properties
no longer call `dt_util.now()`. The exact original repro (forced day rollover
between the two reads) stays consistent, and a coordinator update with a fresh
`now` correctly re-derives the local day. No behavioural regression was found:
earliest-of-today selection, attributes, `+02:00`/`Z`/naive handling, metadata
and availability all remain green. `sensor.py` is at **100% line and 100%
branch**, the whole integration at **100% line / 99% branch**, with **265/265
tests passing and zero xfails/skips**. The only new item is **S5** (Info, HA
style): the override is not decorated with `@callback`; no functional impact.
The carried-over `N4`/`N6`/`S2`/`S3`/`N10`/`N11` and `N9` documentation drift
remain non-blocking. **The 80% gate is met with room to spare.**
