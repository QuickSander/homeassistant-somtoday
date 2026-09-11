# Review — SomToday v0.3.0 browser authorization-code + PKCE rewrite

> Reviewer: reviewer-agent (per `AGENTS.md`).
> Date: 2026-09-11.
> Scope: `auth.py` (`generate_code_verifier`,
> `code_challenge_from_verifier`, `generate_state`, `build_authorize_url`,
> `extract_code`, `async_exchange_code`, `async_refresh_tokens`,
> `SomTodayAuth`), `config_flow.py` (single paste step, link-regeneration
> policy, account/student identification, duplicate detection, reauth
> `wrong_account` + reload, options reload), `api.py` (`async_get_account`,
> `async_get_students`, 401 refresh+retry, error mapping, response release,
> bounded error diagnostics), `models.py` (`Account`, `Student`,
> `SomTodayTokens`), `exceptions.py` (`SomtodayInvalidAuth`), `const.py`,
> `__init__.py`, `manifest.json`, `strings.json`, `translations/*`, plus the
> test suite.
> Sources of truth: `docs/architecture.md` (§3, §4, §5.1) and
> `docs/test-report.md`.
> Method: independent re-read of every file in scope, re-run of the suite,
> coverage and lint, source inspection of the installed Home Assistant
> 2026.9.1 framework, comparison against the reference implementation
> (`jonisnet/ha-somtoday`) and the community API docs
> (`elisaado/somtoday-api-docs`), and fresh black-box probes of
> `extract_code`, the auth holder and `SomTodayTokens`.
> **No production code was modified. No real SomToday API call was made.**

Commands reproduced independently:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch \
  --cov-report=term-missing
$V/python -m ruff check custom_components tests
rg "xfail|skipif|pytest.mark.skip|pytest.mark.xfail" tests/ custom_components/
```

Observed: **135 passed, 0 failed, 0 xfailed, 0 skipped**; line coverage **99%**
(585 statements, 2 missed); branch coverage **99%** (134 branches, 6 partial);
`ruff` **clean** (exit 0). Per-file collection:
`test_auth.py` 50, `test_models.py` 33, `test_config_flow.py` 29,
`test_api.py` 20, `test_translations.py` 2, `test_manifest.py` 1. This matches
`docs/test-report.md` exactly. No `xfail`/`skip` marker exists anywhere.

---

## Summary

The v0.3.0 browser authorization-code + PKCE rewrite is **sound, secure and
faithful to the chosen reference implementation**. The protocol details were
cross-checked against `jonisnet/ha-somtoday` (the integration the architecture
explicitly follows) and the community API docs:

- The authorize URL **omits `tenant_uuid`** and carries PKCE `S256`, `state`,
  `scope=openid`, `session=no_session` and the exact redirect URI.
- The code-exchange body (`grant_type=authorization_code`, `code`,
  `code_verifier`, `client_id`, `scope`, `session`) matches the reference
  byte-for-byte; neither sends `redirect_uri` or `tenant_uuid` (the docs list
  `tenant_uuid`, but the working reference does not, and the school picker
  handles it). aiohttp sets `Content-Type: application/x-www-form-urlencoded`
  automatically for a `dict` body — independently confirmed against a local
  aiohttp server.
- `state` is validated best-effort when present, exactly as the architecture
  §3.2 specifies; PKCE remains the real protection (the verifier never leaves
  the flow object).
- Rotating refresh tokens are preserved when omitted, and `api_url`/`tenant`
  are carried across a refresh.
- The link-regeneration policy matches the reference's `_SPENT_LINK_ERRORS`
  behaviour: the authorize URL is kept on a recoverable paste mistake and
  regenerated only once a code has been spent.

**There are no blocking issues.** The user's goal — deploy this release into
Home Assistant and exercise the authorization against the real service — is not
blocked by any finding in this review.

The suite is green, `auth.py`/`config_flow.py`/`models.py` are at 100% line
coverage (`api.py` also 100% line), and the only coverage gaps are defensive
branches. The residual items are non-blocking correctness/robustness nits, two
documentation/spec divergences, and forward-looking concerns for the
coordinator slice.

**Verdict: approve** (with non-blocking follow-ups; see the final verdict).

---

## Blocking issues

**None.**

Specifically, the following were considered as potential blockers and ruled
out:

- **Missing `redirect_uri`/`tenant_uuid` in the token-exchange body.** Ruled
  out: the reference implementation sends exactly this body and omits both
  parameters; the architecture §3.2 step 5 specifies the same. The token
  endpoint is the native-app public client, which does not require them.
- **Missing explicit `Content-Type`.** Ruled out: aiohttp sets
  `application/x-www-form-urlencoded` for a `dict` body (verified against a
  live local aiohttp server).
- **`state` best-effort rather than strict.** Ruled out by design: the
  architecture §3.2 step 4 specifies best-effort, and strict enforcement would
  break the explicitly supported bare-code paste path. PKCE binds the code to
  the flow.
- **Token/secret leakage.** Ruled out: no token, code, verifier or password is
  logged or persisted except the refresh token (the documented HA plaintext
  limitation).

---

## Non-blocking findings

These do **not** block deployment or the authorization test. They are ordered
by value; the first two are the only ones I would schedule before a wider
public release.

### R1 — Documentation/code divergence on `state` mismatch (Low)

`docs/architecture.md` §5.1 and the `exceptions.py` docstring say a `state`
mismatch raises `SomtodayInvalidAuth` and surfaces as `invalid_auth`.
`auth.py::extract_code` (lines 142–155) actually raises `ValueError
("state_mismatch")`, and `config_flow.py` (lines 250–251) maps it to the
`state_mismatch` error key. The implemented behaviour is the **better UX** and
is covered by tests; the docs are stale. Recommend updating §5.1 and the
`SomtodayInvalidAuth` docstring to match the code (or, less desirable, the
code to match the docs). Documentation-only.

### R2 — Redirect `error=` is not handled (Low)

`extract_code` has no handling for an OAuth2 error redirect such as
`somtoday://…?error=access_denied&state=…`. Probe result: it falls through to
`no_code`, which the flow shows as the generic `invalid_url`
("Could not find an authorization code"). The reference implementation raises
`redirect_error:<code>` and can surface a specific message. Recommend adding an
`error=` branch and a dedicated translation key. UX only; does not block the
happy path.

### R3 — `SomTodayTokens.from_token_response` accepts a null/empty access token (Low)

`models.py` line 222 does `str(payload["access_token"])`, so a response with
`"access_token": null` yields the literal string `"None"`, and `""` yields an
empty bearer token. Probe confirmed both. The reference explicitly rejects a
falsy `access_token`. Recommend raising `ValueError` when the access token is
missing or empty. Real SomToday responses always carry one, so this is
defensive only.

### R4 — `403` maps to `SomTodayAuthError` and would force reauth in the coordinator slice (Low, forward-looking)

`api.py::_request` refreshes only on `401`; `_async_decode` (lines 161–165)
maps `403` to `SomTodayAuthError`. `docs/architecture.md` §5.1 says `401`/`403`
should refresh once. In this slice the data API is only called from the config
flow, where `SomTodayError` is caught, so a `403` cannot trigger reauth today.
When the coordinator lands, a permission-related `403` on a data endpoint would
become `ConfigEntryAuthFailed` and prompt an unnecessary reauth. The reference
deliberately treats `403` as a retryable permission error (`SomTodayApiError`),
never reauth. Recommend aligning before the coordinator slice. (Tester T3 is the
same observation.)

### R5 — `SomTodayTokens.from_entry` raises a bare `KeyError` on a malformed entry (Low, carry-over N10)

`models.py` line 264 reads `data[CONF_REFRESH_TOKEN]` unguarded. A config entry
missing that key makes `async_setup_entry` fail with an unhandled `KeyError`
rather than a domain error, so HA reports `SETUP_ERROR` with no reauth path.
The flow always writes the key, so only a hand-edited/corrupt entry triggers
it. Recommend a domain error (`SomTodayAuthError`) for a clean reauth/retry
path.

### R6 — `async_set_unique_id(..., raise_on_progress=False)` weakens concurrent duplicate protection (Info)

`config_flow.py` line 159 passes `raise_on_progress=False`. The HA convention
(and the reference) is the default `True`, which aborts a second in-progress
flow for the same unique id. With `False`, two simultaneous add-integration
flows for the same account can both reach `_abort_if_unique_id_configured()`
before either is configured. `_abort_if_unique_id_configured()` still catches
the sequential case (tested). Minor race only.

### R7 — Forced `async_refresh()` is not deduplicated (Info, tester T6 confirmed)

Two concurrent `async_refresh()` calls issue two token requests (probe: 2
calls). `async_ensure_valid()` is correctly deduplicated by the lock (3
concurrent callers → 1 request, tested). With rotating tokens this is correct,
just wasteful; only relevant once concurrent API calls exist.

### R8 — Runtime token rotation is not persisted outside setup (Info, carry-over N13)

`__init__.py` lines 72–77 persist the rotation performed during setup. A later
reactive `401` refresh inside `api.py` rotates the token in memory with no
write-back. Unreachable today (no coordinator, no post-setup API calls) and
config-flow rotations are persisted via `as_entry_data()`. The coordinator must
own persistence.

### R9 — Documentation nits (Info)

- `docs/CHANGELOG.md` line 49 says "131 tests"; the suite is 135.
- `docs/architecture.md` §11 manifest snippet still shows `"version": "0.2.0"`
  (real manifest: `0.3.0`).
- `docs/architecture.md` §10 constants snippet uses `CLIENT_ID` and omits
  `CLIENT_ID_APP`/`PKCE_CHARSET`/`SESSION_NO_SESSION`/`CODE_VERIFIER_LENGTH`/
  `STATE_LENGTH`/`REQUEST_TIMEOUT`, all of which exist in `const.py`.

### R10 — `manifest.json` `integration_type` is `hub` (Info, carry-over N15)

SomToday is a cloud *service*; `service` is the accurate classification.
Metadata-only, no functional impact. `test_manifest.py` currently pins
`"hub"`, so the test must change with the manifest.

### R11 — Test-quality nits (Info)

- `aioresponses` is declared in `requirements_test.txt` but unused (the suite
  uses the hand-rolled `FakeSession`/`FakeResponse`).
- `test_translations.py` compares leaf keys but not `{placeholder}` sets, so a
  missing `{auth_url}` in `nl.json` would not be caught by the parity test
  (the EN load test does check `{auth_url}`).
- `test_manifest.py` pins `integration_type == "hub"` (see R10).

### R12 — Dead `_LOGGER` definitions (Info)

`auth.py` line 58 and `__init__.py` line 28 define `_LOGGER` but never use it.
Harmless.

### R13 — `async_step_reauth` uses `self.context["entry_id"]` (Info)

`config_flow.py` lines 176–178 fetch the entry via
`self.hass.config_entries.async_get_entry(self.context["entry_id"])` instead of
the modern `self._get_reauth_entry()`. Works (reauth always sets the context),
slightly less idiomatic.

### R14 — Production `assert`s in the config flow (Info, carry-over Finding B)

`config_flow.py` lines 161 and 194 use `assert self._tokens is not None`.
Stripped under `python -O`; unreachable because `_tokens` is assigned before
the return. Replace with an explicit guard or `cast` if desired.

### Out of scope / cannot be verified here

- **Real-account validation** of the live authorize/token endpoints, the
  refresh-token rotation behaviour and the architecture §12.1 token-host
  pairing. Live calls are prohibited; the human must arrange this. This is the
  same blocker the tester reports.
- **Coordinator/entity modules** (`coordinator.py`, `sensor.py`,
  `binary_sensor.py`, `calendar.py`, `entity.py`) do not exist yet; their
  review is the next slice.

---

## Security assessment

| Area | Result | Notes |
|------|--------|-------|
| Password never requested/stored/logged | **Pass** | No `password` reference in the component (grep). The flow is browser-based; HA never sees a credential. |
| Authorization code handling | **Pass** | `extract_code` returns it for a one-shot exchange; never assigned to the entry, never logged. |
| PKCE verifier handling | **Pass** | 128 chars from the documented app alphabet via `secrets.choice`; S256 challenge; stored only on the in-memory flow object; never persisted/logged. |
| `state` handling | **Pass (best-effort, by design)** | Generated per flow (`secrets`, 32 alphanumeric chars ≈ 190 bits) and compared with `unquote` when the paste carries one. PKCE is the binding control; strict state would break the supported bare-code paste. |
| Refresh-token storage / rotation | **Pass with caveat** | Persisted in `entry.data` (plaintext in `.storage/core.config_entries` — the documented HA limitation). Rotation persisted at setup and reauth; runtime rotation gap is R8. |
| No secret/token logging | **Pass** | No token/code/verifier appears in any log message. `api.py::_log_error_summary` logs only a bounded (500/200 char) response `Location`/body at `debug`, never request headers. `config_flow.py` uses `_LOGGER.exception` (traceback without locals) and a debug account fallback. |
| Hard-coded secrets | **Pass** | Only the public OAuth2 client id (`somtoday-leerling-native`); no client secret, keys or tokens. |
| TLS / hosts | **Pass** | All endpoints are HTTPS with default verification. |
| Shared HA session cookie jar | **Pass with caveat** | `async_get_clientsession(hass)` is HA's shared session; SomToday cookies (e.g. `JSESSIONID`) are host-scoped, so cross-domain leakage is not realistic. No login-form scraping means no session cookies are actually needed. |
| Exception/log injection | **Pass** | The pasted value is never interpolated into logs; only fixed reason strings are raised/translated. |
| Broad `except Exception` | **Pass** | Catches only truly unexpected errors, logs a traceback (no locals) and shows `unknown`. |

No security-blocking issue found.

---

## Home Assistant best-practices assessment

| Practice | Result | Notes |
|----------|--------|-------|
| `entry.runtime_data` pattern | **Pass** | `SomTodayConfigEntry = ConfigEntry[SomTodayRuntimeData]`; HA clears `runtime_data` on unload, so no manual cleanup. |
| `ConfigEntryAuthFailed` vs `ConfigEntryNotReady` | **Pass** | `SomtodayInvalidAuth` → reauth; connection/other `SomTodayError` → retry (`__init__.py` 64–67). Correct. |
| Reauth in place | **Pass** | `async_update_reload_and_abort(entry, data_updates=…, reason="reauth_successful")`; a `SETUP_ERROR` entry recovers to `LOADED` (test `test_reauth_after_failed_setup_reloads_entry`). |
| Reauth `wrong_account` | **Pass** | Manual `account_id != entry.unique_id` compare aborts with `wrong_account`; correct because reauth never sets a unique id (T5 is the unreachable `unique_id is None` case). |
| Duplicate detection / unique id | **Pass with note** | `async_set_unique_id(account_id)` + `_abort_if_unique_id_configured()` → `already_configured` (tested). `raise_on_progress=False` is a minor deviation (R6). |
| Options flow + reload | **Pass** | Modern `OptionsFlow` (`self.config_entry` auto-injected); saving calls `async_schedule_reload(entry.entry_id)` (tested). No update listener, per architecture §4.1. |
| Config-flow UX (authorize link, DevTools guidance) | **Pass** | The authorize URL is an `{auth_url}` placeholder; the description gives both the address-bar and Chrome DevTools `Location:` methods; a bare code is accepted. |
| Link-regeneration policy | **Pass** | Kept on recoverable paste errors (`invalid_url`/`login_page`/`state_mismatch`); regenerated once a code is spent or the failure is non-paste (tested by `test_authorize_url_kept_on_recoverable_paste` / `test_authorize_url_regenerated_when_spent`). Matches the reference's `_SPENT_LINK_ERRORS`. |
| Async resource lifecycle | **Pass** | Every response is released on success and error paths (token request `finally`, 401 first response, decoded response `finally`); no double-release (tests). |
| Translations | **Pass with note** | `strings.json`/`en.json`/`nl.json` have identical leaf keys and load in HA; `{auth_url}` present in both. Placeholder-set parity is untested (R11). |
| Manifest / version gate | **Pass with note** | `domain`, semver `version` 0.3.0, `config_flow`, `iot_class: cloud_polling`, `integration_type`, empty `requirements`, `loggers` present. `integration_type` should be `service` (R10). |
| Deployability | **Pass** | Correct `custom_components/sometoday/` layout, valid manifest, `hacs.json` with `homeassistant: 2024.11.0`, `pytest.ini` with `asyncio_mode = auto`, README with install/config/troubleshooting. |
| Test isolation | **Pass** | No real network; `FakeSession` raises when exhausted. |

---

## Tester-findings adjudication

I independently re-verified the tester's T1/T2 fixes and adjudicated T3–T9.

| ID | Finding | Adjudication | Status |
|----|---------|--------------|--------|
| **T1** | `extract_code` cookie/header false positive | **Confirmed fixed.** `_LOCATION_RE` prefers the `Location` line and `_CODE_RE`/`_STATE_RE` require a `[?&]` boundary. My probe: `Set-Cookie: state=WRONG` + `Location: …?code=REAL&state=S` → `REAL`. Regression test passes normally. | **Fixed** |
| **T2** | Bare percent-encoded code rejected | **Confirmed fixed.** `extract_code("ABCDEFGH%2FIJ%2BK")` → `ABCDEFGH/IJ+K`; `ABCDEFGH%3D%26` → `ABCDEFGH=&`. Test passes. | **Fixed** |
| **T3** | 403 does not trigger a reactive refresh | **Agree, non-blocking.** `_request` retries only `401`; `_async_decode` maps `403` to `SomTodayAuthError`. Diverges from architecture §5.1 and from the reference (which treats 403 as retryable). Unreachable today; becomes relevant with the coordinator (see **R4**). | Open, non-blocking |
| **T4** | `/rest/v1/account/me` omits `additional=restricties` | **Agree, non-blocking.** The reference also sends no params; the unique id comes from `links[0].id`, so the omission is harmless. | Open, non-blocking |
| **T5** | Reauth wrong-account check skipped when `unique_id is None` | **Agree, non-blocking.** Unreachable for entries created by this flow (they always set a unique id). | Open, non-blocking |
| **T6** | Concurrent forced refreshes not deduplicated | **Reproduced.** 2 concurrent `async_refresh()` → 2 token requests; `async_ensure_valid()` is deduplicated. Correct but wasteful (see **R7**). | Open, non-blocking |
| **T7** | Bare query fragment `code=…` (no `?`) no longer recognised | **Agree, by design.** The `[?&]` boundary is required for the T1 fix; the UI never instructs a bare fragment. | Open, by design |
| **T8** | Quoted `Location:` value not unwrapped | **Reproduced.** `Location: "somtoday://…?code=ABC&state=S"` → `state_mismatch`. DevTools "Copy value" does not add quotes; low probability. | Open, non-blocking |
| **T9** | Multiple `Location:` lines uses the first | **Reproduced.** A login-page `Location` followed by the callback `Location` → `login_page`. Copying the final response works; low probability. | Open, non-blocking |

The tester's final report is **accurate**: counts, coverage, marker removal and
regression tests all reproduce. I found one additional gap the tester did not
list (**R2**, redirect `error=`), which is consistent with the reference but
absent from this code.

---

## Final verdict

**Approve.**

- **No blocking issues.** The release is ready to be deployed into Home
  Assistant and used to test the real authorization. The happy path is
  protocol-correct against the reference implementation and the API docs.
- **Security:** no password, no secret/token logging, PKCE correctly
  implemented, refresh token stored with the documented HA caveat.
- **Home Assistant patterns:** `runtime_data`, reauth reload, `ConfigEntryAuth
  Failed`/`NotReady` mapping, options reload and translations all follow the
  framework; the only notes are metadata/UX-level.
- **Tests:** 135/135 pass, 0 xfailed/skipped, 99% line/branch, `ruff` clean —
  independently reproduced.

Recommended (non-blocking) follow-ups before a wider public/HACS release:
**R1** (align docs with the implemented `state_mismatch`), **R2** (handle
redirect `error=`), **R3** (reject a null access token), **R5** (domain error
for a malformed entry), **R10** (`integration_type: service`) and **R9**
(doc nits). **R4**/**R8** must be addressed when the coordinator slice lands.

### Changes made by this review

- `docs/review.md` rewritten for the v0.3.0 browser authorization-code + PKCE
  state. **No production code was modified.**

*No production code was modified by this review.*
