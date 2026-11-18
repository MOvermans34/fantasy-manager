# Fantasy Manager

Een web-app in Football Manager-stijl voor je hele ESPN fantasy football league: live tracking, advanced analytics per speler, scouting van defenses en gebundeld nieuws. Eén server bedient de hele league; elke deelnemer kiest zijn eigen team.

## Schermen

| Scherm | Wat je ziet |
|---|---|
| **League** | De stand en alle matchups van deze week met live scores en winkansen. Klik op een team om de app als dat team te bekijken. |
| **Overzicht** | Live stand en winkans tegen je tegenstander, een **inbox** met meldingen (blessures, bye-weken in je opstelling, wissel- en waiver-tips, gunstige of lastige matchups, nieuws), je opstelling en de scheme-matchups van je starters. |
| **Selectie** | Je selectie met kwaliteit (1-20), vorm (punten t.o.v. projectie), matchupcijfer, snap-%, gebruik en het verloop over het seizoen. Er zijn drie weergaven: overzicht, attributen en gebruik & efficiëntie. |
| **Spelerprofiel** | **Attributen 1-20**, punten per week met snap-%, seizoensstats en de tabbladen: **Splits** (targetdiepte, richting, vs blitz, play-action, motion, boxcount), **Matchup** (scheme-model met uitleg per factor, ESPN-outlook, scoutingrapport en coverage per verdediger), Wedstrijdlog, Nieuws en Vergelijk (attributen naast een concurrent). |
| **Wedstrijdcentrum** | Live punten per speler met statregel, wedstrijdstatus en red zone-indicator, de verwachte eindstand, de winkans en een live-ticker met puntwijzigingen. Tijdens wedstrijden ververst dit elke 30 seconden. |
| **Spelersmarkt** | Alle spelers per positie met advanced metrics (targetshare, WOPR, aDOT, EPA, YACOE, separatie, RYOE, goal-line share, CPOE…). Je kunt filteren op *vrij/waivers* in je league en sorteren op elke kolom. |
| **Scouting defenses** | Alle 32 defenses: EPA toegestaan, blitz-%, druk-%, boxcount, diepe passes en PPR toegestaan per positie. Klik door voor het volledige rapport met coverage per cornerback en safety. |
| **Nieuws** | ESPN-artikelen en -analyses plus Rotowire-spelersupdates, te filteren op bron, je eigen team, de tegenstander en per speler. |

## Delen met je league

De server leest de league met **jouw** ESPN-cookies. Je vrienden hebben geen cookies nodig:

1. Ze openen het adres van de app en vullen de **toegangscode** in die jij ze geeft.
2. Ze kiezen hun team uit de lijst (teamnaam, eigenaar en team-ID). Dat onthoudt de app op hun apparaat.
3. Op de telefoon installeren ze de app via *Delen → Zet op beginscherm* (iPhone) of *⋮ → App installeren* (Android).

Een directe link naar een team kan ook: `https://jouw-adres/?team=3`. Met de knop **Link** linksboven kopieer je die. Alle schermen (overzicht, selectie, wedstrijdcentrum, nieuws, waiver-tips) werken dan voor dat team.

**Veiligheid:**
- Je `espn_s2`-cookie geeft volledige toegang tot je ESPN-account. Die blijft alleen op de server en wordt nooit naar een browser gestuurd.
- De app doet alleen leesverzoeken, dus er wordt niets aan opstellingen veranderd.
- Zet altijd een `ACCESS_CODE`, anders kan iedereen met het adres je league zien.
- Lekt de cookie toch uit, log dan uit op ESPN. Daarmee wordt `espn_s2` ongeldig, en daarna zet je de nieuwe waarde op de server.

## Online zetten op Render

De repo bevat een `Dockerfile` en een Render Blueprint (`render.yaml`). Daarmee staat de app in ongeveer 10 minuten online.

### 1. Code op GitHub

Render deployt vanuit een Git-repo. Maak op GitHub een **privé**-repository aan (bijv. `fantasy-manager`) en zet de inhoud van deze map erin. Gebruik geen `config.json`; die staat in `.gitignore`.

### 2. Blueprint in Render

1. Maak een account op render.com en koppel je GitHub-account.
2. Kies **New → Blueprint** en selecteer je repo. Render leest `render.yaml` in.
3. Render vraagt om drie geheime waarden:

| Variabele | Waarde |
|---|---|
| `ESPN_S2` | je espn_s2-cookie |
| `ESPN_SWID` | je SWID-cookie, inclusief `{ }` |
| `ACCESS_CODE` | een code die je met je league deelt, bijv. `touchdown-2026` |

   `LEAGUE_ID` (519181463), `TEAM_ID` (2) en `SEASON` (2026) staan al in de Blueprint.
4. Klik op **Apply**. De eerste build duurt een paar minuten. Daarna krijg je een adres als `https://fantasy-manager-xxxx.onrender.com`.

### 3. Delen

Stuur je vrienden het adres en de toegangscode. Ze kiezen hun team en kunnen de app op hun beginscherm zetten.

### Gratis of Starter?

| Plan | Kosten | Gedrag |
|---|---|---|
| `free` (standaard in de Blueprint) | € 0 | Valt na 15 minuten zonder bezoek in slaap. Het eerste bezoek daarna duurt ongeveer een minuut. Zolang iemand de app open heeft, blijft hij wakker (de app ververst elke 15 seconden), dus tijdens wedstrijden werkt live tracking zolang er iemand kijkt. Nieuwsgeschiedenis en data-cache beginnen na elke slaap opnieuw. |
| `starter` | $7 per maand | Altijd aan. De live-ticker loopt ook door als niemand kijkt en de app reageert direct. |

Overstappen doe je in Render onder *Settings → Instance Type*, of door in `render.yaml` `plan: starter` te zetten. Op een betaald plan kun je ook een schijf koppelen (zie het commentaar in `render.yaml`), zodat nieuws en cache bewaard blijven.

De app gebruikt ongeveer 135 MB geheugen, met een piek van ongeveer 365 MB bij een koude start. Dat past binnen de 512 MB van beide plannen.

### Onderhoud

- **Cookie verlopen** (de app meldt "401"): haal nieuwe `espn_s2`/`SWID`-waarden uit je browser en zet ze in Render onder *Environment*. De service herstart dan vanzelf.
- **Nieuw seizoen:** pas `SEASON` aan (en `LEAGUE_ID` als die verandert).
- **Updates aan de code:** push naar GitHub en Render deployt automatisch.
- **Logs:** in Render onder *Logs*. Je ziet daar wanneer ESPN, het nieuws en de analytics zijn ververst.

### Alternatief: zonder hosting

Het kan ook op je eigen computer, met Cloudflare Tunnel voor een publiek adres. Dan moet je computer aan blijven tijdens de wedstrijden:

1. Zet `access_code` in `config.json` en start de server:
   ```bash
   python3 server.py --no-open
   ```
2. Start in een tweede terminal de tunnel:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. Deel het `https://…trycloudflare.com`-adres dat verschijnt.

## Installatie lokaal (eenmalig)

Je hebt Python 3.9 of nieuwer nodig.

```bash
cd ff-dashboard
python3 -m pip install -r requirements.txt
cp config.example.json config.json
```

Op Windows gebruik je `py` in plaats van `python3` en `copy` in plaats van `cp`.

Je league is **privé**, dus de app heeft twee cookies van je ESPN-login nodig:

1. Log in op fantasy.espn.com in Chrome, Edge of Firefox.
2. Open de ontwikkelaarstools (F12) → **Application** (Firefox: **Storage**) → **Cookies** → `https://fantasy.espn.com`.
3. Kopieer de waarde van `espn_s2` en van `SWID` (inclusief de `{ }`) naar `config.json`.

Deel `config.json` met niemand: met deze cookies kan iemand in je ESPN-account. Krijg je een melding "401", kopieer de cookies dan opnieuw. Liever geen cookies in een bestand? Zet ze dan in de omgevingsvariabelen `ESPN_S2` en `ESPN_SWID`.

## Starten

```bash
python3 server.py
```

De browser opent op http://localhost:8000 (lokaal is geen toegangscode nodig als je die niet instelt). De eerste start duurt ongeveer een halve minuut, omdat de nflverse-datasets (~15 MB) worden gedownload. Daarna staan ze in `data/cache/`.

| Optie | Wat het doet |
|---|---|
| `--demo` | demoselectie met openbare data, geen cookies nodig |
| `--week 10` | een andere speelronde (handig om het wedstrijdcentrum terug te kijken) |
| `--lan` | ook bereikbaar op je telefoon via hetzelfde wifi (het adres verschijnt in de terminal) |
| `--port 8080` | een andere poort |
| `--no-open` | de browser niet automatisch openen |

Laat de app tijdens de wedstrijden gewoon draaien. Hij ververst vanzelf:

| Data | Interval |
|---|---|
| Live scores | 30 s tijdens wedstrijden, anders 5 min |
| Nieuws | 5 min |
| ESPN-projecties en selecties | 15 min |
| nflverse-analytics | 6 uur |

De intervallen pas je aan in `config.json` onder `intervals`.

## Databronnen

| Bron | Wat |
|---|---|
| **ESPN Fantasy API** (onofficieel) | league, selecties, projecties in jouw scoring, live punten, outlooks, blessurestatus, eigendom-% |
| **ESPN NFL-scoreboard** | wedstrijdstatus, klok, score, balbezit, red zone |
| **nflverse** (gratis, open data) | play-by-play met EPA/CPOE/xYAC, **FTN-charting** (blitz, pass rushers, box, play-action, motion, vangbare/contested ballen, drops), **Next Gen Stats** (separatie, cushion, RYOE, time to throw), snap counts, **PFR coverage-stats per verdediger** |
| **Nieuws** | ESPN-artikelen, Rotowire-updates via ESPN en de Rotowire-RSS-feed |

### Over coverage (man/zone)

De gratis FTN-charting bevat **geen man/zone- of Cover 1/2/3-labels**: die data is alleen betaald beschikbaar (PFF, FTN Data, Fantasy Points). Het scheme-model gebruikt daarom de signalen die wel gratis zijn: blitz-frequentie, druk, boxcount, play-action, targetdiepte, richting en wat een defense per positie weggeeft, plus coverage-stats per verdediger. Mocht je later een betaalde bron nemen, dan kan die er als extra factor bij.

## Hoe de analytics werken

- **Attributen (1-20):** het percentiel van een speler binnen zijn positie, alleen vergeleken met spelers met voldoende volume (WR ≥15 targets, TE ≥12, RB ≥25 carries, QB ≥80 dropbacks). "Kwaliteit" is het gemiddelde van de attributen.
- **Scheme-matchup (0-100, A+ t/m F):** het spelerprofiel naast de tendensen van de tegenstander. Per factor (targetdiepte, richting, vs positie, blitz, play-action, run defense, boxcount, druk, diepe bal) wordt het verwachte EPA-effect berekend. Kleine samples worden naar het league-gemiddelde getrokken. 50 is neutraal. Op het matchup-tabblad zie je per factor de uitleg.
- **Winkans:** de huidige punten plus de projectie maal de resterende speeltijd, met een onzekerheid die afneemt naarmate de wedstrijden vorderen.
- **Vorm:** punten t.o.v. de ESPN-projectie per week (blauw ≥ +3, grijs ±3, rood ≤ −3).

De ESPN-API is onofficieel. Als ESPN daar iets aan verandert, kan een deel tijdelijk niet werken. nflverse-data wordt meestal binnen een dag na de wedstrijden bijgewerkt.
