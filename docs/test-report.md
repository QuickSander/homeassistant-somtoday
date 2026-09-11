# Test report — SomToday Home Assistant plugin

**Component under test:** config-flow / API / integration-setup slice
(`config_flow.py`, `api.py`, `auth.py` response lifecycle, `__init__.py`,
`models.py` `Student`/`parse_students`, `manifest.json`, `strings.json`,
`translations/*.json`, `pytest.ini`)
**Date:** 2026-09-11 (final post-fix re-run: B1/B2/N5/G)
**Tester:** tester-agent
**Environment:** `/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv`
(Python 3.14.7, Home Assistant 2026.9.1, pytest 9.0.3, pytest-asyncio 1.4.0,
pytest-homeassistant-custom-component 0.13.364, aioresponses 0.7.9,
pytest-cov 7.1.0, ruff 0.16.7)

---

## Summary

| Metric | Value |
|--------|-------|
| Test files | 6 (`test_auth`, `test_models`, `test_config_flow`, `test_api`, `test_translations`, `test_manifest`) + `conftest.py` |
| Tests collected | **127** |
| Passed | **127** |
| Failed | **0** |
| Xfailed | **0** |
| Skipped | **0** |
| Line coverage (whole integration) | **99%** (677 statements, 3 missed: `__init__.py:89,99`, `config_flow.py:266`) |
| Branch coverage (whole integration) | **99%** (677 stmts / 2 miss; 144 branches / 5 partial) |
| Lint (`ruff check custom_components tests`) | **clean** (`All checks passed!`) |
| Real SomToday API calls | **none** (all HTTP via `FakeSession`/`FakeResponse`) |

Commands used:

```sh
/var/.../sometoday-venv/bin/python -m pytest tests/ -v \
  --cov=custom_components.sometoday --cov-report=term-missing
/var/.../sometoday-venv/bin/python -m pytest tests/ -q \
  --cov=custom_components.sometoday --cov-branch --cov-report=term-missing
/var/.../sometoday-venv/bin/python -m ruff check custom_components tests
```

Results: `127 passed in 0.96s`; `TOTAL 677 3 99%` (line);
`TOTAL 677 2 144 5 99%` (branch); `All checks passed!`.

Per-file test counts: `test_auth.py` 51, `test_models.py` 29,
`test_config_flow.py` 28, `test_api.py` 16, `test_translations.py` 2,
`test_manifest.py` 1.

**Gate (minimum 80% coverage): PASS** — 99% line and 99% branch, **zero
failures, zero xfails, zero skips**. All previously reported defects
(B1, B2, N5, G) are fixed and verified.

---

## Verification of the fixes (independently reproduced)

Each fix was verified by reading the production code **and** by an independent
probe, not just by trusting the test names.

| ID | Fix | Independent verification | Verdict |
|----|-----|--------------------------|---------|
| **B2** | `api.py::_request` releases the rejected 401 before refresh+retry (`_release()`); `_async_decode` still releases the decoded response | `api.py:90-98` calls `_release(response)` before `async_refresh()`. Probe: `FakeSession([401, 200])` → `first.release_count == 1`, `second.release_count == 1`. Old strict-xfail is now an ordinary passing test. | **FIXED** |
| **B1** | Reauth uses `async_update_reload_and_abort(entry, data_updates=…, reason=…)` so the entry reloads | `config_flow.py:317-321`. Probe: real `MockConfigEntry` driven to `SETUP_ERROR` → reauth (with `async_refresh` mocked) → `reauth_successful`, refresh token `rotated`, **`entry.state is ConfigEntryState.LOADED`**. Covered by `test_reauth_flow_updates_refresh_token` and `test_reauth_after_failed_setup_reloads_entry`. | **FIXED** |
| **N5** | `auth.py` releases every response (authorize/session/forms via `try/finally`, token response, school list) | `auth.py:261-284`, `287-293`, `296-307`, `330-340`, `432-433`, `113-114`. Probes: authorize 500 → 1; username/password form 500 → used responses released once; token 400/500/invalid-JSON → 1; SSO redirect → 1. No double-release. | **FIXED** |
| **G** | `async_get_schools` calls `_raise_for_error_status` **inside** the `try/finally` so 4xx/5xx/429 responses are released | `auth.py:97-114`: the status check is now the first statement inside the `try`, with `_release(response)` in `finally`. Probe: 500/429/403/404 → `release_count == 1` each; 200 and invalid-JSON → `1`. `test_get_schools_releases_error_response` is now a plain passing test (no marker). | **FIXED** |

There are **no `xfail`, `skipif` or `skip` markers anywhere in `tests/`** (a
source scan over all `test_*.py` files returns no matches), and
`pytest -rxX` reports `127 passed` with no xfail/skip summary.

### No regressions in the other release paths

Independent probes across the whole response lifecycle all release exactly once
(no double-release, no leak):

| Path | Result |
|------|--------|
| School list 200 / 500 / 429 / 403 / 404 / invalid-JSON | `release_count == 1` each |
| Authorize 500 | `1` |
| Username form 500 (responses actually used) | `[1, 1, 1]` |
| Token 500 | `[1, 1, 1, 1, 1]` |
| API 401 → refresh → retry | first `1`, retried `1` |
| PKCE happy path (engineer's test) | exact `[1, 1, 1, 1, 1]` |

---

## Test cases

### Component: config flow (`tests/test_config_flow.py`, 28 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_user_flow_single_student` | Single-student login creates the entry directly | PASS |
| `test_user_flow_multiple_students` | Multi-student account shows the picker and stores the chosen id | PASS |
| `test_user_flow_invalid_auth` | Rejected credentials → `invalid_auth` | PASS |
| `test_user_flow_school_list_connection_error` | School list network failure → `cannot_connect` | PASS |
| `test_user_flow_sso_not_supported` | SSO-only school → `sso_not_supported` | PASS |
| `test_user_flow_duplicate_aborts` | Duplicate unique-id → abort `already_configured` | PASS |
| `test_reauth_flow_updates_refresh_token` | Reauth stores the rotated token **and reloads the entry to `LOADED`** (B1) | PASS |
| `test_reauth_after_failed_setup_reloads_entry` | `SETUP_ERROR` → reauth → `LOADED` recovery (B1 regression) | PASS |
| `test_options_flow` | Options flow persists interval/days/toggles | PASS |
| `test_setup_entry_refreshes_token` | Setup rotates the token, updates the entry and exposes `runtime_data` | PASS |
| `test_user_flow_login_connection_error` | Login network failure → `cannot_connect` | PASS |
| `test_user_flow_login_unexpected_error` | Unexpected login failure → `unknown` | PASS |
| `test_user_flow_school_list_unexpected_error` | Unexpected school-list failure → `unknown` | PASS |
| `test_user_flow_student_fetch_errors[auth]` | Student validation 401/403 → `invalid_auth` | PASS |
| `test_user_flow_student_fetch_errors[connection]` | Student validation network failure → `cannot_connect` | PASS |
| `test_user_flow_student_fetch_errors[unknown]` | Student validation unexpected failure → `unknown` | PASS |
| `test_user_flow_no_students` | Empty student list → `no_students` | PASS |
| `test_school_option_labels` | Selector label includes place only when present | PASS |
| `test_reauth_flow_errors[sso]` | Reauth SSO-only → `sso_not_supported` | PASS |
| `test_reauth_flow_errors[auth]` | Reauth rejected password → `invalid_auth` | PASS |
| `test_reauth_flow_errors[connection]` | Reauth network failure → `cannot_connect` | PASS |
| `test_reauth_flow_errors[unknown]` | Reauth unexpected failure → `unknown` | PASS |
| `test_setup_entry_auth_failure` | `SomTodayAuthError` → `ConfigEntryAuthFailed` | PASS |
| `test_setup_entry_connection_failure` | `SomTodayConnectionError` → `ConfigEntryNotReady` | PASS |
| `test_setup_entry_unexpected_failure` | Other `SomTodayError` → `ConfigEntryNotReady` | PASS |
| `test_setup_entry_keeps_refresh_token_when_not_rotated` | Non-rotating refresh leaves entry data unchanged | PASS |
| `test_async_migrate_entry` | Migration hook returns `True` | PASS |
| `test_async_unload_entry` | Unload without platforms returns `True` | PASS |

### Component: REST API client (`tests/test_api.py`, 16 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_get_students_parses_items` | Documented payload parsed; URL/params/auth headers asserted | PASS |
| `test_get_students_401_refreshes_and_retries` | 401 → one refresh → retry succeeds | PASS |
| `test_get_students_auth_error` | 403 → `SomTodayAuthError` | PASS |
| `test_get_students_rate_limit` | 429 → `SomTodayRateLimitError` | PASS |
| `test_get_students_server_error` | 5xx → `SomTodayApiError` | PASS |
| `test_get_students_connection_error` | Network error → `SomTodayConnectionError` | PASS |
| `test_get_students_invalid_json` | Wrong top-level shape → `SomTodayApiError` | PASS |
| `test_get_students_401_retry_still_401` | 401 → refresh → 401 → `SomTodayAuthError` (one refresh) | PASS |
| `test_get_students_401_refresh_failure_propagates` | Refresh failure during retry propagates | PASS |
| `test_get_students_releases_final_response` | Final response is released once | PASS |
| `test_get_students_releases_first_401_response` | Both the 401 and the retried response are released (B2) | PASS |
| `test_get_students_non_json_body` | Undecodable body → `SomTodayApiError` | PASS |
| `test_get_students_body_read_error` | Transport error while reading body → `SomTodayConnectionError` | PASS |
| `test_build_headers_without_tokens` | No tokens → no `Authorization` header | PASS |
| `test_send_post_uses_session_post` | Non-GET dispatched via `session.post` | PASS |
| `test_release_ignores_response_without_release` | `_release()` tolerates an object without `release` | PASS |

### Component: authentication / response lifecycle (`tests/test_auth.py`, 51 tests)

All 47 pre-existing OAuth2 tests pass, plus the response-lifecycle tests:

| Test name | Goal | Result |
|-----------|------|--------|
| `test_pkce_login_releases_every_response` | Authorize/session/form/token responses each released exactly once (N5) | PASS |
| `test_sso_redirect_releases_authorize_response` | Authorize response released even when the SSO fallback runs (N5) | PASS |
| `test_get_schools_releases_response` | School-list response released after parsing, success path (N5) | PASS |
| `test_get_schools_releases_error_response` | School-list response released on an error status (G regression) | PASS |

### Component: models — `Student` / `parse_students` (`tests/test_models.py`, 29 tests)

Token/school tests (12) plus 17 `Student` tests covering the documented
`{"items": [...]}` shape, bare list, `links` self/any/top-level id fallback,
string coercion, invalid/missing id, `display_name` fallbacks, missing/malformed
`pasfoto` and invalid payload/entry `TypeError`s — all PASS.

### Component: translations and manifest (`tests/test_translations.py`, `tests/test_manifest.py`)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_translation_files_have_matching_keys` | `strings.json`, `en.json`, `nl.json` expose identical leaf keys | PASS |
| `test_english_config_translations_load` | HA loads the English config-flow translations | PASS |
| `test_manifest_required_fields` | domain/version-format/`config_flow`/`iot_class`/`integration_type`; exact version not pinned (N16) | PASS |

---

## Coverage

Line coverage (`--cov-report=term-missing`):

```text
Name                                         Stmts   Miss  Cover   Missing
--------------------------------------------------------------------------
custom_components/sometoday/__init__.py         47      2    96%   89, 99
custom_components/sometoday/api.py              69      0   100%
custom_components/sometoday/auth.py            219      0   100%
custom_components/sometoday/config_flow.py     145      1    99%   266
custom_components/sometoday/const.py            42      0   100%
custom_components/sometoday/exceptions.py        7      0   100%
custom_components/sometoday/models.py          148      0   100%
--------------------------------------------------------------------------
TOTAL                                          677      3    99%
```

Branch coverage (`--cov-branch --cov-report=term-missing`):

```text
Name                                         Stmts   Miss Branch BrPart  Cover   Missing
----------------------------------------------------------------------------------------
custom_components/sometoday/__init__.py         47      1      6      2    94%   88->89, 99
custom_components/sometoday/api.py              69      0     14      0   100%
custom_components/sometoday/auth.py            219      0     50      0   100%
custom_components/sometoday/config_flow.py     145      1     26      3    98%   161->176, 266, 286->290
custom_components/sometoday/const.py            42      0      0      0   100%
custom_components/sometoday/exceptions.py        7      0      0      0   100%
custom_components/sometoday/models.py          148      0     48      0   100%
----------------------------------------------------------------------------------------
TOTAL                                          677      2    144      5    99%
```

| File | Stmts | Missed | Branches | Partial | Line | Branch |
|------|------:|-------:|---------:|--------:|-----:|-------:|
| `__init__.py` | 47 | 2 | 6 | 2 | 96% | 94% |
| `api.py` | 69 | 0 | 14 | 0 | 100% | 100% |
| `auth.py` | 219 | 0 | 50 | 0 | 100% | 100% |
| `config_flow.py` | 145 | 1 | 26 | 3 | 99% | 98% |
| `const.py` | 42 | 0 | 0 | 0 | 100% | 100% |
| `exceptions.py` | 7 | 0 | 0 | 0 | 100% | 100% |
| `models.py` | 148 | 0 | 48 | 0 | 100% | 100% |
| **Total** | **677** | **3** | **144** | **5** | **99%** | **99%** |

`api.py`, `auth.py` and `models.py` are at 100% line **and** branch coverage.

### Scenario assessment — architecture §4 (config flow)

| Scenario | Covered | Evidence |
|----------|---------|----------|
| Successful setup, single / multiple students | Yes | `test_user_flow_single_student`, `test_user_flow_multiple_students` |
| Invalid credentials / SSO-only | Yes | `test_user_flow_invalid_auth`, `test_user_flow_sso_not_supported` |
| School-list connection / unexpected failure | Yes | `test_user_flow_school_list_*` |
| Duplicate unique-id abort | Yes | `test_user_flow_duplicate_aborts` |
| Student validation error mapping + no students | Yes | `test_user_flow_student_fetch_errors[...]`, `test_user_flow_no_students` |
| Reauth updates token **and reloads** | Yes | `test_reauth_flow_updates_refresh_token`, `test_reauth_after_failed_setup_reloads_entry` |
| Reauth error mapping | Yes | `test_reauth_flow_errors[...]` |
| Options flow | Yes | `test_options_flow` |
| Setup success: rotation + `runtime_data` | Yes | `test_setup_entry_refreshes_token`, `test_setup_entry_keeps_refresh_token_when_not_rotated` |
| Setup `ConfigEntryAuthFailed` / `ConfigEntryNotReady` | Yes | `test_setup_entry_auth_failure`, `test_setup_entry_connection_failure`, `test_setup_entry_unexpected_failure` |

### Scenario assessment — architecture §5.1 (error mapping)

| Condition | Expected | Covered | Evidence |
|-----------|----------|---------|----------|
| 401 | refresh once, retry; still failing → `SomTodayAuthError` | Yes | `test_get_students_401_refreshes_and_retries`, `test_get_students_401_retry_still_401` |
| 403 | `SomTodayAuthError` | Yes | `test_get_students_auth_error` |
| 429 | `SomTodayRateLimitError` | Yes | `test_get_students_rate_limit` |
| 5xx | `SomTodayApiError` | Yes | `test_get_students_server_error` |
| Network / timeout | `SomTodayConnectionError` | Yes | `test_get_students_connection_error`, `test_get_students_body_read_error` |
| Malformed JSON / schema | `SomTodayApiError` | Yes | `test_get_students_non_json_body`, `test_get_students_invalid_json` |
| Refresh failure during retry | propagate `SomTodayAuthError` | Yes | `test_get_students_401_refresh_failure_propagates` |
| Response lifecycle (all paths) | release exactly once | Yes | B2/N5/G probes and regression tests |

---

## Findings

All previously reported blocking/defect findings are resolved. What remains are
non-blocking carry-over items from `docs/review.md` and defensive/inert coverage
branches that belong to later slices.

### G — `async_get_schools` error-path response leak — FIXED

The status check (`_raise_for_error_status`) is now inside the `try` whose
`finally` releases the response (`auth.py:97-114`). Independent probe confirms
500/429/403/404 and invalid-JSON responses each release exactly once. The
strict-xfail marker was removed; `test_get_schools_releases_error_response`
passes as a normal regression test.

### B — Production `assert` statements in `_async_create_entry` (Low, carry-over)

`config_flow.py:386-388` still guards flow state with `assert`. Stripped under
`python -O`; raises `AssertionError` instead of a domain error. Unreachable
through the UI; reviewer concurred non-blocking.

### C — `async_step_student` `no_students` branch unreachable via the UI (Info, carry-over)

The `SelectSelector` rejects unknown ids with `InvalidData` before the step runs,
so `config_flow.py:266` stays defensive-only (still uncovered).

### D — `async_step_reauth` `entry is None` branch unreachable via the UI (Info, carry-over)

`flow.async_init(SOURCE_REAUTH, entry_id="does-not-exist")` raises
`UnknownEntry` before the handler; `config_flow.py:286->290` remains a defensive
partial branch.

### N13 — Runtime token rotation is not persisted (Low, handover)

`__init__.py:74-77` persists only the rotation performed during setup. A later
reactive `async_refresh()` inside `api.py` (401 retry) rotates in memory with no
write-back. Unreachable today (no coordinator/API polling after setup); must be
owned by the coordinator.

### N14 — Options changes do not trigger a reload (Low, handover)

`SomTodayOptionsFlow` subclasses plain `OptionsFlow`, so saving options does not
reload the entry. Options have no effect yet in this slice; the coordinator
slice should use `OptionsFlowWithReload` / an update listener.

### N15 — `manifest.json` `integration_type` is `hub` (Info, metadata)

Reviewer suggests `service` is the accurate classification for a cloud service.
Metadata-only; the test asserts the current value `hub`.

### Other carry-overs (non-blocking, from `docs/review.md`)

N10 (`from_entry` bare `KeyError` on a malformed entry), the step-2 `GET /`
status not being checked, N17 (broad `_LOGGER.exception` + `unknown`), N18
(options `bool` fields `vol.Required`), and N1 (OAuth2 `state` not validated).
All remain non-blocking and outside this slice.

### Remaining coverage gaps (defensive/inert)

- `__init__.py:88->89`, `99` — `PLATFORMS = []` in this slice, so platform
  forwarding/unloading is never called. Will be covered with the entity slice.
- `config_flow.py:161->176` — re-entering `async_step_user` with `_schools`
  cached is not reachable in a single flow.
- `config_flow.py:266`, `286->290` — findings C and D.

---

## Blockers

1. **Real-account validation outstanding (carried over).** N7
   (`offline_access`/refresh-token issuance) and the architecture §12.2
   refresh-host pairing can only be confirmed against a real SomToday account;
   calling the real API in tests is prohibited.
2. **No coordinator/entity modules exist yet** (`coordinator.py`, `sensor.py`,
   `binary_sensor.py`, `calendar.py`, `entity.py`). Their tests are out of scope
   for this run; N13/N14 are handover items for that slice.

There are no test blockers: the suite is fully green (127 passed, 0 xfailed,
0 skipped) and no test requires a production change to pass.

---

## Previously verified auth slice (summary)

The OAuth2 authentication layer (`auth.py`, `models.py` token/school models,
`exceptions.py`, `const.py`) was verified in an earlier run. Its 47 original
tests still pass, and the N5 response-release hardening added 3 more, plus the
G regression test, bringing `test_auth.py` to 51 tests. `auth.py` is at
**100% line and branch coverage**. The prior review blockers B1–B4/F1/F2 remain
fixed and covered.

---

## Changes made by the tester (cumulative)

**No production code was modified by the tester at any point.** The current
suite state was reached as follows:

- The tester's earlier runs added the config-flow/API/model/translations/manifest
  tests, the `FakeResponse.release_count` counter in `conftest.py`, and the
  strict-xfail regression tests for findings A and G.
- The engineer then fixed those findings and removed the markers; the
  corresponding tests are now ordinary passing regression tests.
- This run performed independent verification only and added **no new tests**,
  because no new genuine gap was found (all release paths release exactly once;
  no double-release; no regression).
- `docs/test-report.md` was rewritten for the final state.

No existing test was weakened or removed.

### Test-quality assessment and gate

| Criterion | Result |
|-----------|--------|
| Minimum 80% coverage | **Met** — 99% line, 99% branch |
| All tests pass | **Met** — 127/127, no xfails, no skips |
| Error scenarios tested | **Met** — §5.1 mapping, setup exceptions, reauth reload, student parsing, response lifecycle |
| No production code modified | **Met** |
| No test removed | **Met** |

**Final verdict:** B1 (reauth reload), B2 (401 response release), N5 (auth
response release) and G (school-list error-path release) are independently
confirmed fixed with regression tests and independent probes. `api.py` and
`auth.py` are at 100% line/branch; the whole slice is at 99% line/branch with
127/127 tests passing. **The 80% gate is met with room to spare.**
