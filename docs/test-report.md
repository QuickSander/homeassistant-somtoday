# Test report — SomToday Home Assistant plugin

**Component under test:** browser authorization-code + PKCE authentication
layer (**v0.3.0**): `auth.py` (PKCE / authorize URL / code extraction / token
exchange / refresh / holder), `config_flow.py` (single paste step, reauth,
options), `api.py` (`account/me`, `leerlingen`, 401 retry, error mapping,
response release), `models.py` (`Account`/`parse_account`, `Student`,
`SomTodayTokens`), `__init__.py`, `exceptions.py`, `const.py`,
`manifest.json`, `strings.json`, `translations/*.json`
**Date:** 2026-09-11 (final post-fix re-run: **T1 + T2 fixed**)
**Tester:** tester-agent
**Environment:**
`/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv`
(Python 3.14.7, Home Assistant 2026.9.1, pytest 9.0.3, pytest-asyncio 1.4.0,
pytest-homeassistant-custom-component 0.13.364, aioresponses 0.7.9,
pytest-cov 7.1.0, ruff 0.16.7)

> This report covers the **v0.3.0 browser flow**: `build_authorize_url()` →
> browser login → paste → `extract_code()` → `async_exchange_code()` →
> `async_refresh_tokens()`. The coordinator and entity platforms are still out
> of scope (not implemented). The two defects reported in the previous run
> (**T1**, **T2**) are fixed and independently re-verified below.

---

## Summary

| Metric | Value |
|--------|-------|
| Test files | 6 (`test_auth`, `test_models`, `test_config_flow`, `test_api`, `test_translations`, `test_manifest`) + `conftest.py` |
| Tests collected | **135** |
| Passed | **135** |
| Failed | **0** |
| Xfailed | **0** (the previous strict-xfail is now a normal passing test) |
| Skipped | **0** |
| Line coverage (whole integration) | **99%** (585 statements, 2 missed) |
| Branch coverage (whole integration) | **99%** (585 stmts / 2 miss; 134 branches / 6 partial) |
| Lint (`ruff check custom_components tests`) | **clean** (`All checks passed!`) |
| Real SomToday API calls | **none** (all HTTP via `FakeSession`/`FakeResponse`) |

Commands used:

```sh
V=/var/folders/my/41d2j1d50dg5sc8d603280x40000gn/T/opencode/sometoday-venv/bin
$V/python -m pytest tests/ -v --cov=custom_components.sometoday --cov-report=term-missing
$V/python -m pytest tests/ -q --cov=custom_components.sometoday --cov-branch --cov-report=term-missing
$V/python -m ruff check custom_components tests
```

Exact results: `135 passed in 0.89s` (0 xfailed, 0 skipped); line
`TOTAL 585 2 99%`; branch `TOTAL 585 2 134 6 99%`;
`All checks passed!` (ruff exit 0).

Per-file test counts (collected): `test_auth.py` 50, `test_models.py` 33,
`test_config_flow.py` 29, `test_api.py` 20, `test_translations.py` 2,
`test_manifest.py` 1.

**Gate (minimum 80% coverage): PASS** — 99% line and 99% branch, zero
failures, zero xfails, zero skips.

---

## Verification of the T1/T2 fixes (independently reproduced)

Each fix was verified by reading the production code **and** by an independent
probe, not just by trusting the test names.

| ID | Fix | Independent verification | Verdict |
|----|-----|--------------------------|---------|
| **T1** | `extract_code` now prefers a pasted `Location:` line (`_LOCATION_RE`, `auth.py:68`) and `_CODE_RE` only matches `code=` at `[?&]` boundaries (`auth.py:63`) | Probe: `Set-Cookie: code=COOKIEVALUE; Path=/` + `Location: …?code=REALCODE&state=STATE` → **`REALCODE`**; request `Cookie: …; code=COOKIEVALUE` block → **`REALCODE`**; lowercase `set-cookie`/`location` → **`REAL`**. `test_extract_code_header_block_prefers_location_over_cookie` passes normally (marker removed). | **FIXED** |
| **T2** | Bare-code path now `unquote()`s the paste and checks the decoded length (`auth.py:164-167`) | Probe: `extract_code("ABCDEFGH%2FIJ%2BK")` → **`ABCDEFGH/IJ+K`**; `extract_code("ABCDEFGH%3D%26")` → **`ABCDEFGH=&`**. `test_extract_code_bare_url_encoded_code` passes. | **FIXED** |

### No regressions in the other `extract_code` cases (independent probe)

All 21 probe cases passed (20 required + 1 boundary check):

| Path | Result |
|------|--------|
| Full redirect URL `somtoday://…?code=THECODE&state=STATE` | `THECODE` |
| DevTools `location:` header line | `THECODE` |
| Full HTTP response-header block | `THECODE` |
| `state` before `code` | `ABC` |
| `state` absent (check skipped) | `ABC` |
| Wrong `state` | `state_mismatch` |
| `code_challenge=` vs `code=` disambiguation | `REALCODE` |
| `code_challenge=` only (login URL) | `login_page` |
| URL-decoding in a URL (`AB%2FC%2BD`) | `AB/C+D` |
| `auth=` param / login host / login-only URL | `login_page` |
| Empty / whitespace / prose / short bare / URL without code | `no_code` |
| Bare valid code | `ABCDEFGHIJKLMNOP` |
| Query param at `&` boundary / non-boundary (`mycode=`) | `REAL` / `no_code` |
| Cookie-vs-Location (T1) and bare-encoded (T2) | `REALCODE` / decoded |

No test was weakened or removed; the engineer removed the `xfail` marker and
added `test_extract_code_bare_url_encoded_code`.

---

## Test cases

### Component: authentication / PKCE / token endpoint (`tests/test_auth.py`, 50 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_generate_code_verifier` | 128-char verifier from the app alphabet, random | PASS |
| `test_code_challenge_from_verifier` | S256 challenge = base64url(SHA-256) without padding | PASS |
| `test_generate_state` | 32-char random state | PASS |
| `test_build_authorize_url_omits_tenant_uuid` | Exact authorize query; **no `tenant_uuid`** | PASS |
| `test_extract_code_full_redirect_url` | Full `somtoday://…?code=…&state=…` accepted | PASS |
| `test_extract_code_skips_state_check_when_absent` | No `state` param → check skipped | PASS |
| `test_extract_code_state_mismatch` | Present but wrong `state` → `state_mismatch` | PASS |
| `test_extract_code_devtools_location_header` | DevTools `location:` header accepted | PASS |
| `test_extract_code_response_header_block` | Full HTTP response-header block accepted | PASS |
| `test_extract_code_bare_code` | Bare code accepted | PASS |
| `test_extract_code_bare_url_encoded_code` | **T2 fix:** bare percent-encoded code decoded | PASS |
| `test_extract_code_ignores_code_challenge` | `code_challenge=` is not matched as `code=` | PASS |
| `test_extract_code_url_decodes` | Percent-encoded code/state decoded | PASS |
| `test_extract_code_login_page[3]` | `auth=` / login host → `login_page` | PASS |
| `test_extract_code_no_code[5]` | Empty/unstructured → `no_code` | PASS |
| `test_extract_code_header_block_prefers_location_over_cookie` | **T1 fix:** `Set-Cookie: code=…` no longer shadows `Location` code | PASS |
| `test_exchange_code_body_and_headers` | Body `grant_type=authorization_code`, `code`, `code_verifier`, `client_id`, `scope`, `session`; `Accept: application/json` | PASS |
| `test_exchange_code_invalid_grant_is_definitive` | HTTP 400 + `invalid_grant` → `SomtodayInvalidAuth` | PASS |
| `test_exchange_code_retryable_errors[400-other/500/404]` | Other non-200 → `SomTodayConnectionError` (retryable) | PASS |
| `test_exchange_code_rate_limit` | 429 → `SomTodayRateLimitError` | PASS |
| `test_exchange_code_invalid_json` | 200 non-JSON → `SomTodayApiError` | PASS |
| `test_exchange_code_missing_access_token` | 200 without token → `SomTodayAuthError` | PASS |
| `test_exchange_code_non_mapping_payload` | 200 JSON array → `SomTodayApiError` | PASS |
| `test_exchange_code_error_body_non_mapping` | 400 non-mapping error body → retryable | PASS |
| `test_exchange_code_body_read_error` | Body-read transport error → `SomTodayConnectionError` | PASS |
| `test_exchange_code_network_error` | Network failure → `SomTodayConnectionError` | PASS |
| `test_exchange_code_timeout` | Timeout → `SomTodayConnectionError` | PASS |
| `test_exchange_code_releases_response` | Token response released exactly once | PASS |
| `test_refresh_tokens_body` | Refresh body (`grant_type=refresh_token`, `client_id`, `scope`) | PASS |
| `test_refresh_tokens_rotates` | Rotated refresh token replaces the old one | PASS |
| `test_refresh_tokens_preserves_when_omitted` | Omitted refresh token preserved | PASS |
| `test_refresh_tokens_preserves_api_url_and_tenant` | Fallbacks keep api_url/tenant | PASS |
| `test_refresh_tokens_invalid_grant` | Refresh `invalid_grant` → `SomtodayInvalidAuth` | PASS |
| `test_holder_ensure_valid_refreshes_expiring` | Expiring token refreshed | PASS |
| `test_holder_ensure_valid_skips_fresh` | Fresh token not refreshed | PASS |
| `test_holder_ensure_valid_without_tokens` | No tokens → `SomTodayAuthError` | PASS |
| `test_holder_get_access_token` | Returns current access token | PASS |
| `test_holder_refresh_preserves_account_metadata` | Account metadata carried over a refresh | PASS |
| `test_holder_refresh_without_token` | No refresh token → `SomTodayAuthError` | PASS |
| `test_holder_as_entry_data` | Persists refresh token, api_url, metadata | PASS |
| `test_holder_as_entry_data_without_tokens` | No tokens → `SomTodayAuthError` | PASS |
| `test_holder_ensure_valid_serialises_concurrent_refreshes` | Concurrent `ensure_valid` → exactly 1 refresh (lock, §3.4) | PASS |

### Component: config flow (`tests/test_config_flow.py`, 29 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_user_flow_success` | Valid paste creates entry; authorize URL has no `tenant_uuid`, has S256 | PASS |
| `test_user_flow_bare_code` | Bare code accepted without state validation | PASS |
| `test_user_flow_account_fallback_to_student_id` | `/account/me` failure falls back to student id | PASS |
| `test_user_flow_duplicate_aborts` | Duplicate unique-id → `already_configured` | PASS |
| `test_user_flow_no_students` | Empty student list → `no_students` | PASS |
| `test_user_flow_exchange_errors[invalid_auth/cannot_connect×2/unknown]` | Exchange failure → documented error key | PASS |
| `test_user_flow_login_page_paste` | Login-page paste → `login_page` | PASS |
| `test_user_flow_state_mismatch` | Wrong state → `state_mismatch` | PASS |
| `test_user_flow_invalid_url` | Unstructured input → `invalid_url` | PASS |
| `test_authorize_url_kept_on_recoverable_paste` | Paste mistake keeps the open authorize URL | PASS |
| `test_authorize_url_regenerated_when_spent` | Definitive rejection mints a fresh PKCE pair + state | PASS |
| `test_reauth_flow_updates_refresh_token` | Reauth stores rotated token and reloads to `LOADED` | PASS |
| `test_reauth_flow_wrong_account` | Different account → abort `wrong_account` | PASS |
| `test_reauth_flow_errors[invalid_auth/cannot_connect]` | Reauth error mapping | PASS |
| `test_reauth_after_failed_setup_reloads_entry` | `SETUP_ERROR` → reauth → `LOADED` recovery | PASS |
| `test_options_flow` | Options persisted (interval/days/toggles) | PASS |
| `test_options_flow_schedules_reload` | Saving options calls `async_schedule_reload(entry_id)` (§4.1) | PASS |
| `test_setup_entry_refreshes_token` | Setup refreshes, persists rotation, exposes `runtime_data` | PASS |
| `test_setup_entry_keeps_refresh_token_when_not_rotated` | Non-rotating response leaves entry data unchanged | PASS |
| `test_setup_entry_auth_failure` | `SomtodayInvalidAuth` → `ConfigEntryAuthFailed` | PASS |
| `test_setup_entry_connection_failure` | `SomTodayConnectionError` → `ConfigEntryNotReady` | PASS |
| `test_setup_entry_unexpected_failure` | Other `SomTodayError` → `ConfigEntryNotReady` | PASS |
| `test_async_migrate_entry` | Migration hook returns `True` | PASS |
| `test_async_unload_entry` | Unload without platforms returns `True` | PASS |
| `test_default_api_url_constant` | Default API URL is `https://api.somtoday.nl` | PASS |

### Component: REST API client (`tests/test_api.py`, 20 tests)

| Test name | Goal | Result |
|-----------|------|--------|
| `test_get_account_parses` | `/account/me` parsed; bearer + Accept headers asserted | PASS |
| `test_get_account_invalid_payload` | Malformed account payload → `SomTodayApiError` | PASS |
| `test_get_students_parses_items` | `{"items":[…]}` parsed; URL/params/headers asserted | PASS |
| `test_get_students_401_refreshes_and_retries` | 401 → one refresh → retry succeeds | PASS |
| `test_get_students_auth_error` | 403 → `SomTodayAuthError` | PASS |
| `test_get_students_rate_limit` | 429 → `SomTodayRateLimitError` | PASS |
| `test_get_students_server_error` | 5xx → `SomTodayApiError` | PASS |
| `test_get_students_connection_error` | Network error → `SomTodayConnectionError` | PASS |
| `test_get_students_invalid_json` | Wrong top-level shape → `SomTodayApiError` | PASS |
| `test_get_students_401_retry_still_401` | 401 → refresh → 401 → `SomTodayAuthError`, one refresh | PASS |
| `test_get_students_401_refresh_failure_propagates` | Refresh failure during retry propagates | PASS |
| `test_get_students_releases_final_response` | Final response released once | PASS |
| `test_get_students_releases_first_401_response` | Both 401 and retried response released | PASS |
| `test_get_students_non_json_body` | Undecodable body → `SomTodayApiError` | PASS |
| `test_get_students_body_read_error` | Body transport error → `SomTodayConnectionError` | PASS |
| `test_error_response_releases_and_logs_diagnostics` | 5xx released although body read for diagnostics | PASS |
| `test_error_response_text_read_error` | Failing diagnostic read does not mask HTTP error | PASS |
| `test_build_headers_without_tokens` | No tokens → no `Authorization` header | PASS |
| `test_send_post_uses_session_post` | Non-GET dispatched via `session.post` | PASS |
| `test_release_ignores_response_without_release` | `_release()` tolerates missing `release` | PASS |

### Component: models (`tests/test_models.py`, 33 tests)

Token tests (11): `from_token_response` expiry/fallbacks/defaults/missing
fields/invalid `expires_in`, `is_expired`/`expires_soon`, `from_entry`
metadata/defaults, `as_entry_data` with and without metadata — all PASS.

`Account` / `parse_account` (5): documented `links[0].id` shape, first-link
wins, top-level id fallback + string coercion, missing/empty username,
`TypeError`/`ValueError` on invalid payloads — all PASS.

`Student` / `parse_students` (17): documented `{"items":[…]}` and bare-list
shapes, all mapped fields, empty list, `self`/any/top-level id fallback, string
coercion, invalid ids, missing id, `display_name` fallbacks, missing/malformed
`pasfoto`, invalid payload/entry `TypeError`s — all PASS.

### Component: translations and manifest

| Test name | Goal | Result |
|-----------|------|--------|
| `test_translation_files_have_matching_keys` | `strings.json`, `en.json`, `nl.json` expose identical leaf keys | PASS |
| `test_english_config_translations_load` | HA loads EN config-flow strings incl. `{auth_url}` and all error keys | PASS |
| `test_manifest_required_fields` | domain/version-format/`config_flow`/`iot_class`/`integration_type` | PASS |

---

## Coverage

Line coverage (`--cov-report=term-missing`):

```text
Name                                         Stmts   Miss  Cover   Missing
--------------------------------------------------------------------------
custom_components/sometoday/__init__.py         45      2    96%   85, 95
custom_components/sometoday/api.py              94      0   100%
custom_components/sometoday/auth.py            140      0   100%
custom_components/sometoday/config_flow.py     120      0   100%
custom_components/sometoday/const.py            32      0   100%
custom_components/sometoday/exceptions.py        7      0   100%
custom_components/sometoday/models.py          147      0   100%
--------------------------------------------------------------------------
TOTAL                                          585      2    99%
```

Branch coverage (`--cov-branch --cov-report=term-missing`):

```text
Name                                         Stmts   Miss Branch BrPart  Cover   Missing
----------------------------------------------------------------------------------------
custom_components/sometoday/__init__.py         45      2      8      3    91%   72->79, 85, 95
custom_components/sometoday/api.py              94      0     18      2    98%   203->206, 208->214
custom_components/sometoday/auth.py            140      0     36      1    99%   75->exit
custom_components/sometoday/config_flow.py     120      0     20      0   100%
custom_components/sometoday/const.py            32      0      0      0   100%
custom_components/sometoday/exceptions.py        7      0      0      0   100%
custom_components/sometoday/models.py          147      0     52      0   100%
----------------------------------------------------------------------------------------
TOTAL                                          585      2    134      6    99%
```

| File | Stmts | Missed | Branches | Partial | Line | Branch |
|------|------:|-------:|---------:|--------:|-----:|-------:|
| `__init__.py` | 45 | 2 | 8 | 3 | 96% | 91% |
| `api.py` | 94 | 0 | 18 | 2 | 100% | 98% |
| `auth.py` | 140 | 0 | 36 | 1 | 100% | 99% |
| `config_flow.py` | 120 | 0 | 20 | 0 | 100% | 100% |
| `const.py` | 32 | 0 | 0 | 0 | 100% | 100% |
| `exceptions.py` | 7 | 0 | 0 | 0 | 100% | 100% |
| `models.py` | 147 | 0 | 52 | 0 | 100% | 100% |
| **Total** | **585** | **2** | **134** | **6** | **99%** | **99%** |

`api.py`, `auth.py`, `config_flow.py` and `models.py` are at **100% line
coverage**; `config_flow.py` and `models.py` are also at **100% branch
coverage**. The remaining partials are defensive branches:

- `__init__.py:72->79` — `auth.tokens is None` guard (unreachable: setup raises
  first); `85`, `95` — `if PLATFORMS:` (empty in this slice, entity slice).
- `api.py:203->206` — `response.headers` not a `Mapping`;
  `208->214` — response without a `text` attribute.
- `auth.py:75->exit` — `_release()` called on a response without `release`.

### Scenario assessment — architecture §3 (browser authorization-code + PKCE)

| Scenario | Covered | Evidence |
|----------|---------|----------|
| Authorize URL has PKCE + state and **no `tenant_uuid`** | Yes | `test_build_authorize_url_omits_tenant_uuid`, `test_user_flow_success` |
| `extract_code` full redirect URL | Yes | `test_extract_code_full_redirect_url` |
| `extract_code` DevTools `Location:` header / header block | Yes | `test_extract_code_devtools_location_header`, `test_extract_code_response_header_block` |
| `extract_code` bare code (plain + percent-encoded) | Yes | `test_extract_code_bare_code`, `test_extract_code_bare_url_encoded_code` |
| `extract_code` `login_page` / `state_mismatch` / `no_code` | Yes | `test_extract_code_login_page[3]`, `test_extract_code_state_mismatch`, `test_extract_code_no_code[5]` |
| `code_challenge=` not confused with `code=` | Yes | `test_extract_code_ignores_code_challenge` |
| Cookie/header `code=` cannot shadow `Location` | Yes | `test_extract_code_header_block_prefers_location_over_cookie` |
| URL-decoding of code/state | Yes | `test_extract_code_url_decodes` |
| Exchange body `grant_type=authorization_code`, `code_verifier`, `client_id`, `session` | Yes | `test_exchange_code_body_and_headers` |
| `invalid_grant` → `SomtodayInvalidAuth` (definitive) | Yes | `test_exchange_code_invalid_grant_is_definitive` |
| Other non-200 / network / malformed → retryable | Yes | `test_exchange_code_retryable_errors[…]`, `test_exchange_code_network_error`, `test_exchange_code_timeout`, `test_exchange_code_invalid_json`, `test_exchange_code_non_mapping_payload` |
| Refresh rotation preservation (omitted token keeps old) | Yes | `test_refresh_tokens_preserves_when_omitted`, `test_refresh_tokens_preserves_api_url_and_tenant`, `test_setup_entry_keeps_refresh_token_when_not_rotated` |
| Refresh rotation applied (new token persisted) | Yes | `test_refresh_tokens_rotates`, `test_holder_refresh_preserves_account_metadata`, `test_setup_entry_refreshes_token` |
| `SomTodayAuth` lock serialises refresh | Yes | `test_holder_ensure_valid_serialises_concurrent_refreshes` |
| `SomTodayAuth` proactive refresh / no-op when fresh | Yes | `test_holder_ensure_valid_refreshes_expiring`, `test_holder_ensure_valid_skips_fresh` |

### Scenario assessment — architecture §5.1 (error mapping)

| Condition | Expected | Covered | Evidence |
|-----------|----------|---------|----------|
| HTTP 400 `error=invalid_grant` | `SomtodayInvalidAuth` | Yes | `test_exchange_code_invalid_grant_is_definitive`, `test_refresh_tokens_invalid_grant` |
| `state` mismatch | definitive flow error | Yes | `test_extract_code_state_mismatch`, `test_user_flow_state_mismatch` |
| `401` data API | refresh once, retry; still failing → auth error | Yes | `test_get_students_401_refreshes_and_retries`, `test_get_students_401_retry_still_401`, `test_get_students_401_refresh_failure_propagates` |
| `403` data API | `SomTodayAuthError` | Yes | `test_get_students_auth_error` |
| Other token non-200 / malformed | retryable connection/API error | Yes | `test_exchange_code_retryable_errors[…]`, `test_exchange_code_invalid_json` |
| Network error / timeout | `SomTodayConnectionError` | Yes | `test_exchange_code_network_error`, `test_exchange_code_timeout`, `test_get_students_connection_error` |
| `429 Too Many Requests` | `SomTodayRateLimitError` | Yes | `test_exchange_code_rate_limit`, `test_get_students_rate_limit` |
| `5xx` | `SomTodayApiError` | Yes | `test_get_students_server_error` |
| Malformed JSON / schema | `SomTodayApiError` | Yes | `test_get_students_non_json_body`, `test_get_students_invalid_json`, `test_get_account_invalid_payload` |
| Response release (all paths) | release exactly once | Yes | `test_exchange_code_releases_response`, `test_get_students_releases_*`, `test_error_response_*` |

---

## Findings

### T1 — `extract_code` cookie/header false positive — **FIXED**

The previous run reported that a pasted header block containing
`Set-Cookie: code=…` / `Cookie: …; code=…` returned the cookie value instead of
the `Location:` redirect code. The fix adds `_LOCATION_RE` (prefer the first
`Location:` line) and tightens `_CODE_RE`/`_STATE_RE`/`_AUTH_RE` to `[?&]`
boundaries only. Independent probe confirms the redirect code now wins, and
`test_extract_code_header_block_prefers_location_over_cookie` passes without an
`xfail` marker.

### T2 — Bare percent-encoded code rejected — **FIXED**

The bare-code path now `unquote()`s the paste and applies the length check to
the decoded value. Independent probe: `ABCDEFGH%2FIJ%2BK` →
`ABCDEFGH/IJ+K`; `ABCDEFGH%3D%26` → `ABCDEFGH=&`.
`test_extract_code_bare_url_encoded_code` passes.

### T7 — A pasted query fragment starting with `code=` is no longer recognised (Low, OPEN, by design)

The tightened `[?&]` boundary means `extract_code("code=ABC&state=S")` now
raises `no_code` (previously accepted). This is only reachable when a user
pastes a bare query fragment without the `?`, which the UI does not instruct;
the full redirect URL and the DevTools `Location:` value always include `?`.
Classified as an acceptable trade-off of the T1 fix, not a regression in a
supported path. No test added (would assert contested behaviour).

### T8 — A quoted `Location:` value is not unwrapped (Info, OPEN)

`_LOCATION_RE` captures `(\S+)`, so `Location: "somtoday://…?code=ABC&state=S"`
yields `state_mismatch` because the captured `state` keeps the trailing quote.
DevTools' "Copy value" does not add quotes, so this is a low-probability paste.
No test added.

### T9 — Redirect chain with multiple `Location:` lines uses the first (Info, OPEN)

If a user copies a redirect chain where an intermediate `Location` is a login
URL and the final one is the `somtoday://` callback, the first line is used and
the flow reports `login_page`. Copying only the final response's `Location`
works. No test added.

### T3 — 403 does not trigger a reactive refresh (Info, deviation from §5.1)

`api.py::_request` only retries on `401`; `_async_decode` maps `403` directly to
`SomTodayAuthError`. Architecture §5.1 lists "`401`/`403` … refresh once". A
`403` is arguably an authorization (not authentication) failure, so not
retrying is defensible, but the code and architecture disagree. Low risk.

### T4 — `/rest/v1/account/me` omits `additional=restricties` (Info)

`api.py::async_get_account` sends no query parameters, while architecture §7.2
lists `additional=restricties`. The account id is read from `links[0].id`, so
the omission does not affect the unique id. Non-blocking.

### T5 — Reauth wrong-account detection skipped when `unique_id is None` (Low/Info)

`config_flow.py` guards the mismatch with `entry.unique_id is not None`. A
legacy entry without a unique id would accept a different account on reauth.
All entries created by this flow set a unique id, so the branch is not
reachable today.

### T6 — Concurrent forced refreshes are not deduplicated (Info)

`async_refresh()` always forces a refresh. Concurrent 401 retries are
serialised by the lock, but each issues a token request (probe: 2 concurrent
`async_refresh()` → 2 calls). With rotating refresh tokens this is correct,
only wasteful. `async_ensure_valid()` is deduplicated (1 call for 3 concurrent
callers).

### Carry-over items from the previous report (not re-verified in this slice)

N10 (`from_entry` bare `KeyError` on malformed entry), N13 (runtime rotation
not persisted outside setup), N14 (options reload — now covered by
`test_options_flow_schedules_reload`), N15 (`integration_type: hub`), N17
(broad `unknown` handler), N18 (options `bool` fields `Required`), and the
production `assert`s in the config flow. All non-blocking and unchanged.

---

## Blockers

1. **Real-account validation is prohibited.** The SomToday authorization-code
   alphabet, refresh-token rotation behaviour on the live endpoint, and the
   architecture §12.2 refresh-host pairing can only be confirmed against a real
   account; tests never call the real API. (The T2 fix removes the earlier
   bare-encoded-code uncertainty for the common case.)
2. **No coordinator/entity modules exist** (`coordinator.py`, `sensor.py`,
   `binary_sensor.py`, `calendar.py`, `entity.py`). Their tests are out of
   scope; §5/§8 remain forward reference only.

No other blockers: the suite is green (`135 passed, 0 xfailed, 0 skipped`) and
no test requires a production change to pass.

---

## Changes made by the tester (this run)

**No production code was modified.** This run independently verified the
engineer's T1/T2 fixes (see the verification section) and re-ran the full suite
and lint. **No new tests were added by the tester**: the engineer supplied
`test_extract_code_bare_url_encoded_code`, the T1 regression test is now a
normal passing test, and the residual observations T7–T9 are low-probability
edge cases that would require asserting contested behaviour. The report was
rewritten for the fixed state.

No existing test was weakened or removed.

### Test-quality assessment and gate

| Criterion | Result |
|-----------|--------|
| Minimum 80% coverage | **Met** — 99% line, 99% branch |
| All tests pass | **Met** — 135 passed, 0 failed, 0 xfailed, 0 skipped |
| Error scenarios tested | **Met** — §3/§5.1 mapping, flow errors, setup exceptions, reauth reload, token refresh |
| No production code modified | **Met** |
| No test removed | **Met** |

**Final verdict:** the v0.3.0 browser authorization-code + PKCE layer is
independently validated. **T1 and T2 are confirmed fixed** with probes and
passing regression tests, with no regressions in the other `extract_code`
cases. All architecture §3 and §5.1 auth scenarios are covered;
`config_flow.py`/`models.py` are at 100% line+branch and the whole integration
at 99% line/branch with **135/135 tests passing and zero xfails/skips**. The
remaining findings T3–T9 are low/info, non-blocking observations. **The 80%
gate is met with room to spare.**
