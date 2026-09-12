# Test report — SomToday Home Assistant plugin

**Component under test:** Model A identity model (**v0.4.0**): one config entry
per `(account, student)` — `const.unique_id_for`, `config_flow.py` (user flow,
student-selection step, required `/account/me`, reauth
`wrong_account`/`student_removed`, v1→v2 migration), `strings.json` /
`translations/{en,nl}.json`, plus the previously approved authentication / API /
model slice.
**Date:** 2026-09-12 (final post-fix re-run: **F1 + F1b fixed**)
**Tester:** tester-agent
**Environment:**
`/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv`
(Python 3.14.7, Home Assistant 2026.9.1, pytest 9.0.3, pytest-asyncio 1.4.0,
pytest-homeassistant-custom-component 0.13.364, aioresponses 0.7.9,
pytest-cov 7.1.0, ruff 0.16.7)

> This report builds on the previously approved **v0.3.0 browser
> authorization-code + PKCE** slice (T1/T2 fixed, 135/135 green) and covers the
> **v0.4.0 Model A identity model**. The two findings raised in the previous
> run — **F1** (account-id fallback misidentifying the account) and **F1b** (the
> same fallback allowing a duplicate student entry) — are **fixed and
> independently re-verified** below. The coordinator and entity platforms remain
> unimplemented and are out of scope.

---

## Summary

| Metric | Value |
|--------|-------|
| Test files | 7 (`test_auth`, `test_models`, `test_config_flow`, `test_api`, `test_const`, `test_translations`, `test_manifest`) + `conftest.py` |
| Tests collected | **159** |
| Passed | **159** |
| Failed | **0** |
| Xfailed | **0** |
| Skipped | **0** |
| Line coverage (whole integration) | **99%** (635 statements, 2 missed) |
| Branch coverage (whole integration) | **99%** (635 stmts / 2 miss; 158 branches / 6 partial) |
| `config_flow.py` | **100% line + 100% branch** (155 stmts, 40 branches) |
| `const.py` | **100% line + 100% branch** |
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

Exact results: `159 passed in 1.16s` (0 failed, 0 xfailed, 0 skipped); line
`TOTAL 635 2 99%`; branch `TOTAL 635 2 158 6 99%`;
`All checks passed!` (ruff exit 0).

Per-file test counts (collected): `test_auth.py` 54, `test_config_flow.py` 45,
`test_models.py` 33, `test_api.py` 20, `test_const.py` 3,
`test_translations.py` 3, `test_manifest.py` 1.

**Gate (minimum 80% coverage): PASS** — 99% line and 99% branch, zero
failures, zero xfails, zero skips.

---

## Verification of the F1 / F1b fix (independently reproduced)

The fix makes `GET /rest/v1/account/me` **required** in
`config_flow.py::_async_identify`: it no longer catches `SomTodayError` and no
longer falls back to `students[0].id`. A failure propagates to
`_async_authorize_and_identify`, whose generic `except SomTodayError` maps it to
the retryable `cannot_connect`.

The engineer's regression tests were reviewed **and** re-verified with an
independent probe (a temporary file outside the suite, since removed). The probe
does not reuse the rewritten tests; it drives the flow with the `hass` fixture
and checks the entry/unique-id invariants.

| Probe | Scenario | Observed | Verdict |
|-------|----------|----------|---------|
| A | Initial flow, `/account/me` raises `SomTodayConnectionError` | `FORM` (`user`) `errors={"base": "cannot_connect"}`, **0 entries** | F1 fixed |
| B | Initial flow, `/account/me` raises `SomTodayApiError` (malformed) | `FORM` `cannot_connect`, **0 entries** | F1 fixed |
| C | `/account/me` succeeds, `students=[]` | `FORM` `no_students` (path intact, not `cannot_connect`) | No regression |
| D | Reauth, `/account/me` raises `SomTodayConnectionError` | `FORM` (`reauth_confirm`) `cannot_connect`; entry `unique_id`/`student_id` unchanged | F1 fixed |
| E | Existing `account-1:1234` entry, `/account/me` fails | `cannot_connect`; only the pre-existing unique id remains (**no duplicate**) | F1b fixed |

**F1 — fixed.** A transient `/account/me` failure during reauth is now
retryable `cannot_connect` instead of `wrong_account`.
Evidence: `test_reauth_transient_account_failure_is_retryable`, probe D.

**F1b — fixed.** A transient `/account/me` failure during the initial flow no
longer computes a student-based unique id, so it cannot add an
already-configured student.
Evidence: `test_user_flow_account_failure_cannot_duplicate_student`, probe E.

The production diff confirms the change: the `try/except SomTodayError`
fallback and the `account_id is None` branch are gone, and `_async_identify`
now returns a non-optional `tuple[str, list[Student]]`
(`config_flow.py:359-380`). `docs/architecture.md` §1.1 documents the required
endpoint and the reason.

---

## Independent assessment of the Model A identity model

Every scenario requested for this slice was reproduced from the production code
and the passing suite, not from test names alone.

| Required scenario | Test(s) | Verdict |
|-------------------|---------|---------|
| 0 students → `no_students` (error, fresh authorize URL) | `test_user_flow_no_students` | PASS |
| 1 student → auto-select, no student step | `test_user_flow_success`, `test_user_flow_second_student_same_account` | PASS |
| 2+ students → `student` step with options | `test_user_flow_multiple_students_shows_student_step` | PASS |
| Duplicate `(account, student)` → `already_configured` | `test_user_flow_duplicate_aborts`, `test_user_flow_student_step_aborts_when_all_configured` | PASS |
| Second student of the same account succeeds with a distinct unique id | `test_user_flow_second_student_same_account` | PASS |
| Reauth `wrong_account` (genuine account mismatch) | `test_reauth_flow_wrong_account` | PASS |
| Reauth `student_removed` | `test_reauth_flow_student_removed` | PASS |
| Migration v1 → composite unique id | `test_async_migrate_entry_v1_to_composite`, `test_setup_entry_migrates_v1_entry` | PASS |
| `unique_id_for` distinguishes students and accounts | `test_unique_id_for_builds_composite_id`, `test_unique_id_for_distinguishes_students_of_one_account`, `test_unique_id_for_distinguishes_accounts_for_one_student` | PASS |
| Translation key parity for the new step/abort | `test_translation_files_have_matching_keys`, `test_english_config_translations_load`, `test_dutch_config_translations_load` | PASS |
| `/account/me` required — initial flow | `test_user_flow_account_lookup_failure_is_retryable`, `test_user_flow_account_lookup_failure_with_empty_list_is_retryable` (+ probes A/B) | PASS |
| `/account/me` required — reauth | `test_reauth_transient_account_failure_is_retryable` (+ probe D) | PASS |
| `/account/me` failure cannot duplicate an existing entry | `test_user_flow_account_failure_cannot_duplicate_student` (+ probe E) | PASS |
| `/account/me` success + empty student list → `no_students` | `test_user_flow_no_students` (+ probe C) | PASS |

### Framework probes (unchanged)

| Probe | Result |
|-------|--------|
| Does the flow's **own in-progress unique id** interfere with `_async_current_ids()`? | **No.** In HA 2026.9.1 `_async_current_ids()` (config_entries.py:3251) iterates `async_entries` only. Verified by source read and `test_concurrent_flows_same_student_create_one_entry`. |
| `raise_on_progress=False` implications | Disables HA's `already_in_progress` guard, but no duplicate is reproducible: `_async_finish` has no real suspension point between `_abort_if_unique_id_configured()` and `async_create_entry`. `test_concurrent_flows_same_student_create_one_entry` yields exactly one entry + one `already_configured` abort. Observation only, no defect. |
| Migration correctness (version persistence, HA wiring) | `test_setup_entry_migrates_v1_entry` drives the HA migration hook and asserts `version == 2` and the composite unique id after `async_setup`. Direct-call tests cover the missing-student/missing-account fallbacks. |
| Student step reachable/usable (`SelectSelector` id as string vs int) | Options are `{"value": str(student.id), ...}`; the handler compares `str(student.id) == selected`. HA validates the dropdown against the offered options. Covered by the student-step tests. |

---

## Test cases

### Component: config flow / identity model (`tests/test_config_flow.py`, 45 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_user_flow_success` | 1 student auto-selects; composite unique id, account metadata persisted | PASS |
| `test_user_flow_bare_code` | A bare code is accepted without state validation | PASS |
| `test_user_flow_account_lookup_failure_is_retryable` | **F1 regression:** `/account/me` failure → retryable `cannot_connect`, no entry | PASS |
| `test_user_flow_duplicate_aborts` | Same `(account, student)` → `already_configured` | PASS |
| `test_user_flow_no_students` | Account ok + 0 students → `no_students` + fresh authorize URL | PASS |
| `test_user_flow_multiple_students_shows_student_step` | 2+ students → `student` step, string option values/labels | PASS |
| `test_user_flow_student_step_unknown_selection_reshows_form` | Unknown dropdown value rejected by HA validation; flow stays on step | PASS |
| `test_user_flow_student_step_aborts_when_all_configured` | All students configured meanwhile → `already_configured` | PASS |
| `test_user_flow_second_student_same_account` | Second student of one account → distinct composite unique id | PASS |
| `test_user_flow_exchange_errors[4]` | Exchange error → `invalid_auth`/`cannot_connect`/`unknown` | PASS |
| `test_user_flow_login_page_paste` | Login-page paste → `login_page` | PASS |
| `test_user_flow_state_mismatch` | Wrong state → `state_mismatch` | PASS |
| `test_user_flow_invalid_url` | Unstructured paste → `invalid_url` | PASS |
| `test_user_flow_sso_callback_paste` | SSO callback paste → `sso_callback` | PASS |
| `test_authorize_url_kept_on_recoverable_paste` | Paste mistake keeps the open authorize URL | PASS |
| `test_authorize_url_regenerated_when_spent` | Definitive rejection mints a new PKCE pair/state | PASS |
| `test_reauth_flow_updates_refresh_token` | Reauth rotates the token and reloads; student binding preserved | PASS |
| `test_reauth_flow_wrong_account` | Genuine different account → `wrong_account` | PASS |
| `test_reauth_flow_student_removed` | Stored student missing → `student_removed` | PASS |
| `test_reauth_flow_errors[2]` | Reauth exchange errors → `invalid_auth`/`cannot_connect` | PASS |
| `test_reauth_after_failed_setup_reloads_entry` | Reauth recovers SETUP_ERROR → LOADED (review B1 regression) | PASS |
| `test_options_flow` | Options persist poll interval and toggles | PASS |
| `test_options_flow_schedules_reload` | Saving options schedules an entry reload | PASS |
| `test_setup_entry_refreshes_token` | Setup refreshes and persists the rotated token; logs student | PASS |
| `test_setup_entry_keeps_refresh_token_when_not_rotated` | Non-rotating response leaves the token untouched | PASS |
| `test_setup_entry_auth_failure` | Definitive rejection → `ConfigEntryAuthFailed` | PASS |
| `test_setup_entry_connection_failure` | Network failure → `ConfigEntryNotReady` | PASS |
| `test_setup_entry_unexpected_failure` | Other API error → `ConfigEntryNotReady` | PASS |
| `test_async_migrate_entry_v1_to_composite` | v1 entry → composite id + version 2 | PASS |
| `test_async_migrate_entry_without_student_falls_back` | v1 without student id keeps account id, bumps version | PASS |
| `test_async_migrate_entry_without_account_keeps_unique_id` | v1 without account metadata keeps unique id, bumps version | PASS |
| `test_async_migrate_entry_current_version_is_noop` | v2 entry untouched | PASS |
| `test_async_unload_entry` | Unload without platforms succeeds | PASS |
| `test_default_api_url_constant` | Default API URL is the documented host | PASS |
| `test_setup_entry_migrates_v1_entry` | HA migration hook runs on setup; composite id + version persisted | PASS |
| `test_reauth_preserves_composite_unique_id` | Reauth does not change the composite unique id | PASS |
| `test_concurrent_flows_same_student_create_one_entry` | Two concurrent flows → exactly one entry + `already_configured` | PASS |
| `test_reauth_transient_account_failure_is_retryable` | **F1 regression:** transient `/account/me` failure in reauth → `cannot_connect` | PASS |
| `test_user_flow_account_failure_cannot_duplicate_student` | **F1b regression:** account failure cannot add a duplicate student | PASS |
| `test_user_flow_student_step_reshows_remaining_after_config_change` | Selected student configured meanwhile → remaining options re-shown | PASS |
| `test_user_flow_account_lookup_failure_with_empty_list_is_retryable` | **F1 regression:** `/account/me` failure with empty list → `cannot_connect` (not `no_students`) | PASS |

### Component: pure identity helper (`tests/test_const.py`, 3 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_unique_id_for_builds_composite_id` | `unique_id_for("account-1", 1234) == "account-1:1234"` | PASS |
| `test_unique_id_for_distinguishes_students_of_one_account` | Two students of one account differ | PASS |
| `test_unique_id_for_distinguishes_accounts_for_one_student` | Same student under two accounts differs | PASS |

### Component: translations (`tests/test_translations.py`, 3 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_translation_files_have_matching_keys` | `strings.json`, `en.json`, `nl.json` expose identical leaf keys (incl. `student` step + `student_removed` abort) | PASS |
| `test_english_config_translations_load` | HA loads EN `student_select` and `student_removed` | PASS |
| `test_dutch_config_translations_load` | HA loads NL `student` title/data and `student_removed` abort | PASS |

### Components carried over from the approved v0.3.0 slice

| Component | Tests | Result |
|-----------|-------|--------|
| `tests/test_auth.py` — PKCE, code extraction, exchange, refresh, holder | 54 | PASS |
| `tests/test_models.py` — `Account`/`Student` parsers, `SomTodayTokens` | 33 | PASS |
| `tests/test_api.py` — `account/me`, `leerlingen`, 401 retry, error mapping, release | 20 | PASS |
| `tests/test_manifest.py` — domain/version/`config_flow`/`iot_class` | 1 | PASS |

The old tests that documented the F1 fallback behaviour
(`test_user_flow_account_fallback_to_student_id`,
`test_reauth_transient_account_failure_aborts_wrong_account`,
`test_user_flow_account_fallback_can_duplicate_configured_student`) were
**rewritten by the engineer** into the retryable regression tests above; no test
was silently dropped. The previously approved auth slice is unaffected (all 107
auth/API/model tests still pass).

---

## Coverage

Line coverage (`--cov-report=term-missing`):

```text
Name                                         Stmts   Miss  Cover   Missing
--------------------------------------------------------------------------
custom_components/sometoday/__init__.py         46      2    96%   96, 106
custom_components/sometoday/api.py              94      0   100%
custom_components/sometoday/auth.py            151      0   100%
custom_components/sometoday/config_flow.py     155      0   100%
custom_components/sometoday/const.py            35      0   100%
custom_components/sometoday/exceptions.py        7      0   100%
custom_components/sometoday/models.py          147      0   100%
--------------------------------------------------------------------------
TOTAL                                          635      2    99%
```

Branch coverage (`--cov-branch --cov-report=term-missing`):

```text
Name                                         Stmts   Miss Branch BrPart  Cover   Missing
----------------------------------------------------------------------------------------
custom_components/sometoday/__init__.py         46      2      8      3    91%   83->90, 96, 106
custom_components/sometoday/api.py              94      0     18      2    98%   203->206, 208->214
custom_components/sometoday/auth.py            151      0     40      1    99%   81->exit
custom_components/sometoday/config_flow.py     155      0     40      0   100%
custom_components/sometoday/const.py            35      0      0      0   100%
custom_components/sometoday/exceptions.py        7      0      0      0   100%
custom_components/sometoday/models.py          147      0     52      0   100%
----------------------------------------------------------------------------------------
TOTAL                                          635      2    158      6    99%
```

| File | Stmts | Missed | Branches | Partial | Line | Branch |
|------|------:|-------:|---------:|--------:|-----:|-------:|
| `__init__.py` | 46 | 2 | 8 | 3 | 96% | 91% |
| `api.py` | 94 | 0 | 18 | 2 | 100% | 98% |
| `auth.py` | 151 | 0 | 40 | 1 | 100% | 99% |
| `config_flow.py` | 155 | 0 | 40 | 0 | 100% | 100% |
| `const.py` | 35 | 0 | 0 | 0 | 100% | 100% |
| `exceptions.py` | 7 | 0 | 0 | 0 | 100% | 100% |
| `models.py` | 147 | 0 | 52 | 0 | 100% | 100% |
| **Total** | **635** | **2** | **158** | **6** | **99%** | **99%** |

`config_flow.py` is at **100% line + branch** after the fix; the removed
fallback also removed the previously uncovered `account_id is None` branch
(statement count dropped from 164 to 155). `const.py` is also 100%. The
remaining partials are defensive branches unrelated to the identity model:

- `__init__.py:83->90` — `auth.tokens is None` guard; `96`, `106` — `if PLATFORMS:`
  (empty until the entity slice).
- `api.py:203->206` — `response.headers` not a `Mapping`; `208->214` — response
  without a `text` attribute.
- `auth.py:81->exit` — `_release()` on a response without `release`.

---

## Findings

### F1 — account-id fallback misidentified the account — **FIXED**
`_async_identify` now requires `/account/me` and lets `SomTodayError` propagate;
the generic handler maps it to retryable `cannot_connect`. Reauth no longer
aborts `wrong_account` on a transient account failure, and the initial flow can
no longer compute a `"<student>:<student>"` unique id. Verified by
`test_reauth_transient_account_failure_is_retryable`,
`test_user_flow_account_lookup_failure_is_retryable`,
`test_user_flow_account_lookup_failure_with_empty_list_is_retryable`, probes
A/B/D, and `docs/architecture.md` §1.1.

### F1b — duplicate student entry via the fallback — **FIXED**
Same root cause, fixed by the same change. Verified by
`test_user_flow_account_failure_cannot_duplicate_student` and probe E: with an
existing `account-1:1234` entry, a failing `/account/me` leaves exactly that one
entry and returns `cannot_connect`.

### F2 — migrated entry without a student id is un-reauthable — **Low, OPEN**
Defensive v1 fallback in `async_migrate_entry`
(`test_async_migrate_entry_without_student_falls_back`). Only affects malformed
v1 entries that never stored a student; unchanged by this fix.

### F3 — `config.error.wrong_account` is unused — **Info, OPEN**
Reauth aborts with `async_abort(reason="wrong_account")`, which resolves via
`config.abort.wrong_account`. The identical `config.error.wrong_account` key is
never selected (the flow does not set it as a form error). Harmless duplication.

### F4 — `_async_current_ids(include_ignore=True)` counts ignored entries — **Info, OPEN**
An ignored entry with a composite unique id would suppress re-adding that
student, while HA's `_abort_if_unique_id_configured` allows re-configuring an
ignored entry from the user source. This integration has no discovery/ignore
step, so the branch is unreachable today.

### `raise_on_progress=False` — **Info, no defect**
Disables the `already_in_progress` guard in `_async_finish`
(config_flow.py:399). No duplicate is reproducible because the finish path has
no real suspension point; `test_concurrent_flows_same_student_create_one_entry`
confirms exactly one entry and one `already_configured` abort.

### Carry-over findings from the v0.3.0 report (unchanged, non-blocking)
T3 (403 does not trigger a reactive refresh), T4 (`/account/me` omits
`additional=restricties`), T6 (concurrent forced refreshes not deduplicated),
T7–T9 (low-probability paste edge cases), and the production `assert`s in the
config flow. None affect the identity model.

---

## Blockers

1. **Real-account validation is prohibited.** The live SomToday behaviour of
   `/account/me` and multi-student accounts can only be confirmed against a real
   account; tests never call the real API. The F1 fix is therefore verified with
   mocked failures (`SomTodayConnectionError` and `SomTodayApiError`), which is
   the strongest evidence available in this environment.
2. **No coordinator/entity modules exist** (`coordinator.py`, `sensor.py`,
   `binary_sensor.py`, `calendar.py`, `entity.py`). Their tests remain out of
   scope.

No other blockers: the suite is green (`159 passed, 0 failed, 0 xfailed,
0 skipped`) and no test requires a production change to pass.

---

## Changes made by the tester (this run)

**No production code was modified.** No new tests were added: the engineer's
rewritten regression tests cover the required `/account/me` path for the initial
flow, reauth, the empty student list and duplicate prevention, and
`config_flow.py` is at 100% line+branch, so no genuine gap remained. The old
F1/F1b documentation tests were replaced by the engineer; the tester reviewed
them and re-verified the behaviour independently.

| Action | Detail |
|--------|--------|
| Independent probe (temporary, removed) | 5 scenarios: initial `/account/me` connection error, initial malformed payload, account-ok/empty-list `no_students`, reauth connection error, and no-duplicate-with-existing-entry — all PASS |
| Report rewritten | All F1/F1b references, summary, test tables, coverage, findings, blockers, gate checklist and verdict updated to the fixed state |
| Production code | untouched |
| Tests removed | none |

### Test-quality assessment and gate

| Criterion | Result |
|-----------|--------|
| Minimum 80% coverage | **Met** — 99% line, 99% branch (`config_flow.py` 100%/100%) |
| All tests pass | **Met** — 159 passed, 0 failed, 0 xfailed, 0 skipped |
| Error scenarios tested | **Met** — flow errors, required `/account/me` (initial/reauth/empty list), reauth `wrong_account`/`student_removed`, setup exceptions, migration fallbacks, concurrency |
| No production code modified | **Met** |
| No test removed or weakened | **Met** — the engineer's rewrite replaced the F1 documentation tests with retryable regression tests; nothing was silently dropped |

**Final verdict:** the v0.4.0 Model A identity model is independently validated
with **F1 and F1b confirmed fixed**. `/account/me` is required end-to-end: a
transient failure now yields retryable `cannot_connect`, creates no entry, and
cannot duplicate an existing student, while the genuine `wrong_account` and
`student_removed` reauth aborts and the `no_students` path still behave as
specified. `config_flow.py` and `const.py` are at 100% line+branch, the whole
integration at 99% line/branch, with **159/159 tests passing and zero
xfails/skips**. The remaining findings (F2 Low, F3/F4 Info) are non-blocking.
**The 80% gate is met with room to spare.**
