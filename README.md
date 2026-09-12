# SomToday for Home Assistant

A Home Assistant custom component that logs in to [SomToday](https://www.somtoday.nl/)
and (eventually) exposes a student's schedule, homework, grades and absence as
Home Assistant entities.

> **Current status: authentication, schedule and the first lesson sensors
> (v0.7.0).** This release installs, authenticates against SomToday, exposes the
> student's **timetable as a read-only `calendar` entity**, and adds
> **`first_lesson_of_today`** and **`first_lesson_of_tomorrow`** timestamp
> sensors (useful for driving an alarm). Grades, homework, absence and the
> remaining sensor/binary_sensor entities land in later releases.

## Requirements

- Home Assistant 2024.11 or newer.
- A SomToday account. Because you log in through your own browser, **SSO and
  MFA are fully supported** — there is no per-school configuration.

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

SomToday removed its public school list and disabled the password grant. This
integration therefore uses the same browser-based authorization-code + PKCE
flow as the official app:

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **SomToday**.
3. Home Assistant shows a SomToday **authorize URL**. Open it in your browser.
   SomToday asks you to pick your school and log in; SSO/MFA work as usual.
4. After a successful login, your browser is redirected to a `somtoday://`
   address that Home Assistant cannot receive. Copy that redirect back into the
   form using one of these methods:
   - copy the full `somtoday://…/oauth/callback?code=…&state=…` URL from the
     address bar **before** the browser discards it, or
   - open **Chrome DevTools → Network**, find the request to the callback, and
     copy the value of its **`Location:`** response header, or
   - paste just the authorization `code`.

   > **If the SomToday app opens instead** (common on macOS/iOS where the app is
   > installed), the OS handles the `somtoday://` link and the address never
   > appears in the browser. Use the **DevTools `Location:` header** method: open
   > DevTools (F12) → **Network** *before* finishing the login, click the request
   > to `somtoday.nl`, and copy the `Location:` response header. You can also use
   > a desktop browser/profile without the SomToday app installed.

   > **Timing matters.** SomToday's authorization code is single-use and
   > short-lived. Have the DevTools **Response Headers** pane (or the address
   > bar) ready *before* you submit, and paste within a few seconds.

   > **Do not paste the Microsoft/SSO callback.** A URL like
   > `https://inloggen.somtoday.nl/oidc?code=…&state=…&session_state=…` is an
   > intermediate SSO step; its `code` cannot be exchanged. Keep going until the
   > browser tries to open `somtoday://…` and use that.
5. Home Assistant exchanges the code for tokens, reads `/rest/v1/account/me`
   and `/rest/v1/leerlingen`, and creates the config entry. If the account sees
   more than one student, you pick one; the integration adds **one entry per
   student**, so a parent/guardian account can be added once for each child.
   Only the rotating refresh token and account metadata are stored.

If the paste is wrong (for example you copied the login page instead of the
redirect), the form tells you and **keeps the same authorize URL**, so you can
finish the login you already started.

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

> The `scan_interval` and `schedule_days_ahead` options affect the coordinator
> and the calendar immediately (the entry reloads when you save). The
> homework/grades/absence toggles take effect once those entities are added.

### Entities

One device is created per student, with these entities:

| Entity | Type | Description |
|--------|------|-------------|
| `calendar.<student>` | calendar | The student's timetable (read-only). |
| `sensor.<student>_first_lesson_of_today` | sensor (timestamp) | Start of the first lesson today; `unknown` on a free day. |
| `sensor.<student>_first_lesson_of_tomorrow` | sensor (timestamp) | Start of the first lesson tomorrow; `unknown` if there is none. |

The `first_lesson_of_today`/`first_lesson_of_tomorrow` sensors expose the
lesson's details as attributes (missing values are omitted), and are designed to
drive an alarm. For example, set a phone alarm 45 minutes before the first
lesson, if there is one:

| Attribute | Type | Meaning |
|-----------|------|---------|
| `subject` | string | Subject name (e.g. `Wiskunde`). |
| `room` | string | Room/location (e.g. `B12`). |
| `teacher` | string | Teacher abbreviation(s) (e.g. `JDO`). |
| `end` | timestamp | End of the first lesson (timezone-aware). |
| `lesson_id` | string | SomToday appointment id. |
| `lessons_today` / `lessons_tomorrow` | int | Number of lessons on that day. |

The state stays in the past once the lesson has started (it is still "the first
lesson of the day"), and is `unknown` on a day without lessons.

```yaml
automation:
  - alias: "School alarm"
    triggers:
      - trigger: time
        at: "06:00:00"
    actions:
      - if:
          - condition: template
            value_template: "{{ states('sensor.somtoday_eli_saado_first_lesson_of_today') not in ['unknown', 'unavailable'] }}"
        then:
          - action: notify.mobile_app_phone
            data:
              message: >-
                First lesson {{ state_attr('sensor.somtoday_eli_saado_first_lesson_of_today', 'subject') }}
                at {{ as_timestamp(states('sensor.somtoday_eli_saado_first_lesson_of_today')) | timestamp_custom('%H:%M') }}
```

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
On every setup/reload you will see this line in the log:

```
SomToday: authenticated as <student> (account <id>)
```

If instead you get a "Reauthenticate" prompt, the stored refresh token was
rejected; if setup keeps retrying, the token endpoint was unreachable. Neither
message contains a token.

### Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `Could not find an authorization code in the pasted text` | You pasted something that is not a redirect URL or code. Copy the `somtoday://…?code=…` URL or just the code. |
| `It looks like the login was not completed yet` | You pasted the login page (it contains `auth=`) instead of the final redirect. Finish the login first. |
| `This redirect does not belong to the current login attempt` | The `state` in the pasted URL does not match the shown authorize URL. Start again from the link in the form. |
| `That is the Microsoft/SSO callback, not the final SomToday redirect` | You pasted the `/oidc?…&session_state=…` URL. Finish the login until the browser tries to open `somtoday://…`. |
| `SomToday rejected the authorization code` | The code expired, was already used, or failed PKCE. Restart from the newly shown URL and paste immediately; the HA log now records the exact OAuth2 error/description. |
| `Could not connect to SomToday` | No internet or a temporary SomToday failure. Retry; the form keeps the same authorize URL when it is safe. |
| `No students were found for this account` | The account has no linked students. |
| `A different SomToday account signed in` | During reauth a different account was used than the one being repaired. |
| Setup fails and asks to re-authenticate | The stored refresh token was rejected; sign in again. |

If login fails unexpectedly, please open an issue and include the debug log for
`custom_components.sometoday` (it never contains passwords or tokens).

## Privacy and security

- No password is ever requested or stored.
- The authorization code and PKCE verifier are used once during setup and are
  never persisted; only the rotating refresh token is stored.
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
