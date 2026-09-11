# SomToday for Home Assistant

A Home Assistant custom component that logs in to [SomToday](https://www.somtoday.nl/)
and (eventually) exposes a student's schedule, homework, grades and absence as
Home Assistant entities.

> **Current status: authentication only (v0.2.0).**
> This release installs and authenticates against SomToday so the login flow can
> be tested from the Home Assistant UI. **No entities, sensors or coordinator are
> added yet** — the integration currently validates the session during setup and
> exposes no data. Entity support lands in a later release.

## Requirements

- Home Assistant 2024.11 or newer.
- A SomToday account for a school that uses the standard SomToday login
  (username + password).
- **Not supported:** schools that only allow login through an external identity
  provider (single sign-on / SSO). The config flow reports
  `sso_not_supported` for those accounts.

## Installation

### HACS (recommended)

1. In Home Assistant, open **HACS → Integrations**.
2. Open the three-dot menu → **Custom repositories**.
3. Add this repository URL, choose category **Integration**, and click **Add**.
4. Search for **SomToday**, install it, and restart Home Assistant.

### Manual

1. Copy the `custom_components/sometoday` directory into your Home Assistant
   configuration directory, so you end up with:
   `<config>/custom_components/sometoday/`.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **SomToday**.
3. **Select your school** from the searchable list (loaded from SomToday's
   public school list).
4. **Sign in** with your SomToday username and password. The password is used
   once for the login and is never stored; only the rotating refresh token is
   saved in the config entry.
5. If the account has more than one student, choose the student to add.
6. The integration finishes setup by refreshing the stored token. If the session
   is no longer valid, Home Assistant prompts you to re-authenticate.

### Options

After setup you can open **Configure** on the integration to change:

| Option | Default | Meaning |
|--------|---------|---------|
| `scan_interval` | 15 | Poll interval in minutes (5–1440). |
| `schedule_days_ahead` | 14 | Days of schedule to fetch (1–60). |
| `homework_days_ahead` | 7 | Days of homework to fetch (1–60). |
| `enable_grades` | on | Fetch grades. |
| `enable_homework` | on | Fetch homework. |
| `enable_absence` | on | Fetch absence. |

> The options are stored now but only take effect once the coordinator and
> entities are added in a later release.

## Testing the authorization

This release exists mainly so the SomToday login can be exercised against the
real service. To get more detail while testing, add this to
`configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: warning
  logs:
    custom_components.sometoday: debug
```

Then add the integration as described above. A successful authorization creates
a config entry; check **Settings → Devices & Services** for the SomToday entry.

### Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `Cannot connect` | No internet, or `servers.somtoday.nl` unreachable. |
| `Invalid username or password` | Wrong credentials, or the school uses SSO. |
| `This school requires single sign-on` | SSO-only account — not supported yet. |
| Setup fails and asks to re-authenticate | The stored refresh token was rejected; sign in again. |

If login fails unexpectedly, please open an issue and include the debug log for
`custom_components.sometoday` (it never contains the password).

## Privacy and security

- The password is only used to obtain tokens and is **never persisted**.
- The refresh token is stored by Home Assistant in
  `.storage/core.config_entries` as plain text (the standard Home Assistant
  limitation). Restrict access to your configuration directory accordingly.
- All traffic uses HTTPS to SomToday hosts.

## Development

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements_test.txt
pytest tests/ -v --cov=custom_components.sometoday
ruff check custom_components tests
```

All SomToday HTTP traffic is mocked in the tests; the real API is never called.

## License

See the repository for license information.
