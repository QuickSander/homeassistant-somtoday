# Review — SomToday v0.6.0 `first_lesson_of_today` sensor slice

> Reviewer: reviewer-agent (per `AGENTS.md`).
> Date: 2026-09-12.
> Scope: the **v0.6.0 `first_lesson_of_today` sensor slice** —
> `custom_components/sometoday/sensor.py` (new), the `PLATFORMS` change in
> `__init__.py`, `manifest.json` 0.6.0, `strings.json` +
> `translations/{en,nl}.json`, `tests/test_sensor.py` (new) and
> `tests/test_init.py`. The previously approved v0.3.0 (auth), v0.4.0
> (identity) and v0.5.0 (schedule/calendar) slices were re-run but not
> re-reviewed in depth; the only thing this slice touches outside the sensor is
> the platform list, which was checked directly.
> Sources of truth: `docs/architecture.md` §8/§8.1 (and §2, §9, §11, §13) and
> `docs/test-report.md`.
> Method: independent re-read of every in-scope file; independent re-run of the
> suite, coverage and lint; source inspection of the installed Home Assistant
> 2026.9.1 framework (`as_local`, `now`, `CoordinatorEntity`); and a throw-away
> timezone/DST probe in the temp directory (since removed). **No production code
> was modified. No real SomToday API call was made.**

Commands reproduced independently:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch \
  --cov-report=term-missing
$V/python -m ruff check custom_components tests
```

Observed: **265 passed, 0 failed, 0 xfailed, 0 skipped**; line coverage **100%**
(994 statements, 0 missed); branch coverage **99%** (248 branches, 4 partial,
all pre-existing diagnostic guards); `sensor.py` **100% line / 100% branch**
(59 statements, 14 branches); `ruff` **clean** (exit 0). Test counts per file
match `docs/test-report.md` (`test_sensor.py` 19, `test_init.py` 4).

> Small discrepancy vs. the report: `docs/test-report.md` records
> `sensor.py` as **58** statements and the total as **993**, while the current
> tree measures **59** / **994**. The one extra statement is the `@callback`
> decorator line that now sits on `_handle_coordinator_update` (S5 fix); see the
> adjudication below. Documentation drift only — no runtime impact.

---

## Summary

**The slice is ready to tag/release. There are no blocking issues.** The sensor
implements exactly what architecture §8.1 specifies, and it meets the user's
alarm-automation goal for well-formed SomToday data under the default 15-minute
poll interval.

Verified from the production code and the HA framework source (not from test
names alone):

- **State is the correct instant.** `native_value` returns
  `dt_util.as_local(self._first_lesson.start)`, where `_first_lesson` is the
  `min` by start time of the lessons whose **local start date** equals today's
  local date. Past/ongoing lessons are included, so a lesson that already
  started is still returned (architecture §8.1; `test_lesson_already_started_is_still_returned`).
- **Awareness / TIMESTAMP contract.** `dt_util.as_local` always returns a
  timezone-aware `datetime` (confirmed in the installed
  `homeassistant.util.dt.as_local`); a naive input is first given the default
  HA timezone and then converted. The full-setup test confirms HA serialises
  the value as a UTC ISO string with `device_class: timestamp`.
- **Timezone and DST.** Independent probe (Europe/Amsterdam) confirmed:
  a `Z`/UTC start that lands on the **next** local calendar day is selected for
  that local day (00:30 local beats a 09:00 local lesson); spring-forward
  (2026-03-29, 01:30 `+01:00` vs 03:30 `+02:00`) selects the correct earliest
  lesson with the correct count; fall-back ambiguous `02:30` keeps an aware
  value. `dt_util.now()` and `dt_util.as_local` share `DEFAULT_TIME_ZONE`, so
  the day filter and the normalisation always agree.
- **Day rollover.** `_handle_coordinator_update` re-derives from a fresh
  `dt_util.now()` before delegating to `super()` (which writes the state), so a
  poll after local midnight moves the state to the new day's first lesson
  (`test_coordinator_update_rolls_over_to_the_new_day`; independent probe).
- **Cross-midnight.** The day is taken from the lesson's **start**; a
  23:30→00:30 lesson counts for today, a lesson that started before midnight
  does not. Both boundaries are pinned by permanent tests.
- **S4 is genuinely fixed.** `_refresh_derived(now)` computes `_first_lesson`
  and `_today_lessons` from one `now`; `native_value` and
  `extra_state_attributes` only read the cached fields and never call `now()`
  (framework/source confirmed; `test_state_and_attributes_use_a_single_now`).
- **S5 is fixed in code.** The override carries `@callback` at `sensor.py:98`,
  matching `CoordinatorEntity._handle_coordinator_update`. The tester's report
  still lists it as OPEN (stale; see adjudication).

---

## Blocking issues

**None.** Nothing found blocks the alarm-automation goal:

- The state is the correct local instant, aware, and DST-safe.
- It stays correct across days within one poll interval (default 15 min).
- `None` (rendered `unknown`) is returned when there is no lesson today, and
  `unavailable` when the coordinator fails, so an automation can distinguish
  "free day" from "integration down".
- Platform setup/unload is generic and the sensor is created only after
  `async_config_entry_first_refresh()` succeeds, so no entity exists without a
  snapshot.

---

## Non-blocking findings

New findings from this review use the `R` prefix to avoid colliding with the
carried-over `F2`/`F3`/`F4` IDs.

| ID | Severity | Finding | Evidence / recommendation |
|----|----------|---------|---------------------------|
| **R1** | Low | **Midnight staleness bounded by the poll interval.** `_first_lesson` is only recomputed in `__init__` and `_handle_coordinator_update`, so for up to `scan_interval` after local midnight the sensor still reports the previous day's first lesson. Under the default 15 min this is negligible for a morning alarm, but a large `scan_interval` (up to 1440) widens the window. | `sensor.py:66,98-105,108-133`. Recommendation (next slice or docs): schedule a `async_track_time_change` refresh at local midnight, or document that the sensor refreshes on the coordinator poll. Not blocking at the default interval. |
| **R2** | Info | **No permanent DST regression test.** DST was only validated by a temporary tester probe and my throw-away probe; the suite runs under `US/Pacific` and never sets a DST-transition timezone. | `docs/test-report.md:139`; `tests/test_sensor.py`. Recommendation: add a test that sets `dt_util.set_default_time_zone(ZoneInfo("Europe/Amsterdam"))` around a transition. Non-blocking; behaviour is correct. |
| **R3** | Info | **`lessons_today` is absent when there is no lesson today.** `extra_state_attributes` returns `None` if `_first_lesson is None`, so a "free day" exposes no count. | `sensor.py:79-80`. State is `unknown` and availability is `True`, so it is distinguishable from `unavailable`; exposing `lessons_today: 0` would be friendlier for templates. UX only. |
| **R4** | Info | **README does not document the sensor's attributes or give an alarm example.** It mentions the sensor but not `subject`/`room`/`teacher`/`end`/`lesson_id`/`lessons_today`, nor the fact that the state stays in the past after the lesson starts. | `README.md:7-12`; `docs/architecture.md:713-717` has the detail. Recommendation: add a short attribute table + template/automation example. Documentation completeness only. |
| **R5** | Info | **Documentation drift.** `docs/architecture.md:117` still says "Platforms: `calendar` (implemented); `sensor`, `binary_sensor` (later)" although `sensor` is now implemented; `docs/test-report.md:272,332-333,375-376` still says **S5 OPEN** and its coverage table says `sensor.py` 58 / total 993. | Independent grep + coverage run. The code and `CHANGELOG` are correct; the report predates the S5 fix. Owner amendment only. |

### Carried-over, still non-blocking (unchanged by this slice)

All confirmed still present; none affects the sensor and none blocks the release.

- **N4 (Low)** — out-of-range calendar fetches can raise `SomtodayInvalidAuth`/
  `SomTodayError` past HA's `CalendarEntity` error handling. Recommendation
  unchanged: map in a coordinator helper or return `[]`.
- **N6 (Low)** — out-of-range calendar ranges are not cached; each call issues a
  fresh paginated request.
- **N5 residual (Low)** — a token rotation followed by a failed poll is not
  persisted until the next success.
- **S2 / N11 (Info)** — pages are not de-duplicated; the `Content-Range` `start`
  is ignored.
- **S3 (Info)** — a mixed naive/aware inverted interval could raise; unreachable
  with well-formed data (N1 fixed the reachable case).
- **N10 (Info)** — `models._first_link_id` takes the first link regardless of
  `rel`; confirm against a live payload.
- **T4, T6/R7, T7–T9, F2, F3, F4** — the v0.3.0/v0.4.0 carry-overs
  (`/account/me` scope, forced-refresh dedup, paste edge cases, un-reauthable
  migrated entry, unused `wrong_account` key, `include_ignore=True`). Unchanged,
  non-blocking.

---

## Security assessment

| Area | Result | Notes |
|------|--------|-------|
| Sensor data exposure | **Pass** | Only `subject`, `room`, `teacher` (abbreviations), `end`, `lesson_id`, `lessons_today`. No student ids, tokens, or account data. |
| Secrets in logs | **Pass** | The sensor adds no logging; the auth/API slice is unchanged from the approved reviews. |
| Refresh-token storage | **Pass with caveat** | Plaintext in `.storage/core.config_entries` (documented HA limitation); unchanged. |
| Per-student isolation | **Pass with caveat** | The sensor reads only `entry.runtime_data.coordinator.data.schedule`, which is already client-side scoped to the entry's student. The documented multi-student trade-off (architecture §7.2.1) is unchanged. |
| Response parsing | **Pass** | `Lesson` is a frozen dataclass; the sensor performs no parsing or deserialisation. |
| Read-only | **Pass** | The sensor has no write path and no service registration. |
| Dependencies / network | **Pass** | Empty `requirements`, HA shared session, all HTTP mocked in tests; no real API call in this review. |

No security-blocking issue found.

---

## Home Assistant best-practices assessment

| Practice | Result | Notes |
|----------|--------|-------|
| `SensorEntity` + `TIMESTAMP` | **Pass** | `_attr_device_class = SensorDeviceClass.TIMESTAMP`, no `state_class`, `native_value` is an aware `datetime` or `None`. Framework `as_local` guarantees awareness. |
| `CoordinatorEntity` availability | **Pass** | Inherited `available` follows `last_update_success`; `test_unavailable_when_update_failed`. |
| `@callback` on update handler | **Pass** | Present at `sensor.py:98`, matching the base class. Fixes tester S5. |
| `has_entity_name` / translation / unique id / device info | **Pass** | `_attr_has_entity_name` inherited; `_attr_translation_key = "first_lesson_of_today"`; `f"{entry.entry_id}_first_lesson_of_today"`; shared `DeviceInfo` via `SomTodayEntity`. EN/NL keys load. |
| Platform setup extensibility | **Pass** | `ENTITY_CONSTRUCTORS` tuple + `async_setup_entry`; adding the remaining §8.1 sensors does not touch setup. |
| Forward/unload | **Pass** | `PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]`, `async_forward_entry_setups` / `async_unload_platforms`; `test_unload_entry_unloads_platforms` asserts both go `unavailable`. |
| First refresh ordering | **Pass** | Platforms are forwarded only after `async_config_entry_first_refresh()` succeeds; entities are never created without a snapshot. |
| State/attribute consistency | **Pass** | Single `now` per update (S4); properties are pure reads. |
| Test isolation | **Pass** | All HTTP mocked (`MagicMock`/`patch`); no marker skips; `ruff` clean. |

---

## Tester-findings adjudication

| ID | Tester claim | My adjudication | Status |
|----|--------------|-----------------|--------|
| **S4** | Fixed: state/attributes from a single `now` | Confirmed from source: `_refresh_derived` caches both fields; `native_value`/`extra_state_attributes` never call `now()`; `_handle_coordinator_update` re-derives before `super()`. Tests + independent probe agree. | **Fixed** |
| **S5** | `_handle_coordinator_update` override lacks `@callback` (OPEN — style) | **Now fixed in code**: `sensor.py:98` carries `@callback`. The report is stale and should be updated; the +1 coverage statement vs. the report is exactly this decorator. | **Fixed (report stale)** |
| **N9** | Documentation drift | Substantially closed: README status, architecture §13 sensor-tests text, §9 `PLATFORMS` comment, §11 tree, manifest example and the class-model "future work" comments are all corrected. Remaining: architecture §2 line 117 and the stale test-report items (R5). | **Substantially closed** |
| **N4** | Out-of-range calendar fetch errors | Agree, Low, unchanged, unrelated to the sensor. | Open, non-blocking |
| **N6** | Out-of-range ranges not cached | Agree, Low, unchanged. | Open, non-blocking |
| **S2 / N11** | Pages not de-duplicated | Agree, Info; `Content-Range` `start` also ignored. | Open, non-blocking |
| **S3** | Inverted mixed interval can raise | Agree, Info, unreachable with well-formed data. | Open, non-blocking |
| **N10** | Link selection ignores `rel` | Agree, Info, needs live confirmation. | Open, non-blocking |
| **T4, T6/R7, T7–T9, F2, F3, F4** | Various low/info | Agree, all non-blocking and unchanged. | Open, non-blocking |
| Counts / coverage / lint | 265 passed, 100% line / 99% branch, ruff clean | Reproduced exactly (`sensor.py` 100%/100%). Only the report's `sensor.py`/total statement counts are off by one (R5). | Verified |
| DST / timezone | Probe-verified | Independently re-probed (Z cross-local-midnight, day rollover, spring-forward, fall-back). All correct. | Verified |

---

## Final verdict

**Approve — ready to tag/release.**

- **No blocking issues.** The sensor state is the correct local instant for the
  alarm use case (today's earliest lesson, past lessons included), it is
  timezone-aware, DST-safe, and correct across days within one poll interval.
- **Confirmed fixed:** **S4** (single `now`) and **S5** (`@callback`); **N9**
  substantially closed.
- **New non-blocking findings:** **R1** (midnight staleness bounded by the poll
  interval), **R2** (no permanent DST test), **R3** (`lessons_today` absent on a
  free day), **R4** (README lacks sensor/attribute docs and an alarm example),
  **R5** (architecture §2 line 117 + stale test-report S5/coverage).
- **Remaining carry-overs:** **N4**, **N6**, the **N5** failed-poll residual,
  **S2/N11**, **S3**, **N10**, and **T4**, **T6/R7**, **T7–T9**, **F2**, **F3**,
  **F4** — all unchanged and non-blocking.
- **Security:** no security-blocking issue.
- **Tests:** 265/265 pass, 0 xfailed/skipped, 100% line / 99% branch, `ruff`
  clean — independently reproduced, plus an independent timezone/DST probe.

The v0.6.0 `first_lesson_of_today` sensor delivers the user's alarm-automation
goal and can be tagged/released. The `R` items are documentation/robustness
follow-ups worth scheduling for the next slice; none gates this release.

### Changes made by this review

- `docs/review.md` rewritten for the v0.6.0 `first_lesson_of_today` sensor state.
- **No production code was modified.** The only probe was a throw-away script in
  the temp directory (since removed).
