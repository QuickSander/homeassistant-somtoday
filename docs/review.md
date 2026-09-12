# Review — SomToday v0.4.0 Model A identity model

> Reviewer: reviewer-agent (per `AGENTS.md`).
> Date: 2026-09-12.
> Scope: the v0.4.0 **Model A identity model** — one config entry per
> `(account_id, student_id)`:
> `config_flow.py` (`VERSION = 2`, `async_step_user` decision table,
> `async_step_student` + `SelectSelector`, shared `_async_finish`, required
> `/account/me` in `_async_identify`, reauth `wrong_account` / `student_removed`,
> `async_migrate_entry`), `const.py` (`unique_id_for`, `CONF_STUDENT_SELECT`),
> `strings.json` + `translations/{en,nl}.json` (`student` step,
> `student_removed`), `manifest.json` 0.4.0, the `__init__.py` re-export, and the
> tests/docs touched by the change. The previously approved v0.3.0 auth/API/model
> slice was re-run but not re-reviewed in depth.
> Sources of truth: `docs/architecture.md` (§1.1, §4, §7.2.1, §10, §12, §14) and
> `docs/test-report.md`.
> Method: independent re-read of every in-scope file; re-run of the suite,
> coverage and lint; source inspection of the installed Home Assistant 2026.9.1
> framework (`ConfigEntry.async_migrate`, `Integration.async_get_component`,
> `_async_current_ids`, `async_set_unique_id`, `_abort_if_unique_id_configured`,
> `async_update_reload_and_abort`); comparison against the reference
> implementation (`jonisnet/ha-somtoday`, current `main`) and the architecture.
> **No production code was modified. No real SomToday API call was made.**

Commands reproduced independently:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m pytest tests/ -q
$V/python -m coverage erase
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch \
  --cov-report=term-missing
$V/python -m ruff check custom_components tests
rg -n "xfail|skipif|pytest.mark.skip|pytest.mark.xfail" tests/ custom_components/
```

Observed: **159 passed, 0 failed, 0 xfailed, 0 skipped**; line coverage **99%**
(635 statements, 2 missed); branch coverage **99%** (158 branches, 6 partial);
`config_flow.py` **100% line + 100% branch**; `const.py` **100%**; `ruff` **clean**
(exit 0); no `xfail`/`skip` marker anywhere. This matches `docs/test-report.md`
exactly. `strings.json` is byte-identical to `translations/en.json`, and all
three translation files expose identical leaf keys (independently flattened).

---

## Summary

The v0.4.0 Model A identity model is **correct, coherent and faithful to
`docs/architecture.md` §1.1**. The composite identity
`unique_id_for(account_id, student_id) == f"{account_id}:{student_id}"` is the
single source of truth shared by the config flow and the migration, is computed
identically in both (`str(account_id)` + `int(student_id)`), and is persisted on
the entry, so it is stable across flows and restarts.

Verified end-to-end from the production code and the HA framework source (not
from test names):

- **Decision table.** 0 students → `no_students` + a freshly minted PKCE/state
  pair; all students configured → `already_configured`; exactly one
  unconfigured → auto-finish; more than one → `async_step_student`. The
  `student` step re-computes the unconfigured set on every render and on submit,
  so a student configured meanwhile is excluded (re-show remaining, or abort if
  none remain).
- **No duplicate entries.** `_async_unconfigured_students()` filters against
  `self._async_current_ids()`, and `_async_finish()` additionally calls
  `async_set_unique_id(...)` + `_abort_if_unique_id_configured()`. `_async_finish`
  has **no suspension point** (`async_set_unique_id` is a coroutine with no
  internal `await`; the abort/create calls are synchronous), so the
  finish path is atomic on the event loop. The concurrent-flow test yields
  exactly one entry and one `already_configured` abort.
- **Reauth semantics.** A genuine account mismatch aborts `wrong_account`; a
  stored student missing from `/leerlingen` aborts `student_removed`; a
  transient `/account/me` failure is retryable `cannot_connect` (form, not
  abort). The student binding cannot be silently rebound: `_async_identify` only
  sets `tokens.account_id`, so `as_entry_data()` omits `student_id`/
  `student_name` and `data_updates` merges over the existing entry data
  (preserving them). `async_update_reload_and_abort` updates + reloads + aborts
  `reauth_successful` (default reason for the reauth source) without touching the
  unique id.
- **Migration.** HA discovers the hook: `ConfigEntry.async_migrate` imports the
  component module (`custom_components.sometoday.__init__`) and checks
  `hasattr(component, "async_migrate_entry")`; `__init__.py:22` re-exports it
  from `config_flow.py`. HA runs migration **before** `async_setup_entry`
  (`config_entries.py:785`) and persists `version = 2`. The composite unique id
  is recomputed from `entry.data[account_id]`/`[student_id]`.
- **Multi-instance / multi-school.** `config_flow: true` + `integration_type:
  "hub"` let the flow run repeatedly; each entry has a distinct composite id and
  its own independently rotated refresh token; the authorize URL omits
  `tenant_uuid`, so the school picker is SomToday's. Scenarios A (one account per
  student) and B (one account, several students) both work.

**There are no blocking issues.** The user's original question is answered
affirmatively: multiple instances can be added, one entry per student is the
correct model for both scenarios, and duplicate prevention holds within an
account. The residual items are documentation/robustness nits and the tester's
already-known low/info findings.

**Verdict: approve with changes** (changes are documentation-only; see the final
verdict).

---

## Blocking issues

**None.**

Considered and ruled out as blockers:

- **Composite identity collision.** The `:` separator is unambiguous for real
  SomToday ids (account id is a UUID/number, student id is an integer), and the
  helper is shared by flow and migration, so no mismatch is possible.
- **Duplicate entries via `raise_on_progress=False`.** No suspension point exists
  between `_abort_if_unique_id_configured()` and `async_create_entry`, and the
  framework guard is independently covered by the concurrency test. Deliberate,
  per architecture §4.1.
- **Migration not discoverable.** Disproved by HA source inspection and by
  `test_setup_entry_migrates_v1_entry`, which drives the real
  `ConfigEntry.async_migrate` hook.
- **Silent student rebinding on reauth.** Disproved: `student_id`/`student_name`
  are not in `as_entry_data()` for a fresh exchange and `data_updates` merges.
- **`/account/me` required.** Correct for Model A (see the dedicated section
  below).

---

## Non-blocking findings

Ordered by value. `M` = identity-model findings; carry-overs from the v0.3.0
review keep their original `R`/`T` identifiers.

### M1 — README still documents the removed `/account/me` fallback (Medium, docs)

`README.md:69-71` says Home Assistant "reads `/rest/v1/account/me` (falling back
to `/rest/v1/leerlingen`)". That fallback was **removed by the F1 fix** and is
the opposite of the new contract (`config_flow.py:359-380`; architecture §1.1).
`README.md:7` also still says "Current status: authentication only (v0.3.0)",
and the README never mentions the new student-selection step or the
one-entry-per-student model. Because AGENTS.md makes documentation part of every
change, this must be corrected before the release is announced. Documentation
only; no runtime impact.

### M2 — `Account.id` takes the first link, not the `rel == "self"` link (Low, identity robustness)

`models.py::_first_link_id` (lines 46-53) returns the first `links[*]` entry that
has an `id`, regardless of `rel`. `Student._extract_id` (lines 113-128) prefers
`rel == "self"`, and the reference implementation's `_account_unique_id` requires
`rel == "self"`. Since `account_id` is now half of the persisted unique id, a
payload whose first link is not the account self-link would produce a
different/unstable account id. `test_parse_account_uses_first_link` codifies the
first-link behaviour, and architecture §7.3 specifies `links[0].id`, so the code
follows the spec — but the spec and the `Student` parser disagree with the
reference. Recommend confirming a real `/account/me` payload (tester blocker #1)
and, if it has multiple links, aligning with `Student`/the reference by
preferring `rel == "self"`. Low probability, non-blocking.

### M3 — A v0.3.0 entry created via the old fallback cannot be repaired by migration (Low)

v0.3.0's `_async_identify` set `account_id = str(students[0].id)` when
`/account/me` failed, so such an entry stored a **student id as the account id**.
Migration faithfully computes `unique_id_for("1234", 1234) == "1234:1234"`, but
reauth then compares the real account id (e.g. `account-1`) to
`entry.data[account_id] == "1234"` and always aborts `wrong_account`. Migration
cannot recover the true account id without a network call. Only affects users
who installed v0.3.0 while `/account/me` was unavailable. Non-blocking; worth a
release note ("delete and re-add entries that show `wrong_account` after
upgrading").

### M4 — Migration raises on a non-numeric stored `student_id` (Low)

`config_flow.py:93` does `int(student_id)`. A hand-edited/corrupt v1 entry with
`student_id = "abc"` raises `ValueError` inside `async_migrate_entry`; HA catches
it (`config_entries.py:1204-1208`), logs, and marks the entry
`MIGRATION_ERROR`. The missing-`student_id` case is handled; the malformed case
is not. Consider `try/except` with the existing `str(account_id)` fallback.
Defensive only.

### M5 — Migration does not bump versions below 1 (Info)

`async_migrate_entry` only acts on `entry.version == 1` and returns `True` for
everything else. An entry with `version == 0` is never bumped, so HA re-runs the
(no-op) migration on every setup. No error, just repeated work. Consider
`if entry.version < SomTodayConfigFlow.VERSION:`.

### M6 — `config.error.wrong_account` is unused (Info; tester F3)

Reauth aborts with `async_abort(reason="wrong_account")`, resolved by
`config.abort.wrong_account`. The identical `config.error.wrong_account` key
(`strings.json:43`) is never selected. Harmless duplication; remove or leave.

### M7 — `_async_current_ids(include_ignore=True)` counts ignored entries (Info; tester F4)

HA's `_async_current_ids()` defaults to `include_ignore=True`
(`config_entries.py:3251-3258`), while `_abort_if_unique_id_configured` allows a
`SOURCE_USER` flow to re-configure an ignored entry
(`config_entries.py:3189-3190`). An ignored entry with a composite unique id
would therefore suppress re-adding that student. This integration has no
discovery/ignore step (`manifest.json` declares no discovery and the flow has no
`async_step_dhcp`/`zeroconf`/`ssdp`), so the branch is unreachable. Agree with
the tester: Info, no defect.

### M8 — `raise_on_progress=False` deviates from the HA default (Info)

`config_flow.py:399-401` passes `raise_on_progress=False`, disabling HA's
`already_in_progress` guard (`config_entries.py:3206-3213`). Architecture §4.1
mandates it, and no duplicate is reproducible (no suspension point; concurrency
test). Observation only. Using the default `True` would be marginally more
defensive at the cost of aborting the second of two parallel flows with a less
specific reason.

### M9 — Production `assert`s in the config flow (Info; carry-over)

`config_flow.py:211` (`_account_id is not None`) and `395-396`
(`_tokens`/`_account_id is not None`) are stripped under `python -O`. Both are
unreachable because the attributes are always set before the step runs. Replace
with explicit guards or `cast` if desired. Unchanged from the prior review.

### M10 — Reauth uses `self.context["entry_id"]` instead of `_get_reauth_entry()` (Info; carry-over)

`config_flow.py:247-249` fetches the entry manually. Works (reauth always sets
the context) but is less idiomatic than HA's `self._get_reauth_entry()`. Also,
if the entry were deleted mid-flow, the flow re-shows the form forever instead
of aborting. Very low probability.

### M11 — Cross-account duplicate of the same student, and imprecise doc wording (Info)

Because identity is the pair, the **same student under two different accounts**
gets two distinct unique ids and can be added twice
(`test_unique_id_for_distinguishes_accounts_for_one_student`). Architecture §1.1
and `CHANGELOG.md` say "the same student still cannot be added twice", which is
true only within one account. The behaviour is intentional (each account has its
own session/refresh token) and matches the stated Model A, but the wording should
be qualified. No action required beyond the doc clarification.

### M12 — Documentation nits (Info)

- `README.md:7` status is `v0.3.0` (should be `v0.4.0`).
- `docs/CHANGELOG.md:51` says "Total: 151 tests"; the suite is **159**.
- `docs/CHANGELOG.md:99` (0.3.0) says "140 tests", while the v0.3.0 review and
  test-report recorded 135. Pre-existing.
- The README does not document the `student` step, the one-entry-per-student
  model, or the `student_removed` troubleshooting case.
- `manifest.json` keeps `integration_type: "hub"`; the prior review suggested
  `"service"`. Architecture §1.1 explicitly chooses `hub` (it enables repeat
  config flows), so this is now intentional — no change needed.

### M13 — Account id and student name are logged at INFO (Info, privacy)

`__init__.py:74-78` logs the student name and account id on every setup/reload.
No token or secret is logged (independently re-confirmed: the test asserts the
refresh token is absent from the log). This is PII, not a credential; acceptable
for diagnostics, but worth noting for privacy-sensitive users.

### Carry-over findings from v0.3.0 (unchanged, non-blocking)

These are unrelated to the identity model and were not touched by this change:

- **R2** — redirect `error=` is not handled (generic `invalid_url`).
- **R3** — `SomTodayTokens.from_token_response` accepts a null/empty access token.
- **R4 / T3** — `403` maps to `SomTodayAuthError` and will force reauth once the
  coordinator exists; the reference treats `403` as retryable.
- **R5** — `SomTodayTokens.from_entry` raises a bare `KeyError` on a malformed
  entry.
- **R7 / T6** — concurrent forced `async_refresh()` calls are not deduplicated.
- **R8** — runtime token rotation is only persisted during setup/reauth.
- **R12** — dead `_LOGGER` definitions.
- **T4** — `/account/me` omits `additional=restricties` (harmless; the id comes
  from `links`).
- **T7–T9** — low-probability paste edge cases (bare `code=` fragment, quoted
  `Location:`, multiple `Location:` lines).

---

## Security assessment

| Area | Result | Notes |
|------|--------|-------|
| Password / client secret | **Pass** | No `password` or `client_secret` anywhere in the component. Browser PKCE only. |
| Authorization code handling | **Pass** | Exchanged once; never stored on the entry or logged. |
| PKCE verifier / `state` | **Pass** | In-memory per flow; regenerated on a spent code and on `no_students`; never persisted/logged. |
| Refresh-token storage | **Pass with caveat** | Plaintext in `.storage/core.config_entries` (documented HA limitation). Each entry owns its own rotated token. |
| No secret/token logging | **Pass** | INFO logs only student name + account id; the token-absence assertion passes. `api._log_error_summary` logs only bounded response metadata at debug. |
| Composite unique id | **Pass** | Not a secret; contains account/student ids already known to HA. `:` separator cannot be confused with real ids. |
| Reauth account binding | **Pass** | `wrong_account` abort prevents an entry being rebound to another account; student binding is preserved on success. |
| Shared HA session | **Pass with caveat** | `async_get_clientsession(hass)`; SomToday cookies are host-scoped. |
| Migration | **Pass** | Only unique id + version change; no data written from untrusted input. Malformed input cannot inject (see M4 for the MIGRATION_ERROR edge). |
| Broad `except Exception` | **Pass** | Logs a traceback without locals and shows `unknown`. |

No security-blocking issue found.

---

## Home Assistant best-practices assessment

| Practice | Result | Notes |
|----------|--------|-------|
| Composite unique id + `_abort_if_unique_id_configured` | **Pass** | Shared helper; abort reason `already_configured`; concurrency test. |
| `_async_current_ids()` usage | **Pass with note** | Correct for filtering unconfigured students; default `include_ignore=True` is unreachable here (M7). |
| `async_set_unique_id(..., raise_on_progress=False)` | **Pass with note** | Deliberate per architecture; no duplicate reproducible (M8). |
| `async_step_student` + `SelectSelector` | **Pass** | `SelectSelectorConfig(options=[{"value": str(id), "label": name}])`; string values compared with `str(student.id)`; sorted by `(display_name, id)`. Valid and usable. |
| Decision table | **Pass** | Matches architecture §4.1 exactly (0/≥1, 0/1/>1). |
| Reauth in place | **Pass** | `async_update_reload_and_abort(entry, data_updates=..., reason="reauth_successful")`; preserves unique id and student binding; recovers `SETUP_ERROR` → `LOADED`. |
| `wrong_account` / `student_removed` / retryable | **Pass** | Genuine mismatch aborts; transient failure is `cannot_connect`; missing student aborts `student_removed`. No silent rebinding. |
| Migration hook | **Pass** | Re-exported from `__init__.py`; discovered by `Integration.async_get_component()`; runs before setup; `version` persisted; covered by the real HA hook test. |
| Translation parity | **Pass with note** | `strings.json` == `en.json` byte-for-byte; all three files have identical leaf keys and load in HA. `config.error.wrong_account` unused (M6). |
| Manifest / version | **Pass** | `domain`, semver `0.4.0`, `config_flow`, `iot_class: cloud_polling`, `integration_type: hub`, empty `requirements`, `loggers`. |
| Options flow + reload | **Pass** | Unchanged, still schedules a reload. |
| Async resource lifecycle | **Pass** | Responses released on success/error; unchanged. |
| Test isolation | **Pass** | All HTTP mocked; no marker skips; `ruff` clean. |

---

## Tester-findings adjudication

| ID | Tester claim | My adjudication | Status |
|----|--------------|-----------------|--------|
| **F1** | Account-id fallback misidentified the account | **Confirmed fixed.** `/account/me` is required; `_async_identify` returns non-optional `tuple[str, list[Student]]`; `SomTodayError` propagates to retryable `cannot_connect`. Reproduced from source and the regression tests. | **Fixed** |
| **F1b** | Duplicate student via the fallback | **Confirmed fixed.** A failing `/account/me` cannot compute a student-based unique id; the pre-existing entry is the only one. | **Fixed** |
| **F2** | Migrated entry without a student id is un-reauthable | **Agree, Low, non-blocking.** `student_id is None` → reauth `any(student.id == None)` is False → `student_removed`. Only malformed/hand-edited v1 entries. I add the adjacent **M3** (v0.3.0 fallback stored a student id as the account id) and **M4** (non-numeric id → `MIGRATION_ERROR`). | Open, non-blocking |
| **F3** | `config.error.wrong_account` unused | **Agree, Info.** Reauth aborts (resolved via `config.abort.wrong_account`); the error key is never selected. Harmless. | Open, non-blocking |
| **F4** | `_async_current_ids(include_ignore=True)` counts ignored entries | **Agree, Info, unreachable.** No discovery/ignore step exists in this integration. Confirmed against `config_entries.py:3251` and `:3189`. | Open, non-blocking |
| `raise_on_progress=False` | No defect | **Agree.** HA source confirms the guard is disabled; the finish path has no suspension point, so exactly one entry is created (concurrency test). Architecture mandates it. | Observation, no defect |
| **T3 / R4** | 403 does not trigger a reactive refresh | **Agree, non-blocking, forward-looking.** Must be settled before the coordinator slice (permission 403 would force reauth). | Open, non-blocking |
| **T4** | `/account/me` omits `additional=restricties` | **Agree, non-blocking.** The id comes from `links`, not from additional objects. | Open, non-blocking |
| **T6 / R7** | Concurrent forced refreshes not deduplicated | **Agree, non-blocking.** `async_ensure_valid()` is lock-deduplicated; only forced refreshes duplicate. | Open, non-blocking |
| **T7–T9** | Paste edge cases | **Agree, by design/low probability.** The UI never instructs those inputs. | Open, non-blocking |
| Production `assert`s | — | **Agree, non-blocking.** Unreachable; stripped under `-O`. | Open, non-blocking |

The tester's report is **accurate**: counts, coverage, marker removal and the
F1/F1b regression tests all reproduce. I found one additional documentation
defect the tester did not list (**M1**, README still documents the removed
fallback) and two migration edge cases (**M3**, **M4**).

---

## Multi-instance / multi-school behaviour (the user's original question)

**Confirmed correct.** Multiple instances can be added and one entry per student
is the right model for both architecture scenarios:

| Scenario | Result |
|----------|--------|
| A — one SomToday account per student, possibly different schools | One entry per account/student; distinct composite ids. The authorize URL omits `tenant_uuid`, so the school picker is SomToday's and works for any school. |
| B — one parent account seeing several students | Flow shows the `student` step for >1 unconfigured students; one entry per child; adding a second child of an already-configured account auto-selects the remaining one and creates a distinct entry. |
| Multiple HA instances of the integration | Allowed by `config_flow: true`; each entry keeps its own refresh token and composite id. |

Within one account the same student cannot be added twice (duplicate filter +
unique-id abort). Across two different accounts the same student can (M11) — the
documented "cannot be added twice" wording should be qualified to "per account".

---

## `/account/me` required vs the reference integration's fallback

**The F1 fix is the right call for Model A.** The reference's fallback is
narrower than it looks and does not contradict this design:

- In `jonisnet/ha-somtoday`, `async_get_account()` and `async_get_students()`
  are in the **same `try`**; an `/account/me` failure returns `cannot_connect`
  and never reaches the fallback. The `_account_unique_id(account) or
  parsed[0].uuid` fallback only applies when `/account/me` **succeeds but has no
  usable self-link**.
- That reference uses a **one-entry-per-account** model (title lists all
  students), so a student-based fallback is harmless there. Under Model A
  (one entry per student), a student-based `account_id` would make the unique id
  change with the student and break reauth/duplicate detection — exactly the
  F1/F1b bug.
- This integration has **no fallback at all**: a 200 response without a usable id
  makes `parse_account` raise, which `api.async_get_account` maps to
  `SomTodayApiError` → retryable `cannot_connect`. That is strictly safer than
  minting an unstable id.

The only residual risk is operational: setup now depends on `/account/me` being
available. The tester's blocker #1 (live validation prohibited) means this cannot
be confirmed against the real service here; the reference makes the same
assumption, so this is acceptable. See **M2** for the related
`rel == "self"` link-selection question.

---

## Final verdict

**Approve with changes.**

- **No blocking issues.** The identity model is correct, stable and free of
  duplicate-entry paths; reauth cannot silently rebind; migration is discovered,
  ordered correctly and persists `version = 2`; multi-instance and multi-school
  both work.
- **Security:** no password/secret, no token/code logging, correct PKCE/`state`,
  refresh token stored under the documented HA caveat.
- **Home Assistant patterns:** composite unique id + abort, `SelectSelector`
  step, `async_update_reload_and_abort`, migration hook, translation parity and
  manifest bump all follow the framework. The only deviations
  (`raise_on_progress=False`, `_async_current_ids` include-ignore) are deliberate
  or unreachable.
- **Tests:** 159/159 pass, 0 xfailed/skipped, 99% line/branch,
  `config_flow.py`/`const.py` 100%, `ruff` clean — independently reproduced.

**Required before release (documentation only):** fix **M1** (README's removed
fallback claim and stale `v0.3.0` status) and **M12** (CHANGELOG test count and
the missing student-selection documentation). Recommended follow-ups, all
non-blocking: **M2** (confirm/link `rel == "self"` selection on `/account/me`),
**M3**/**M4** (migration edge cases), and the tester's **F2** (Low) / **F3**,
**F4** (Info). The v0.3.0 carry-overs (notably **T3/R4**) must be addressed when
the coordinator slice lands.

### Changes made by this review

- `docs/review.md` rewritten for the v0.4.0 Model A identity model.
  **No production code was modified.**
