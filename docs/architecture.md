# Architectuur: SomToday Home Assistant Integratie

> Technisch ontwerp voor de SomToday custom component.
> Opgesteld door de architect-agent volgens de afspraken in AGENTS.md.

## 1. Overzicht

De integratie leest SomToday-data (rooster, huiswerk, cijfers) uit via de
SomToday REST API en stelt deze beschikbaar als Home Assistant entities.
De integratie volgt het standaard Home Assistant integratieframework met
een `DataUpdateCoordinator` voor polling en een `ConfigFlow` voor
gebruikersconfiguratie.

### Componenten

```text
┌─────────────────────────────────────────────────────────────┐
│                     Home Assistant Core                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              SomTodayConfigFlow (config_flow.py)             │
│  - Gebruikersinvoer: credentials + poll-interval             │
│  - OAuth2 autorisatie                                        │
│  - Validatie via test-API-call                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           SomTodayDataUpdateCoordinator (coordinator.py)     │
│  - Polling met configureerbaar interval                      │
│  - OAuth2 token refresh                                      │
│  - Error handling & retry                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              SomTodayApiClient (api.py)                      │
│  - HTTP calls naar SomToday API                              │
│  - Injecteerbare aiohttp sessie (voor mocking)               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Sensor Entities (sensor.py)                     │
│  - Rooster, huiswerk, cijfers                                │
└─────────────────────────────────────────────────────────────┘
```

## 2. Config Flow

### Stappen

1. **User step** (`async_step_user`):
   - Vraagt: gebruikersnaam, wachtwoord, school (SomToday subdomein)
   - Vraagt: **poll-interval in minuten** (default: 15, min: 5, max: 1440)
   - Valideert credentials via een test-call naar de API
   - Maakt een config entry aan bij succes

2. **OAuth2 step** (`async_step_oauth2`):
   - Start OAuth2 flow indien SomToday dit vereist
   - Slaat refresh token op in de config entry

3. **Reauth step** (`async_step_reauth`):
   - Wordt getriggerd bij `ConfigEntryAuthFailed`
   - Vraagt opnieuw om credentials

### Config entry data

De opgeslagen data verschilt per authenticatiemethode:

**Bij OAuth2 (aanbevolen)**:

```python
{
    "username": str,
    "school": str,
    "refresh_token": str,     # persistent, nodig voor token refresh
    "scan_interval": int,     # in minuten, door gebruiker opgegeven
}
```

**Bij wachtwoord-authenticatie (fallback)**:

```python
{
    "username": str,
    "password": str,          # persistent, nodig om tokens te vernieuwen
    "school": str,
    "scan_interval": int,     # in minuten, door gebruiker opgegeven
}
```

Het **access token wordt NIET persistent opgeslagen**. Dit is kortlevend en
wordt in het geheugen van de coordinator gehouden. Alleen de refresh token
(of het wachtwoord) wordt in de config entry bewaard.

> **Beveiligingsnoot**: Home Assistant slaat config entries op in
> `.storage/core.config_entries` als plaintext JSON. De refresh token en het
> wachtwoord zijn dus niet versleuteld. Dit is de standaard HA-aanpak; er is
> geen ingebouwde encrypted opslag. Beperk de bestandsrechten van `.storage/`
> en documenteer dit richting de gebruiker.

### Options flow

De gebruiker kan het poll-interval later aanpassen via de options flow
(`async_step_init`). Dit werkt de coordinator bij zonder herstart.

## 3. DataUpdateCoordinator

### Poll-interval

Het poll-interval is **configureerbaar** en wordt als volgt bepaald:

```python
scan_interval_minutes = entry.options.get(
    CONF_SCAN_INTERVAL,
    entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
)
update_interval = timedelta(minutes=scan_interval_minutes)
```

- **Default**: 15 minuten
- **Minimum**: 5 minuten (voorkomt API rate limiting)
- **Maximum**: 1440 minuten (24 uur)
- Validatie gebeurt in de config flow via `vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))`

### Update logica

```python
async def _async_update_data(self):
    try:
        return await self.api_client.fetch_all()
    except SomTodayAuthError as err:
        raise ConfigEntryAuthFailed from err
    except SomTodayApiError as err:
        raise UpdateFailed from err
```

### Error handling

| Fout | Actie |
|------|-------|
| Auth error (401/403) | `ConfigEntryAuthFailed` → reauth flow |
| Netwerk timeout | `UpdateFailed` → retry volgende cyclus |
| Rate limit (429) | `UpdateFailed` + exponentiële backoff |
| Server error (5xx) | `UpdateFailed` → retry volgende cyclus |

## 4. API Client

### Structuur

```python
class SomTodayApiClient:
    def __init__(self, session: aiohttp.ClientSession, ...):
        self._session = session  # injecteerbaar voor tests

    async def fetch_all(self) -> SomTodayData: ...
    async def fetch_schedule(self) -> list[Lesson]: ...
    async def fetch_homework(self) -> list[Homework]: ...
    async def fetch_grades(self) -> list[Grade]: ...
```

De `session` is injecteerbaar zodat de tester-agent deze kan mocken met
`aioresponses` of `unittest.mock`.

### Endpoints

Gebaseerd op https://github.com/elisaado/somtoday-api-docs:

| Endpoint | Doel |
|----------|------|
| `/oauth2/token` | OAuth2 token ophalen/refreshen |
| `/rest/v1/leerlingen/{id}/rooster` | Rooster ophalen |
| `/rest/v1/leerlingen/{id}/huiswerk` | Huiswerk ophalen |
| `/rest/v1/leerlingen/{id}/cijfers` | Cijfers ophalen |

## 5. Sensor Entities

| Entity | Type | Device class | State |
|--------|------|--------------|-------|
| `sensor.sometoday_volgende_les` | sensor | — | Naam volgende les |
| `sensor.sometoday_huiswerk_count` | sensor | — | Aantal open huiswerk |
| `sensor.sometoday_gemiddeld_cijfer` | sensor | — | Gemiddeld cijfer |
| `binary_sensor.sometoday_heeft_huiswerk` | binary_sensor | — | on/off |
| `calendar.sometoday_rooster` | calendar | — | Lessen als events |

Alle sensoren worden `unavailable` wanneer de coordinator een `UpdateFailed`
rapporteert.

## 6. OAuth2 Flow

1. Gebruiker voert credentials in via config flow
2. Integratie vraagt access token + refresh token aan bij `/oauth2/token`
3. Alleen de **refresh token** wordt opgeslagen in de config entry; het
   access token blijft in het geheugen van de coordinator
4. Bij 401: coordinator probeert refresh via refresh token
5. Bij refresh failure: `ConfigEntryAuthFailed` → reauth flow

### Roterende refresh tokens

Sommige OAuth2-providers geven bij elke refresh een **nieuwe** refresh token
en invalideren de oude. De coordinator moet dit afhandelen door de config
entry bij te werken:

```python
if new_refresh_token != entry.data[CONF_REFRESH_TOKEN]:
    self.hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_REFRESH_TOKEN: new_refresh_token},
    )
```

Zonder deze stap werkt de integratie na de eerste refresh niet meer, omdat
de opgeslagen refresh token dan verlopen is.

## 7. Bestandsstructuur

```text
custom_components/sometoday/
├── __init__.py          # Setup, entry unload
├── manifest.json        # Metadata + version
├── config_flow.py       # Config + options flow
├── coordinator.py       # DataUpdateCoordinator
├── api.py               # SomTodayApiClient
├── sensor.py            # Sensor entities
├── const.py             # Constanten (CONF_*, DEFAULT_*)
├── strings.json         # Vertalingen (EN)
└── translations/
    └── nl.json          # Nederlandse vertalingen
```

## 8. Constanten (const.py)

```python
DOMAIN = "sometoday"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_REFRESH_TOKEN = "refresh_token"
DEFAULT_SCAN_INTERVAL = 15  # minuten
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 1440
```

## 9. Error Handling Samenvatting

- **Config flow**: valideert input, toont foutmeldingen via `strings.json`
- **Coordinator**: vertaalt API-fouten naar HA exceptions
- **Entities**: worden `unavailable` bij `UpdateFailed`
- **Reauth**: automatisch getriggerd bij auth failures
- **Token refresh**: roterende refresh tokens worden via `async_update_entry`
  teruggeschreven naar de config entry
