# Review — SomToday config-flow / API / integration-setup slice (final)

> Reviewer: reviewer-agent (per `AGENTS.md`).
> Date: 2026-09-11 (final post-fix re-review: B1/B2/N5/G).
> Scope: `config_flow.py` (user/credentials/student/reauth/options),
> `api.py` (`async_get_students`, 401 refresh+retry, error mapping, response
> release), `auth.py` (response lifecycle), `__init__.py`
> (`async_setup_entry`/`async_unload_entry`/`runtime_data`, token rotation,
> `ConfigEntryAuthFailed`/`ConfigEntryNotReady`, empty `PLATFORMS`),
> `models.py` additions (`Student`, `parse_students`), `manifest.json`,
> `strings.json`, `translations/en.json`, `translations/nl.json`, `pytest.ini`;
> tests `test_config_flow.py`, `test_api.py`, `test_translations.py`,
> `test_manifest.py`, plus the `test_auth.py` lifecycle tests.
> Sources of truth: `docs/architecture.md` (§4, §5.1, §7.3, §9) and
> `docs/test-report.md` (final).
> Method: independent re-read of every file in scope, re-run of the suite and
> lint, source-level inspection of the installed Home Assistant 2026.9.1
> framework, and fresh black-box probes of the reauth and response-release
> paths (outside the repository). **No production code was modified.**

Commands reproduced independently:

```sh
/var/.../sometoday-venv/bin/python -m pytest tests/ -q \
  --cov=custom_components/sometoday --cov-branch --cov-report=term-missing
/var/.../sometoday-venv/bin/python -m ruff check custom_components tests
rg "xfail|skipif|pytest.mark.skip" tests/
```

Observed: **127 passed, 0 failed, 0 xfailed, 0 skipped**, line coverage **99%**
(677 statements, 3 missed), branch coverage **99%** (144 branches, 5 partial),
`ruff` clean. Per-file: `test_auth.py` 51, `test_models.py` 29,
`test_config_flow.py` 28, `test_api.py` 16, `test_translations.py` 2,
`test_manifest.py` 1. This matches `docs/test-report.md` exactly.

---

## Summary

All previously blocking issues (**B1** reauth no-reload, **B2** 401 response
leak) and the follow-up lifecycle issues (**N5** auth response release, **G**
school-list error-path release) are **fixed, independently verified, and covered
by regression tests**. There are **no remaining blocking issues**.

- The suite is fully green with no `xfail`/`skip` markers anywhere.
- `api.py` and `auth.py` are at **100% line and branch coverage**; the whole
  slice is at 99% line/branch, with the only gaps being defensive branches and
  the empty-`PLATFORMS` code paths reserved for the entity slice.
- Documentation (`docs/architecture.md`, `AGENTS.md`, `docs/CHANGELOG.md`,
  `docs/test-report.md`) is current, with two trivial nits noted below.

The previously approved auth slice is unchanged and still passes (its original
47 tests, now 51 with the lifecycle additions). Its open non-blocking items
(N1 state validation, N7 real-account validation, N10 `from_entry` missing-key)
carry over unchanged.

**Verdict: approve.** The slice is ready to be tagged/released for deploy and
testing. The remaining items are non-blocking and must be scheduled with the
coordinator/entity slice (N13/N14 become mandatory there).

---

## Blocking issues

**None.** Both previous blockers are resolved; no new blocker was introduced.

---

## Independent confirmation of the fixes

Each fix was verified by reading the production code **and** by a fresh
black-box probe, not by trusting the test names.

| ID | Fix | Independent verification | Verdict |
|----|-----|--------------------------|---------|
| **B1** | Reauth uses `async_update_reload_and_abort(entry, data_updates=auth.as_entry_data(), reason="reauth_successful")` (`config_flow.py` 317–321) | Fresh probe (real HA harness): drive an entry to `SETUP_ERROR` via `async_ensure_valid` → `SomTodayAuthError`, then run the reauth flow → `REAUTH: abort reauth_successful`, `REFRESH_TOKEN: rotated`, **`STATE_AFTER_REAUTH: ConfigEntryState.LOADED`**. `data_updates` preserves tenant/school/username/student. Regression tests `test_reauth_flow_updates_refresh_token` and `test_reauth_after_failed_setup_reloads_entry` both pass and assert `LOADED`. | **FIXED** |
| **B2** | `api.py::_request` calls `_release(response)` on the rejected 401 **before** `async_refresh()` + retry (`api.py` 90–98); `_async_decode` still releases the decoded response in `finally` (169–170) | Probe `FakeSession([401, 200])` → first `release_count == 1`, second `release_count == 1`. Extra probe for the worst case (**401 + refresh failure**): `FIRST_401_RELEASE_ON_REFRESH_FAILURE: 1`, one HTTP call. Old strict `xfail` is now an ordinary passing test. | **FIXED** |
| **N5** | `auth.py` releases every response: authorize/session/username-form/password-form via `try/finally` (261–284, 287–293, 296–307, 330–340), token response (385–433), school list (97–114) | Read every path. Probes: PKCE happy path releases all five responses exactly once; SSO-redirect authorize releases once; token error statuses and invalid JSON release once via the `_parse_token_response` `finally`. No double-release. | **FIXED** |
| **G** | `async_get_schools` moved `_raise_for_error_status` **inside** the `try/finally` (`auth.py` 97–114), so 4xx/5xx/429 responses are released too | Read `auth.py` 97–114: the status check is the first statement inside the `try`. `test_get_schools_releases_error_response` (500 → `release_count == 1`) is a normal passing test; no marker remains. | **FIXED** |

The release helper is duplicated as a small module-level `_release()` in both
`api.py` (33–37) and `auth.py` (57–61). Harmless duplication; a shared util
would be marginally cleaner (non-blocking).

---

## Non-blocking follow-ups

None of the following blocks this slice; the first two become **mandatory** when
the coordinator/entities land.

### Coordinator-slice requirements (currently unreachable)

- **N13 — runtime token rotation is not persisted.** `__init__.py` 74–77 persists
  only the rotation performed during setup. A later reactive `async_refresh()`
  inside `api.py` (401 retry) rotates the token in memory with no write-back.
  Unreachable today: after setup there is no polling and `PLATFORMS` is empty,
  and config-flow rotations are persisted via `as_entry_data()`. The coordinator
  must own persistence (architecture §9).
- **N14 — options changes do not trigger a reload.** `SomTodayOptionsFlow`
  subclasses plain `OptionsFlow`, so saving options does not reload the entry.
  Options have no effect yet. The coordinator slice must use
  `OptionsFlowWithReload` or register an update listener (architecture §4.1).

### Recommended before a public / HACS release

- **N15 — `manifest.json` `integration_type` is `hub`.** SomToday is a cloud
  *service*; `service` is the accurate classification. Metadata-only, no
  functional impact; `test_manifest.py` asserts the current value.
- **N1 — OAuth2 `state` is generated but never validated** (`auth.py` 247,
  `_extract_code`). Low practical risk (server-side flow, undisclosed verifier,
  `Location` header), but it deviates from OAuth2 guidance. Add validation + a
  test before a public release.
- **N10 — `SomTodayTokens.from_entry()` raises a bare `KeyError`** for a missing
  `CONF_REFRESH_TOKEN` (`models.py` 279), and `entry.data[CONF_TENANT_UUID]`
  (`__init__.py` 57) is likewise unguarded outside the `try`. The config flow
  always writes both keys, so a malformed entry is the only trigger; HA then
  reports `SETUP_ERROR`. A domain error (`SomTodayAuthError`) would give a
  cleaner reauth/retry path.

### Low / optional

- **Finding B — production `assert`s in `_async_create_entry`**
  (`config_flow.py` 386–388). Stripped under `python -O`; raises
  `AssertionError` instead of a domain error. Unreachable through the UI
  (credentials always set the state first). Replace with explicit guards or
  `cast` if desired.
- **Step-2 `GET /` status is not checked** (`auth.py` 287–293). The authorize
  and both form steps are checked; the session-establishment GET is not. The
  later steps normally fail, so this is defensive-only.
- **N17 — broad `_LOGGER.exception` + `unknown`** on unexpected errors
  (`config_flow.py` 169, 227, 314, 374). No secret leak (tracebacks omit locals);
  a debug-level `exc_info` would be sufficient.
- **N18 — options `bool` fields are `vol.Required`.** Fine for the UI; a
  `vol.Optional`/`cv.boolean` with defaults would be more robust for partial
  programmatic calls.
- **Test-quality nits (non-blocking):** `test_manifest.py` asserts the exact
  version string `"0.2.0"` (brittle on every bump); `test_translations.py`
  compares leaf keys but not `{placeholder}` sets; `aioresponses` is declared in
  `requirements_test.txt` but unused (the suite uses the hand-rolled
  `FakeSession`/`FakeResponse`).
- **Doc nits (non-blocking):** `docs/CHANGELOG.md` line 46 still says
  "125 tests" while the suite is 127; the illustrative `manifest.json` snippet
  in `docs/architecture.md` §11 (line 721) still shows `"version": "0.1.0"`
  while the real manifest is `0.2.0`.

### Out of scope / cannot be verified here

- **N7 — real-account validation** of `offline_access`/refresh-token issuance
  and the architecture §12.2 refresh host/client-ID pairing. Live calls are
  prohibited; the human must arrange this.
- **Coordinator/entity modules** (`coordinator.py`, `sensor.py`,
  `binary_sensor.py`, `calendar.py`, `entity.py`) do not exist yet and are the
  next slice.

---

## Security assessment

| Area | Result | Notes |
|------|--------|-------|
| Password never persisted | **Pass** | `config_flow.py` reads it into a local and passes it straight to `async_login`; never assigned to `self`, never in `data`/`as_entry_data()`. In-progress HA flows live in memory only (`data_entry_flow.py` has no `Store`). |
| Password never logged | **Pass** | No `print`; credential paths log only `_LOGGER.exception` (traceback without locals) and the auth client's tenant-UUID debug line. Error messages contain no credentials. |
| Refresh-token storage / rotation write-back | **Pass** | Setup and reauth persist via `auth.as_entry_data()` (refresh token + api_url + auth_method), only when changed. Runtime rotation is a documented coordinator handover (N13). Plaintext in `.storage/core.config_entries` is the documented HA limitation. |
| Uniqueness / dedup | **Pass** | `async_set_unique_id(f"{tenant}:{username}")` + `_abort_if_unique_id_configured()` before login. `test_user_flow_duplicate_aborts` covers it. Unique id excludes the student (architecture §12.5 limitation). |
| Hard-coded secrets | **Pass** | Only public client IDs; no keys/tokens. |
| TLS / hosts | **Pass** | All endpoints HTTPS with default verification. |
| OAuth2 `state` validation | **Fail (low risk, N1)** | Generated, never compared. Unchanged; non-blocking, recommended before public release. |
| Shared HA session cookie jar | **Pass with caveat** | `async_get_clientsession(hass)` is HA's shared session, so SomToday's `JSESSIONID` can also land in the global cookie jar. Cookies are host-scoped; cross-domain leakage is not realistic. |

No security-blocking issue found.

---

## Home Assistant best-practices assessment

| Practice | Result | Notes |
|----------|--------|-------|
| `entry.runtime_data` pattern | **Pass** | `SomTodayConfigEntry = ConfigEntry[SomTodayRuntimeData]`; HA deletes `runtime_data` on unload (config_entries.py 1054–1055), so no manual cleanup is needed. |
| `ConfigEntryAuthFailed` vs `ConfigEntryNotReady` | **Pass** | Auth error → reauth; connection/other → retry (`__init__.py` 63–70). Correct mapping. |
| Reauth updates in place | **Pass (fixed)** | Now `async_update_reload_and_abort`; a `SETUP_ERROR` entry recovers to `LOADED` (probe confirmed). |
| `async_unload_entry` | **Pass** | Returns `async_unload_platforms` when platforms exist; `True` otherwise. Correct for the empty `PLATFORMS` slice. |
| Migration stub | **Pass with note** | `async_migrate_entry` returns `True`; `VERSION = 1`. Does not populate `CONF_AUTH_METHOD` for hypothetical pre-B3 entries, but no released schema exists. |
| Options flow | **Pass with note** | Modern `OptionsFlow` (`self.config_entry` auto-injected; the ignored argument is the current pattern). Does not reload (N14, coordinator slice). |
| Unique id / abort reasons | **Pass** | `already_configured` and `reauth_successful` present in `strings.json`. |
| Translation / `strings.json` correctness | **Pass** | `strings.json`, `en.json`, `nl.json` have identical leaf keys; `async_get_translations` loads the English strings. No hard-coded user-facing strings. |
| Manifest / version gate | **Pass with note** | `version` 0.2.0, `domain`, `config_flow`, `iot_class`, `integration_type`, `requirements: []`, `loggers` present. `integration_type` should be `service` (N15). |
| Deployability as a custom component | **Pass with caveats** | Correct `custom_components/sometoday/` layout, valid manifest, `pytest.ini` with `asyncio_mode = auto`. No `hacs.json` (fine for manual deploy; needed for a HACS release). Missing coordinator/entity modules are the next slice. |
| Async correctness / resource lifecycle | **Pass (fixed)** | Every response is released on success and error paths; no double-release. |
| Test isolation | **Pass** | No real network; `FakeSession` raises when exhausted. |

---

## Tester-findings adjudication

| ID | Finding | Adjudication | Status |
|----|---------|--------------|--------|
| **A** | `api._request` leaks the first 401 response | Confirmed independently; elevated to blocking in the previous review. | **Fixed (B2)** |
| **B** | Production `assert`s in `_async_create_entry` | Agree, non-blocking (unreachable, `-O`-stripped). Still present. | Open, non-blocking |
| **C** | `async_step_student` `no_students` branch unreachable | Agree; `SelectSelector` rejects unknown ids first. | Non-blocking |
| **D** | `async_step_reauth` `entry is None` branch unreachable | Agree; HA raises `UnknownEntry` first. | Non-blocking |
| **E** | `Student._extract_id` ignores a single `links` mapping | Agree; documented API uses a list. | Non-blocking |
| **F** | Options-flow `config_entry` argument ignored | Agree — not a bug; `OptionsFlow.config_entry` is auto-injected. | Non-blocking |
| **G** | `async_get_schools` error-path response leak | Agree; confirmed fixed with the status check inside `try/finally`. | **Fixed** |
| **B1** (my review) | Reauth never reloads the entry | Confirmed independently; entry stayed in `SETUP_ERROR`. | **Fixed** |
| **N5** (prior review) | Auth responses never released | Confirmed; every path now releases via `try/finally`. | **Fixed** |

The tester's final report is accurate: counts, coverage, marker removal and
regression tests all reproduce.

---

## Final verdict

**Approve.**

All blocking issues are fixed, independently verified and covered by passing
regression tests:

- **B1** — reauth reloads the entry; a `SETUP_ERROR` entry recovers to `LOADED`
  (probe + `test_reauth_after_failed_setup_reloads_entry`).
- **B2** — the rejected 401 is released before refresh+retry, including the
  refresh-failure path (probe + ordinary passing test; no `xfail`).
- **N5** — every `auth.py` response is released on success and error paths.
- **G** — `async_get_schools` releases 4xx/5xx/429 responses.

The suite is green (127/127, no xfails/skips, 99% line/branch, `ruff` clean),
the docs are current, and the remaining items are non-blocking or belong to the
coordinator/entity slice.

**Release decision:** the slice is **ready to be tagged/released for deploy and
testing** as version `0.2.0`. N13/N14 become mandatory when the coordinator
lands; N15/N1/N10/Finding-B/step-2 should be scheduled before a public/HACS
release (a `hacs.json` would also be needed then).

### Changes since the previous review

- `docs/review.md` rewritten to the final state. B1/B2/N5/G recorded as fixed
  and independently verified; the remaining non-blocking follow-ups and the
  release decision are documented above.

*No production code was modified by this review.*
