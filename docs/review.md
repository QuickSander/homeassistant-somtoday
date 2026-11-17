# Review — SomToday v0.8.1 grade-endpoint fix

> Reviewer: reviewer-agent (per `AGENTS.md`).
> Date: 2026-11-17.
> Scope: commit `2a6f185` (**v0.8.1**) plus the tester's uncommitted additions —
> `api.py` (`GRADES_PATH`, `EXAM_GRADES_PATH`, `LEGACY_GRADES_PATH`,
> `GRADE_TYPES`, `GRADE_ADDITIONALS`, `GRADE_SORT`, `async_get_grades`,
> `_grade_params`), `models.py` (`_strip_not_made`, `Grade.imported`,
> `Grade.from_api`), `sensor.py` (`_valid_grades` imported filter),
> `manifest.json` 0.8.1, `docs/architecture.md`, `docs/CHANGELOG.md`,
> `README.md`, `docs/test-report.md`, and the tests in
> `tests/{test_api,test_models,test_sensor}.py`.
> Sources of truth: `docs/architecture.md` §5/§5.1/§7.2/§7.3/§8.1/§13,
> `docs/CHANGELOG.md`, `docs/test-report.md`, and the upstream
> `elisaado/somtoday-api-docs` payload for
> `GET /rest/v1/resultaten/huidigVoorLeerling/{id}`.
> Method: independent re-read of every in-scope file; independent re-run of the
> suite, coverage and lint; read-through of the upstream grade payload. **No
> production code or test was modified. No real SomToday API call was made.
> Nothing was committed.**

## Summary

**Verdict: approve with non-blocking follow-ups.** The v0.8.1 fix is correct
for the stated endpoint selection rule (dossier primary, legacy only on HTTP
404, exam only when voortgang is empty), the legacy parser is preserved and the
new shapes are parsed defensively. **0 blocking issues, 8 non-blocking
findings** (three medium, five low). Release is safe; the medium findings are
worth verifying against a real exam-year payload before the next grade change
(N2, N3, N4).

Commands reproduced independently:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch \
  --cov-report=term-missing
$V/python -m ruff check custom_components tests
```

Observed: **328 passed, 0 failed, 0 xfailed, 0 skipped**; line coverage
**100%** (1242 statements, 0 missed); branch coverage **99%** (334 branches, 10
partial, all pre-existing diagnostic guards); `models.py` 100% line/branch,
`api.py` 100% line / 99% branch, `sensor.py` 100% line / 97% branch. `ruff`
reports **9 issues, all pre-existing and all in `tests/`** (6 × `RUF100`,
2 × `UP017`, 1 × `FURB162`); **no production-code findings**. The uncommitted
`docs/test-report.md` figures (328 tests, 100% line, 9 ruff findings) match this
run.

## Follow-up (v0.8.2)

The medium findings and N1/N5 were addressed after this review; the review text
above is kept as the original record.

| ID | Status | Resolution |
|----|--------|------------|
| N1 | Fixed | `SomTodayApiError` now carries a `status`; the grades fallback checks `err.status == 404` instead of matching `"HTTP 404"` in the message. |
| N2 | Mitigated | The shared query matches the official app's request for both dossiers; a realistic exam-dossier row is now exercised in `test_get_grades_uses_exam_dossier_when_voortgang_is_empty`. Still worth a real exam-year payload check. |
| N3 | Fixed | `_split_not_made` strips `"!"`/`" !"` and surfaces the signal; `not_made` is set even when `bijzonderheid` is absent. |
| N4 | Fixed | `_async_get_grades` also catches `TypeError`/`ValueError`, so a malformed grade payload keeps the previous snapshot; covered by a coordinator test. |
| N5 | Fixed | `_is_present` treats only a non-empty mapping/sequence (or non-empty scalar) as an imported result. |
| N6 | Open (low) | Capture a real current-shape payload as a fixture when available. |
| N7 | Open (low) | Only HTTP 404 triggers the legacy fallback, per the stated requirement. |
| N8 | Open (low) | Verify with exam-year data whether an imported-only row needs merging. |

## Blocking issues

None.

## Non-blocking findings

| ID | Severity | Finding | Location | Recommendation |
|----|----------|---------|----------|----------------|
| N1 | Low | The legacy fallback keys off the literal substring `"HTTP 404"` in `str(err)`. It works today because `_async_decode` formats that exact text, but any future message change silently disables the fallback and grades stay unknown on legacy schools. | `api.py:211-221` | Carry the status as data, not text: add `status` to `SomTodayApiError` (set in `_async_decode`) or add a `SomTodayNotFoundError` subclass and catch that. This also makes the 403/429/5xx branches explicit. |
| N2 | Medium | The exam fallback reuses the voortgang query (`type=Toetskolom,DeeltoetsKolom,Werkstukcijferkolom,Advieskolom`, the same `additional`s and `sort=desc-geldendResultaatCijferInvoer`). Exam-dossier columns can use other `type`/sort fields, in which case the server can return an empty list and the fallback (the reason for reading the exam dossier) never yields a grade. The test only asserts that the request is made with those params, not that real exam rows pass the filter. | `api.py:226-239`, `tests/test_api.py:907-925` | Verify with a real exam-year response. If exam column types differ, use exam-specific `GRADE_TYPES`/`sort` (or omit `type`/`sort` for the exam endpoint) and add a fixture with actual exam rows. |
| N3 | Medium | `_strip_not_made` removes the `" !"` postfix from `formattedResultaat` but discards the signal. If `bijzonderheid` is absent (only the display value carries the marker), a result the portal flags as not made/no-count is parsed as a normal value and counted. Only the exact `" !"` suffix is handled (`"7,5!"` fails to parse), and the test asserts the value without asserting `not_made`/`counts`. | `models.py:209-213, 426, 436-443` | Confirm what `"!"` means in the current app. If it means not made / not counting, set `not_made`/`counts` from it instead of dropping it; tolerate `"!"` with or without the space and add assertions for both flags. |
| N4 | Medium | The "grades failure is non-fatal" guarantee is incomplete. `parse_grades` raises `TypeError` for an unexpected payload (e.g. `items` is not a list), and `_async_get_grades` only catches `SomTodayError`/`aiohttp.ClientError`. A malformed grade payload from the new endpoint would propagate and fail the whole coordinator poll, taking the schedule/calendar unavailable. | `coordinator.py:197-206`, `models.py:482-497` | Catch `(SomTodayError, aiohttp.ClientError, TypeError, ValueError)` around the grades fetch (or wrap the parse in `api.py`) and keep the previous snapshot, as the docstring already promises. Add a coordinator test with a malformed `items` value. |
| N5 | Low | `imported=bool(payload.get("resultaatAnderVakKolom"))` uses truthiness, while the architecture says "is present". A non-empty non-mapping truthy value (e.g. the string `"false"`) would mark a normal grade imported; an empty container is correctly not imported. | `models.py:461`, `docs/architecture.md:676` | Use an explicit check (`isinstance(value, Mapping) and bool(value)`, or `value not in (None, "", [], {})`) and add tests for `{}`/`[]`/`False`. Keep the docs wording in sync. |
| N6 | Low | The current dossier shape is **not documented upstream**: `somtoday-api-docs` only documents `resultaat`, `geldendResultaat`, `datumInvoer`, `teltNietmee`, `toetsNietGemaakt`, `type` and `vak`. The new fields (`cijfer`, `formattedResultaat`, `bijzonderheid`, `resultaatAnderVakKolom`, `additionalObjects.vaknaam`) are validated only against hand-written fixtures. Also, `type` is read only from the top level; when the app asks for `additional=resultaatkolom`, the column type may live under `additionalObjects.resultaatkolom`, leaving `latest_grade`'s `type` attribute empty for the current shape. | `models.py:408-462`, `tests/test_models.py:694-708` | Capture a sanitised real payload as a fixture and cite its source in `architecture.md`. If `type` is nested in the real shape, read `additionalObjects.resultaatkolom.type` as a fallback (or document that `type` is absent on the current endpoint). |
| N7 | Low | Only HTTP 404 selects the legacy endpoint. A 400/405/422 caused by an unsupported `sort`/`type`/`additional` query at a school surfaces as a (non-fatal) grades error and never tries the legacy path, so those users keep stale/unknown grades even though the legacy endpoint works. This is consistent with the stated requirement; it is only a compatibility caveat. | `api.py:211-221` | If the real app/portal is known to reject queries at some schools, also treat the verified "unsupported query" statuses as fallback triggers. Do not include 401/403/429. |
| N8 | Low | Dropping imported rows can hide an exam/SE grade that only appears as an imported column in a non-empty voortgang dossier, because the exam dossier is then not read. The dedupe intent is sound, but the completeness guarantee depends on the original row also existing in the voortgang dossier. | `sensor.py:69-77`, `api.py:223-229` | Verify with exam-year data; if the only row is imported, read the exam dossier and merge/dedupe by id/subject instead of unconditionally dropping imported rows. |

## Security

Pass. The new code adds no secrets and no token logging. The bearer token is
only placed in the request headers in `_build_headers`; the new debug message
(`api.py:214-217`) contains only the endpoint name, and the exception messages
contain only the method/path and student id. `_log_error_summary` remains
unchanged, is debug-only and bounded, and logs response status/metadata rather
than request headers, so the token cannot leak through it. No credentials or
grade data are written to the log in normal operation.

## Home Assistant best practices

- **Coordinator error mapping** is correct: `SomtodayInvalidAuth` →
  `ConfigEntryAuthFailed`, other `SomTodayError`/network errors → `UpdateFailed`
  (N4 is the one gap, in the secondary-data path).
- **Grades are non-fatal** in the intended path: 403/5xx on grades keep the
  previous snapshot and leave the schedule/calendar available; the old
  `enable_grades` opt-out is unchanged.
- **Sensor filtering** is consistent across `average_grade`, `latest_grade` and
  `grades_count`: all three use `_valid_grades`, which now also excludes
  imported rows. Filtering semantics are documented in §8.1 and the README.
- **Pagination** reuses the proven `Range: items=…` walker; 200 (whole list) and
  206 (partial) are both handled.

## Parser robustness and regression risk

- The legacy shape still parses: `resultaat`, `geldendResultaat`, `datumInvoer`,
  `teltNietmee`, `toetsNietGemaakt`, top-level `vak` and `*GemiddeldeKolom`
  filtering are unchanged, and all legacy tests pass. Legacy users are only
  affected by one extra 404 request per poll before the fallback; no data
  regression was observed.
- The current shape is parsed defensively: numeric `cijfer`, a decimal-comma
  `formattedResultaat` fallback, `additionalObjects.vaknaam`,
  case-insensitive `bijzonderheid`, `resultaatAnderVakKolom`, and the
  first-attempt/retake date fallbacks are all covered.
- The main residual parser risks are N3 (the `"!"` marker), N6 (the current
  shape is only fixture-validated and `type` may be nested) and N2 (exam rows
  may not match the voortgang type filter).

## Documentation check

- `README.md` status is **v0.8.1** and the grades section describes the
  `TeltNietMee`/imported exclusions. Consistent with the code.
- `docs/CHANGELOG.md` has a complete `[0.8.1] - 2026-11-17` entry that matches
  the commit (endpoint change, fallbacks, parser fields, imported filter, docs
  and tests). `manifest.json` is **0.8.1**, matching the README and CHANGELOG.
- `docs/architecture.md` updates §5, §7.2, §7.3, §8.1 and §13 consistently with
  the implementation; the endpoint table lists primary, exam and legacy paths
  correctly.
- `docs/test-report.md` (uncommitted) matches the reproduced run (328 passed,
  100% line, 9 pre-existing ruff findings) and documents the new cases.
- Minor stale references (not blocking): `architecture.md:457` still says the
  grades slice was implemented in v0.8.0 (the endpoint changed in v0.8.1), and
  the illustrative `manifest.json` in `architecture.md:938` still shows
  `"version": "0.7.2"`. Neither affects runtime.

## Verdict

**Approve — with non-blocking follow-ups.** No blocking issues. The endpoint
selection, fallbacks, parser compatibility and legacy regression behaviour match
the requirement and are backed by 328 passing tests. Before the next grade
change, verify N2 (exam query) and N3 (`"!"` semantics) against a real
exam-year payload, and prefer structured 404 detection (N1) over substring
matching.

---

# Historical review — SomToday v0.8.0 grades slice

> Reviewer: reviewer-agent (per `AGENTS.md`).
> Date: 2026-09-13.
> Scope: the **v0.8.0 grades slice** — `models.py` (`Grade`, `_as_float`,
> `parse_grade(s)`), `api.py` (`async_get_grades`, `GRADES_PATH`),
> `coordinator.py` (`SomTodayData.grades`, `_async_get_grades`,
> `enable_grades`), `sensor.py` (the three grade sensors),
> `manifest.json` 0.8.0, `strings.json` + `translations/{en,nl}.json`, and the
> new tests in `tests/{test_models,test_api,test_coordinator,test_sensor}.py`.
> The previously approved v0.3.0 (auth), v0.4.0 (identity) and v0.5.0/v0.6.0/
> v0.7.0 slices are re-run but not re-reviewed in depth.
> Sources of truth: `docs/architecture.md` §2/§5/§6/§7.2/§7.3/§8.1/§13 and
> `docs/test-report.md`.
> Method: independent re-read of every in-scope file; independent re-run of the
> suite, coverage and lint; source inspection of the installed Home Assistant
> 2026.9.1 framework; and a read-through of the upstream
> `somtoday-api-docs` payload for
> `GET /rest/v1/resultaten/huidigVoorLeerling/{id}`. **No production code was
> modified. No real SomToday API call was made.**

Commands reproduced independently:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch \
  --cov-report=term-missing
$V/python -m ruff check custom_components tests
```

Observed: **313 passed, 0 failed, 0 xfailed, 0 skipped**; line coverage **100%**
(1199 statements, 0 missed); branch coverage **99%** (318 branches, 10 partial,
all pre-existing diagnostic guards); `models.py`, `coordinator.py` 100% line/
branch; `sensor.py` 100% line / 97% branch; `ruff` **clean** (exit 0).

## Verdict

**Approve — ready to tag/release.**

- **Requirements met.** The two explicit requirements are implemented and
  tested: the average is broken down **per subject** (`average_grade`'s
  `averages: {subject: mean}` attribute) and `latest_grade` reports the
  **subject** it was for (`subject`/`subject_abbr` attributes).
- **Correctness.** SomToday's own average columns (`*GemiddeldeKolom`),
  `teltNietmee`, `toetsNietGemaakt` and non-numeric grades (`"V"`, `""`) are all
  excluded before averaging, so the integration never averages averages. Subject
  parsing tolerates both the top-level `vak` and the nested
  `additionalObjects.vak` shape.
- **Resilience.** The grades fetch is non-fatal: a `SomTodayError`/network
  error (e.g. HTTP 403 without grade permission) keeps the previous snapshot and
  leaves the schedule/calendar available; a `SomtodayInvalidAuth` still
  escalates to reauth. The `enable_grades` option is honoured.
- **Security.** No new secrets; only the bearer token already in use. No grade
  data is logged.
- **No blocking issues.** Non-blocking observations only: the `sensor.py`
  branch coverage is 97% (defensive `value is None` guards, line coverage 100%),
  and `new_grade` remains explicitly deferred to the `binary_sensor` slice
  (§8.2).

---

# Historical review — v0.6.0 `first_lesson_of_today` sensor slice

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
