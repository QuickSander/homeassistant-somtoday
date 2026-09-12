# Review — SomToday v0.5.0 schedule slice (final state)

> Reviewer: reviewer-agent (per `AGENTS.md`).
> Date: 2026-09-12.
> Scope: the **v0.5.0 schedule data slice** after the B1 fix and the N1–N9
> follow-ups — `custom_components/sometoday/{coordinator,entity,calendar,api,models,__init__}.py`,
> `manifest.json` 0.5.0, `strings.json` + `translations/{en,nl}.json`, and the
> docs. The previously approved v0.3.0 (auth) and v0.4.0 (identity) slices were
> re-run but not re-reviewed in depth.
> Sources of truth: `docs/architecture.md` (§5, §5.1, §6, §7.2/§7.2.1, §8.3) and
> `docs/test-report.md`.
> Method: independent re-read of every in-scope file; re-run of the suite,
> coverage and lint; source inspection of the installed Home Assistant 2026.9.1
> framework; a throw-away multi-day probe of the coordinator fetch/cache window
> and the calendar out-of-cache boundary (since removed). **No production code
> was modified. No real SomToday API call was made.**

Commands reproduced independently:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch \
  --cov-report=term-missing
$V/python -m ruff check custom_components tests
```

Observed: **246 passed, 0 failed, 0 xfailed, 0 skipped**; line coverage **100%**
(935 statements, 0 missed); branch coverage **99%** (234 branches, 4 partial,
all pre-existing diagnostic guards); `ruff` **clean** (exit 0). These match
`docs/test-report.md` exactly.

---

## Summary

**The slice is ready to tag/release. There are no blocking issues.** The B1
regression is genuinely fixed, all required findings (**N1**, **N2**, **N3**,
**N5**, **N7**, **N8**, **N9**) are confirmed, and the schedule slice meets the
user's goal — a working, per-student, read-only schedule calendar — for
well-formed SomToday data.

Verified from the production code and the HA framework source (not from test
names):

- **Fetch vs cache window are now decoupled.** `_async_update_data` calls
  `_current_window()` (recomputed from `dt_util.now()` on every poll) and stores
  the fetched range in `_data_window`; `schedule_window` returns `_data_window`
  (the cached-data window) and is used only by the calendar's cache check.
- **B1 invariants** (independently probed with the real `_async_update_data`,
  mocked API/auth): two polls one day apart advanced the fetch window
  `(2026-09-11, 2026-09-15)` → `(2026-09-12, 2026-09-16)`; after midnight
  without a poll `schedule_window` stayed on the cached range while
  `_current_window()` advanced; a range beyond the cached window was correctly
  classified out-of-cache; a failed poll kept the cached window while the next
  fetch window still advanced.
- **Per-student scoping, pagination, calendar contract, error mapping and HA
  lifecycle** remain correct (details in the previous sections of this file's
  history; re-confirmed by the suite and source).

---

## Blocking issues

**None.** The previous blocking issue **B1** (frozen fetch window) is fixed and
covered by `test_consecutive_polls_advance_the_window` and
`test_schedule_window_does_not_advance_between_polls`.

---

## Confirmation of the required fixes

| ID | Fix | Independent verification | Status |
|----|-----|--------------------------|--------|
| **B1** | `_current_window()` recomputes the fetch window each poll; `schedule_window` is the cached-data accessor | Confirmed at `coordinator.py:90-116,130`. Probe: two polls a day apart advance the window; cache window stays until the next successful poll; failed poll keeps the cache window; out-of-cache detection still works. New regression tests pass. | **Fixed** |
| **N1** | Sort with `dt_util.as_local(lesson.start)` | `coordinator.py:160`; `test_update_data_mixed_naive_aware_sorts` passes. | **Fixed** |
| **N2** | Persistent 401 → `SomtodayInvalidAuth` (reauth), 403 → `SomTodayApiError` (retryable) | `api.py:319-332`; reactive refresh still runs first; API and coordinator tests pass. Architecture §5.1 now has separate 401/403 rows. | **Fixed** |
| **N3** | Cache window captured at the last successful fetch | `schedule_window` returns `_data_window`; survives a failed poll. Combined with B1, fetch and cache windows no longer conflict. | **Fixed** |
| **N5** | Rotated token persisted at the end of the poll | `coordinator.py:127-130`; `test_update_data_persists_token_rotated_during_fetch` passes. Residual: a rotation followed by a failed poll is not persisted until the next success (non-blocking). | **Fixed (with residual)** |
| **N7** | `_async_get_students` re-raises `SomtodayInvalidAuth` | `coordinator.py:172-173`; `test_update_data_escalates_students_invalid_auth` passes; transient errors still keep the previous snapshot. | **Fixed** |
| **N8** | Read-only calendar assertion | `test_calendar_is_read_only` asserts no create/delete/update feature bits. | **Fixed** |
| **N9** | Documentation updated | README status/options, architecture §5.1 (401/403 rows), §13 hooks, §11 tree, CHANGELOG (246 tests) all corrected. See the residual nits below. | **Substantially closed** |

### N9 status — substantially closed, two residual Info nits

Re-read directly from the files (not from the tester's summary):

- **Corrected:** `README.md:7-11` now reads "authentication + schedule (v0.5.0)"
  and documents the read-only calendar; the options note (`README.md:92-95`)
  explains that `scan_interval`/`schedule_days_ahead` take effect immediately.
  `docs/architecture.md:503-504` has separate 401/403 rows; §13 no longer marks
  the coordinator/calendar as future work; §11 marks `coordinator.py`/
  `calendar.py`/`entity.py` implemented. `docs/CHANGELOG.md:48` says "246 tests,
  100% line coverage".
- **Still stale (Info):** `docs/architecture.md:211-216,220,223` (class-model
  comments still say `# future work` for `async_get_students`, the coordinator
  and `SomTodayData`; note `async_get_students` is implemented) and
  `docs/architecture.md:768-769` (the §9 `__init__.py` snippet) and
  `docs/architecture.md:869` (manifest example still `"version": "0.4.0"`).
  These are documentation-only nits with no runtime impact; the genuinely
  future items (grades/homework/absence/subjects, sensor/binary_sensor) are
  correctly labelled.

---

## Remaining non-blocking follow-ups

All confirmed still present; none block the release.

- **N4 (Low) — out-of-range calendar fetch errors bypass coordinator handling.**
  `async_get_events` → `async_fetch_schedule` can raise `SomtodayInvalidAuth`/
  `SomTodayError`; HA's `CalendarEntity._async_update_listener` catches only
  `HomeAssistantError`, so these surface as a logged task error with no graceful
  empty result. Recommendation: map errors in a coordinator helper or return
  `[]`.
- **N6 (Low) — out-of-range ranges are not cached.** Every out-of-window
  `async_get_events` call issues a fresh paginated request. Recommendation:
  memoise recent ranges or refresh the coordinator for the requested window.
- **N5 residual (Low) — a rotation followed by a failed poll is not persisted.**
  `_persist_rotated_token` runs only after a successful poll. Recommendation:
  persist in a `finally` (or on every `auth.tokens` change).
- **S2 / N11 (Info) — pages are not de-duplicated and the `Content-Range`
  `start` is ignored.** A broken server returning overlapping pages would
  double-count, bounded by the 50-page cap. No repro; no v1 action.
- **S3 (Info) — mixed naive/aware inverted interval.** `CalendarEvent`
  validation would raise for an inverted interval; unreachable with well-formed
  data, and the reachable mixed-datetime case is fixed by N1.
- **N10 (Info) — link selection uses the first link regardless of `rel`.**
  `models._first_link_id` (used by `Lesson.id`/`_extract_student_ids`) takes the
  first link with an `id`, while `Student._extract_id` prefers `rel == "self"`.
  Spec says `links[0].id`; confirm against a live payload (carry-over M2).
- **Carry-overs from v0.3.0/v0.4.0 (unchanged, non-blocking):** **T4**
  (`/account/me` omits `additional=restricties`), **T6/R7** (concurrent forced
  refreshes not deduplicated), **T7–T9** (low-probability paste edge cases),
  **F2** (migrated v1 entry without a student id is un-reauthable, Low), **F3**
  (`config.error.wrong_account` unused, Info), **F4**
  (`_async_current_ids(include_ignore=True)`, Info). **T3/R4** is closed by
  **N2**.

---

## Security assessment

| Area | Result | Notes |
|------|--------|-------|
| Secrets in logs | **Pass** | Only a debug student-list message and bounded `_log_error_summary` metadata; no request headers/tokens. |
| Refresh-token storage | **Pass with caveat** | Plaintext in `.storage/core.config_entries` (documented HA limitation); rotated tokens written back via `async_update_entry`. |
| Per-student data isolation | **Pass with caveat** | Client fetches all appointments; the coordinator scopes client-side. A multi-student response without `additionalObjects.leerlingen` keeps other students' lessons (documented trade-off, architecture §7.2.1). |
| Response parsing | **Pass** | `_extract_items` rejects non-sequence payloads; `parse_lesson` skips malformed entries. No unsafe deserialisation. |
| Read-only calendar | **Pass** | No create/update/delete overrides; `test_calendar_is_read_only` asserts it. |
| Dependencies / auth slice | **Pass** | Empty `requirements`, HA shared session; PKCE/auth unchanged from the approved v0.3.0 review. |

No security-blocking issue found.

---

## Home Assistant best-practices assessment

| Practice | Result | Notes |
|----------|--------|-------|
| `entry.runtime_data` / typed entry | **Pass** | `SomTodayRuntimeData(auth, api, coordinator)`. |
| `DataUpdateCoordinator` lifecycle | **Pass** | `config_entry=entry` → HA auto-registers `async_shutdown` on unload. |
| First refresh | **Pass** | `async_config_entry_first_refresh()`; auth failure → reauth, `UpdateFailed` → `ConfigEntryNotReady`. |
| Platform forwarding / unload | **Pass** | `async_forward_entry_setups` / `async_unload_platforms`, `PLATFORMS = [Platform.CALENDAR]`. |
| `CoordinatorEntity` availability | **Pass** | Availability follows `last_update_success`. |
| Device / unique id / translation | **Pass** | One device per entry, `has_entity_name`, `{entry_id}_calendar`, `entity.calendar` in all three files. |
| `CalendarEntity` contract | **Pass** | tz-aware `CalendarEvent`s, valid duration, base-class start/end alarms. |
| Error mapping | **Pass** | Persistent 401 → `ConfigEntryAuthFailed`; 403/other → `UpdateFailed`; student-list auth escalation correct. |
| Polling window | **Pass** | Fetch window recomputed each poll (`_current_window`); cache window captured for the calendar (`schedule_window`). |
| Test isolation | **Pass** | All HTTP mocked; no marker skips; `ruff` clean. |

---

## Tester-findings adjudication

| ID | Tester claim | My adjudication | Status |
|----|--------------|-----------------|--------|
| **B1** | Fixed by `_current_window()` | Confirmed from source, the two new tests, and my own multi-day probe (fetch advances; cache stable; failed poll keeps cache; out-of-cache detection works). | **Fixed** |
| **N1** | Mixed naive/aware sort fixed | Confirmed. | **Fixed** |
| **N2** | 401 definitive / 403 retryable | Confirmed; architecture §5.1 matches. | **Fixed** |
| **N3** | Cache window captured at the last fetch | Confirmed. | **Fixed** |
| **N5** | Token rotated during the fetch persisted | Confirmed for the successful-poll path; failed-poll residual. | **Fixed (with residual)** |
| **N7** | Student-list auth rejection escalates | Confirmed. | **Fixed** |
| **N8** | Read-only asserted | Confirmed. | **Fixed** |
| **N9** | Docs updated | Mostly confirmed; two residual stale spots (class-model/§9 "future work", manifest example `0.4.0`). Info only. | **Substantially closed** |
| **S2 / N11** | Pages not de-duplicated | Agree, Info; `Content-Range` `start` also ignored. No v1 action. | Open, non-blocking |
| **S3** | Inverted mixed interval can raise | Agree, Info, unreachable with well-formed data. | Open, non-blocking |
| **T3/R4** | 403 handling | Closed by N2. | **Closed** |
| **T4, T6/R7, T7–T9, F2, F3, F4** | Various low/info | Agree, all non-blocking and unchanged. | Open, non-blocking |
| Counts / coverage / lint | 246 passed, 100% line / 99% branch, ruff clean | Reproduced exactly. | Verified |

The tester's latest report repeats the earlier N9 description rather than the
current file contents; the actual files are substantially corrected (see the N9
section above for the two residual nits).

---

## Final verdict

**Approve — ready to tag/release.**

- **No blocking issues.** B1 is fixed with dedicated regression tests, and the
  fetch window now advances every poll while the cached-data window remains
  stable for the calendar's cache check.
- **Confirmed fixed:** **N1**, **N2**, **N3**, **N5**, **N7**, **N8**, and
  **N9** substantially (two Info doc nits remain).
- **Remaining non-blocking follow-ups:** **N4**, **N6**, the **N5** failed-poll
  residual, **S2/N11**, **S3**, **N10**, and the v0.3.0/v0.4.0 carry-overs
  (**T4**, **T6/R7**, **T7–T9**, **F2**, **F3**, **F4**). **T3/R4** is closed.
- **Security:** no security-blocking issue.
- **Tests:** 246/246 pass, 0 xfailed/skipped, 100% line / 99% branch, `ruff`
  clean — independently reproduced, including the multi-day poll case that
  caught B1.

The v0.5.0 schedule slice delivers the user's goal (a working, per-student,
read-only schedule calendar) and can be tagged/released. The residual items are
worth scheduling for the next slice but do not gate this release.

### Changes made by this review

- `docs/review.md` rewritten for the final v0.5.0 schedule-slice state.
- **No production code was modified.** The only probe was a throw-away script in
  the temp directory (now removed).
