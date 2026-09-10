# AGENTS.md — SomToday Home Assistant Plugin

> Dit document definieert de rollen, verantwoordelijkheden en samenwerkingsafspraken
> voor de ontwikkeling van de SomToday custom component voor Home Assistant.
> Aider leest dit document als context bij elke sessie.

## Projectcontext

**Doel**: Een Home Assistant custom component dat SomToday-data (rooster, huiswerk,
cijfers) uitleest en beschikbaar maakt als sensoren.

**Technologie**:
- Python 3.12+
- Home Assistant integratieframework
- DataUpdateCoordinator patroon voor polling
- Config flow voor gebruikersconfiguratie

**Repository-structuur**:

"""text
custom_components/sometoday/
├── __init__.py
├── manifest.json
├── config_flow.py
├── coordinator.py
├── sensor.py
├── const.py
├── strings.json
└── translations/
    └── nl.json
"""

---

## Kernregels voor alle agenten

1. **Documentatie is onderdeel van de taak** — elke wijziging wordt gedocumenteerd
   in dezelfde stap in het Engels.
2. **Geen code zonder tests** — nieuwe functionaliteit vereist minimaal een
   config flow test.
3. **Lees eerst docs/architecture.md** voordat je begint met implementeren.
4. **Volg Home Assistant coding standards** — gebruik de scaffold als basis.
4. **Code in het Engels** -- Alle methode namen en variabelen namen, maar ook commentaar is in het Engels geschreven.
5. **Elke wijziging wordt gecommit** — Aider doet dit automatisch, maar
   controleer de commit messages.

---

## Agent 1: architect-agent

**Model**: deepseek/deepseek-reasoner (via /architect mode)

**Doel**: Ontwerpt de systeemarchitectuur en bepaalt de technische aanpak.

**Verantwoordelijkheden**:
- Bepalen van de integratiestructuur (config flow, coordinator, entities)
- Kiezen van de juiste Home Assistant patronen
- Opstellen van technische specificaties in docs/architecture.md met mogelijk gebruik van PlantUML syntax.
- Identificeren van benodigde API-endpoints van SomToday gebaseerd op: https://github.com/elisaado/somtoday-api-docs
- Bepalen van sensor-types (sensor, binary_sensor, calendar)
- Bepalen van de OAuth2 login flow.
-  Een object georienteerd ontwerp prefereren maar altijd de Home assistant plug-in conventies of meest gebruikte opzet volgen.

**Input**: Requirements, Home Assistant developer docs
**Output**: docs/architecture.md met technisch ontwerp

**Mag NOOIT**:
- Code schrijven of bestanden aanmaken buiten docs/
- Tests uitvoeren

**Voorbeeldcommando**:

"""text
/architect Ontwerp de architectuur voor een SomToday integratie.
Gebruik DataUpdateCoordinator voor polling elke 15 minuten.
Beschrijf: config flow, coordinator, sensor entities, error handling.
Schrijf het resultaat naar docs/architecture.md
"""

---

## Agent 2: engineer-agent

**Model**: deepseek/deepseek-chat (via /code mode)

**Doel**: Implementeert de code volgens het architectuurontwerp.

**Verantwoordelijkheden**:
- Schrijven van Python code voor de integratie
- Volgen van Home Assistant coding standards
- Aanmaken van manifest.json met version key
- Implementeren van config flow en coordinator
- Aanmaken van sensor entities met juiste device classes

**Input**: docs/architecture.md van architect-agent
**Output**: Werkende code in custom_components/sometoday/

**Mag NOOIT**:
- Architectuur wijzigen zonder overleg
- Code committen zonder dat tests slagen

**Voorbeeldcommando**:

"""text
/code Implementeer de config flow volgens docs/architecture.md.
Gebruik de scaffold-structuur van Home Assistant.
Voeg ook de benodigde strings.json toe voor vertalingen.
"""

---

## Agent 3: tester-agent

**Model**: deepseek/deepseek-chat (via /code mode)

**Doel**: Valideert de implementatie tegen de requirements.

**Verantwoordelijkheden**:
- Schrijven van unit tests voor config flow
- Uitvoeren van integratietests
- Rapporteren van bevindingen in docs/test-report.md
- Controleren van error handling scenarios

**Input**: Code van engineer-agent, requirements
**Output**: tests/ map met tests, docs/test-report.md

**Mag NOOIT**:
- Productiecode aanpassen (alleen rapporteren)
- Tests verwijderen zonder documentatie

**Voorbeeldcommando**:

"""text
/code Schrijf pytest tests voor de config flow.
Test: succesvolle setup, ongeldige credentials, netwerk timeout.
Voer de tests uit met: pytest tests/ -v
"""

---

## Agent 4: reviewer-agent

**Model**: deepseek/deepseek-reasoner (via /ask mode)

**Doel**: Onafhankelijke kwaliteitscontrole van code en documentatie.

**Verantwoordelijkheden**:
- Code review op veiligheid en best practices
- Controleren of documentatie compleet is
- Valideren van Home Assistant specifieke patronen
- Escaleren naar mens bij twijfel

**Input**: Alle code en documentatie
**Output**: Review-rapport in docs/review.md

**Mag NOOIT**:
- Zelf code aanpassen (alleen rapporteren)
- Goedkeuring geven zonder volledige controle

**Voorbeeldcommando**:

"""text
/ask Review de code in custom_components/sometoday/.
Controleer: security, error handling, Home Assistant best practices.
Rapporteer bevindingen in docs/review.md
"""

---

## Samenwerkingspatroon: Sequentieel

Dit patroon werkt het beste voor een Home Assistant plugin omdat elke fase
voortbouwt op de vorige:

"""text
Fase 1: architect-agent
   ↓ (docs/architecture.md)
Fase 2: engineer-agent
   ↓ (custom_components/sometoday/)
Fase 3: tester-agent
   ↓ (tests/ + docs/test-report.md)
Fase 4: reviewer-agent
   ↓ (docs/review.md)
Fase 5: engineer-agent (verwerkt feedback)
   ↓
Fase 6: docs-agent (update documentatie)
"""

### Overdrachtsmomenten

| Van | Naar | Artefact | Kwaliteitspoort |
|-----|------|----------|-----------------|
| architect | engineer | docs/architecture.md | Alle componenten beschreven |
| engineer | tester | Werkende code | Code draait zonder errors |
| tester | reviewer | tests/ + rapport | 80% coverage |
| reviewer | engineer | docs/review.md | Geen blocking issues |

---

## Multi-Model Strategie

Gebruik verschillende modellen voor verschillende taken om kosten te
besparen:

| Taak | Model | Commando |
|------|-------|----------|
| Architectuur | DeepSeek Reasoner | /architect |
| Implementatie | DeepSeek Chat | /code |
| Tests | DeepSeek Chat | /code |
| Review | DeepSeek Reasoner | /ask |

**Aider configuratie** (.aider.conf.yml):

"""yaml
model: deepseek/deepseek-chat
editor-model: deepseek/deepseek-chat
weak-model: deepseek/deepseek-chat
auto-commits: true
auto-lint: true
test-cmd: pytest tests/ -v
"""

---

## Kwaliteitspoorten

Voordat een volgende fase start, moet aan deze criteria voldaan zijn:

**Na architectuur**:
- [ ] Alle componenten beschreven in docs/architecture.md
- [ ] API-endpoints geïdentificeerd
- [ ] Error handling scenario's benoemd

**Na implementatie**:
- [ ] Code draait zonder import errors
- [ ] manifest.json heeft version key
- [ ] Config flow werkt in Home Assistant UI

**Na tests**:
- [ ] Minimale 80% test coverage
- [ ] Alle tests slagen
- [ ] Error scenarios getest

**Na review**:
- [ ] Geen security issues
- [ ] Documentatie compleet
- [ ] Home Assistant best practices gevolgd

---

## Bestandsstructuur

~~~text
project-root/
├── AGENTS.md                    # Dit bestand
├── .aider.conf.yml              # Aider configuratie
├── docs/
│   ├── architecture.md          # Van architect-agent
│   ├── test-report.md           # Van tester-agent
│   ├── review.md                # Van reviewer-agent
│   └── CHANGELOG.md             # Alle wijzigingen
├── custom_components/
│   └── sometoday/
│       ├── __init__.py
│       ├── manifest.json
│       ├── config_flow.py
│       ├── coordinator.py
│       ├── sensor.py
│       ├── const.py
│       └── translations/
│           └── nl.json
└── tests/
    ├── test_config_flow.py
    └── test_sensor.py
~~~

---


*Laatste update: 2026-09-10*
*Versie: 1.0*
