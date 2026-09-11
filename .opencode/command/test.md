---
description: Write and run pytest tests for the SomToday integration
agent: tester
---

Write pytest tests for the SomToday integration according to the tester-agent
role in `AGENTS.md`.

Task for this run:

$ARGUMENTS

If no specific task is given, test the config flow: successful setup, invalid
credentials and network timeout. Mock the SomToday API, run the tests with
`pytest tests/ -v`, and report the results in `docs/test-report.md`.
