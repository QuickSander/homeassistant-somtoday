# AGENTS.md — SomToday Home Assistant Plugin

> This document defines the roles, responsibilities and collaboration
> agreements for the development of the SomToday custom component for Home
> Assistant.
> opencode reads this file automatically as project instructions at the start
> of every session.

## Project context

**Goal**: A Home Assistant custom component that reads SomToday data
(schedule, homework, grades) and exposes it as sensors.

**Technology**:
- Python 3.12+
- Home Assistant integration framework
- DataUpdateCoordinator pattern for polling
- Config flow for user configuration

**Repository structure**:

```text
custom_components/sometoday/
├── __init__.py          # Setup, runtime_data, entry unload
├── manifest.json        # Metadata + version
├── config_flow.py       # Config + options + reauth flow
├── coordinator.py       # SomTodayDataUpdateCoordinator
├── api.py               # SomTodayApiClient (injectable session)
├── auth.py              # SomTodayAuthClient (PKCE + password fallback)
├── exceptions.py        # Shared error hierarchy
├── models.py            # Dataclasses + parsers
├── entity.py            # Shared SomTodayEntity base
├── sensor.py            # Sensor entities
├── binary_sensor.py     # Binary sensor entities
├── calendar.py          # Calendar entity
├── const.py             # Constants (CONF_*, DEFAULT_*, client IDs)
├── strings.json         # Translations (source of truth, EN)
└── translations/
    ├── en.json          # English translations (loaded by HA)
    └── nl.json          # Dutch translations
```

---

## Core rules for all agents

1. **Documentation is part of the task** — every change is documented in the
   same step, in English.
2. **No code without tests** — new functionality requires at least one
   config flow test.
3. **Read docs/architecture.md first** before you start implementing.
4. **Follow Home Assistant coding standards** — use the scaffold as a base.
5. **Code in English** — all method names, variable names, and comments are
   written in English.
6. **Every change is committed** — only when the user explicitly asks for a
   commit. Unlike Aider, opencode never commits on its own. Check the commit
   message against the repository style.

---

## How opencode maps the roles

The Aider modes (`/architect`, `/code`, `/ask`) do not exist in opencode.
Instead, each role is a dedicated **subagent** plus a matching **command**:

| Role | opencode subagent | Command |
|------|-------------------|---------|
| Architecture | `.opencode/agent/architect.md` | `/architect` |
| Implementation | `.opencode/agent/engineer.md` | `/code` |
| Testing | `.opencode/agent/tester.md` | `/test` |
| Review | `.opencode/agent/reviewer.md` | `/review` |

Each subagent has its own model configured in its frontmatter (see
[Multi-model strategy](#multi-model-strategy)) and restricted permissions that
enforce the role's "may NEVER" rules. The commands are thin wrappers that run
the matching agent with the right prompt.

> Note: opencode loads its config once at startup and does not hot-reload. After
> changing `opencode.json`, an agent file, or a command, quit and restart
> opencode.

---

## Agent 1: architect-agent

**opencode agent**: `architect` — **Model**: `deepseek/deepseek-v4-pro`

**Goal**: Designs the system architecture and determines the technical
approach.

**Responsibilities**:
- Determine the integration structure (config flow, coordinator, entities)
- Choose the right Home Assistant patterns
- Write technical specifications in docs/architecture.md, optionally using
  PlantUML syntax
- Identify the required SomToday API endpoints based on:
  https://github.com/elisaado/somtoday-api-docs
- Determine the sensor types (sensor, binary_sensor, calendar)
- Determine the OAuth2 login flow
- Prefer an object-oriented design, but always follow the Home Assistant
  plug-in conventions or the most common setup

**Input**: Requirements, Home Assistant developer docs
**Output**: docs/architecture.md with the technical design

**May NEVER**:
- Write code or create files outside `docs/`
- Run tests

**Example command**:

```text
/architect Design the architecture for a SomToday integration.
Use a DataUpdateCoordinator to poll every 15 minutes.
Describe: config flow, coordinator, sensor entities, error handling.
Write the result to docs/architecture.md
```

---

## Agent 2: engineer-agent

**opencode agent**: `engineer` — **Model**: `deepseek/deepseek-v4-flash`

**Goal**: Implements the code according to the architecture design.

**Responsibilities**:
- Write Python code for the integration
- Follow Home Assistant coding standards
- Create manifest.json with a version key
- Implement the config flow and coordinator
- Create sensor entities with the correct device classes
- Provide an API client with an injectable session so it can be mocked

**Input**: docs/architecture.md from the architect-agent
**Output**: Working code in custom_components/sometoday/

**May NEVER**:
- Change the architecture without consultation
- Commit code when the tests fail

**Example command**:

```text
/code Implement the config flow according to docs/architecture.md.
Use the Home Assistant scaffold structure.
Also add the required strings.json for translations.
```

---

## Agent 3: tester-agent

**opencode agent**: `tester` — **Model**: `deepseek/deepseek-v4-flash`

**Goal**: Validates the implementation against the requirements.

**Responsibilities**:
- Write unit tests for the config flow
- Write unit tests for the coordinator (including polling and error handling)
- Write unit tests for the sensor entities (state, attributes, device classes)
- Write unit tests for the OAuth2 login flow (token refresh, expiry)
- Run integration tests via the `hass` fixture
- Measure and report test coverage
- Report findings in docs/test-report.md
- Verify error handling scenarios

**Input**: Code from the engineer-agent, requirements
**Output**: tests/ directory with tests, docs/test-report.md

**Test tooling**:
- `pytest` as the test runner
- `pytest-asyncio` for async tests
- `pytest-homeassistant-custom-component` for the `hass` fixture and HA test
  helpers
- `pytest-cov` for coverage reporting
- These dependencies live in `requirements_test.txt` (to be created by the
  engineer-agent)

**Test strategy per component**:

| Component | Test type | Main scenarios |
|-----------|-----------|----------------|
| config_flow | unit | successful setup, invalid credentials, network timeout, duplicate entry |
| coordinator | unit | successful update, API error, timeout, retry behavior |
| sensor | unit | correct state, attributes, device class, unavailable on API error |
| OAuth2 flow | unit | token refresh, token expiry, refresh failure |

**Mocking agreements**:
- The SomToday API is **always** mocked; tests may never call the real API
- Use `aioresponses` or `unittest.mock` for HTTP mocking
- Mock responses are placed as fixtures in `tests/conftest.py`
- The engineer-agent delivers the API client with an injectable session so it
  can be mocked

**Report template** (`docs/test-report.md`):
- **Summary**: number of tests, passed/failed, coverage percentage
- **Test cases**: per component a table with test name, goal, result
- **Coverage**: coverage percentage per file
- **Findings**: discovered bugs or missing scenarios
- **Blockers**: things that could not be tested, with the reason

**May NEVER**:
- Modify production code (only report)
- Remove tests without documentation
- Call the real SomToday API in tests

**Escalation**: escalate to the human when:
- The API documentation is insufficient to test a scenario
- A test can only pass by modifying production code
- Coverage stays below 80% after reasonable effort

**Example command**:

```text
/test Write pytest tests for the config flow.
Test: successful setup, invalid credentials, network timeout.
Run the tests with: pytest tests/ -v
```

---

## Agent 4: reviewer-agent

**opencode agent**: `reviewer` — **Model**: `deepseek/deepseek-v4-flash`

**Goal**: Independent quality control of code and documentation.

**Responsibilities**:
- Code review for security and best practices
- Verify that documentation is complete
- Validate Home Assistant specific patterns
- Escalate to the human when in doubt

**Input**: All code and documentation
**Output**: Review report in docs/review.md

**May NEVER**:
- Change code itself (only report)
- Approve without a full review

**Example command**:

```text
/review Review the code in custom_components/sometoday/.
Check: security, error handling, Home Assistant best practices.
Report the findings in docs/review.md
```

---

## Collaboration pattern: Sequential

This pattern works best for a Home Assistant plugin because every phase builds
on the previous one:

```text
Phase 1: architect-agent
   ↓ (docs/architecture.md)
Phase 2: engineer-agent
   ↓ (custom_components/sometoday/)
Phase 3: tester-agent
   ↓ (tests/ + docs/test-report.md)
Phase 4: reviewer-agent
   ↓ (docs/review.md)
Phase 5: engineer-agent (processes feedback)
   ↓
Phase 6: docs update
```

### Handover points

| From | To | Artifact | Quality gate |
|------|----|----------|--------------|
| architect | engineer | docs/architecture.md | All components described |
| engineer | tester | Working code | Code runs without errors |
| tester | reviewer | tests/ + report | 80% coverage |
| reviewer | engineer | docs/review.md | No blocking issues |

---

## Multi-model strategy

The model is set per agent in `.opencode/agent/<name>.md` and can be overridden
per run with `/models` or the `-m/--model` flag. The architect runs on
`deepseek/deepseek-v4-pro`, the most capable model available from the provider,
for the design-heavy work; the other three subagents use
`deepseek/deepseek-v4-flash`, which is faster and sufficient for implementation,
tests and review.

| Task | Model | Command |
|------|-------|---------|
| Architecture | `deepseek/deepseek-v4-pro` | `/architect` |
| Implementation | `deepseek/deepseek-v4-flash` | `/code` |
| Tests | `deepseek/deepseek-v4-flash` | `/test` |
| Review | `deepseek/deepseek-v4-flash` | `/review` |

---

## Quality gates

Before the next phase starts, these criteria must be met:

**After architecture**:
- [ ] All components described in docs/architecture.md
- [ ] API endpoints identified
- [ ] Error handling scenarios named

**After implementation**:
- [ ] Code runs without import errors
- [ ] manifest.json has a version key
- [ ] Config flow works in the Home Assistant UI

**After tests**:
- [ ] Minimum 80% test coverage
- [ ] All tests pass
- [ ] Error scenarios tested

**After review**:
- [ ] No security issues
- [ ] Documentation complete
- [ ] Home Assistant best practices followed

---

## File structure

```text
project-root/
├── AGENTS.md                    # This file (opencode project instructions)
├── opencode.json                # opencode config (default model)
├── README.md                    # Install, configuration and troubleshooting
├── hacs.json                    # HACS metadata
├── .opencode/
│   ├── agent/                   # Subagents: architect, engineer, tester, reviewer
│   └── command/                 # Commands: /architect, /code, /test, /review
├── docs/
│   ├── architecture.md          # From the architect-agent
│   ├── test-report.md           # From the tester-agent
│   ├── review.md                # From the reviewer-agent
│   └── CHANGELOG.md             # All changes
├── custom_components/
│   └── sometoday/
│       ├── __init__.py          # Setup, runtime_data, entry unload
│       ├── manifest.json        # Metadata + version
│       ├── config_flow.py       # Config + options + reauth flow
│       ├── coordinator.py       # SomTodayDataUpdateCoordinator
│       ├── api.py               # SomTodayApiClient (injectable session)
│       ├── auth.py              # SomTodayAuthClient (PKCE + password fallback)
│       ├── exceptions.py        # Shared error hierarchy
│       ├── models.py            # Dataclasses + parsers
│       ├── entity.py            # Shared SomTodayEntity base
│       ├── sensor.py            # Sensor entities
│       ├── binary_sensor.py     # Binary sensor entities
│       ├── calendar.py          # Calendar entity
│       ├── const.py             # Constants (CONF_*, DEFAULT_*, client IDs)
│       ├── strings.json         # Translations (source of truth, EN)
│       └── translations/
│           ├── en.json          # English translations (loaded by HA)
│           └── nl.json          # Dutch translations
├── pytest.ini                   # asyncio_mode = auto (HA test plugin)
├── requirements_test.txt        # Test dependencies
└── tests/
    ├── conftest.py
    ├── test_auth.py
    ├── test_models.py
    ├── test_config_flow.py
    ├── test_api.py
    ├── test_translations.py
    ├── test_manifest.py
    ├── test_coordinator.py
    └── test_sensor.py
```

---

*Last update: 2026-09-11*
*Version: 2.0*
