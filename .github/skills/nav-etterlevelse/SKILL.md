---
name: nav-etterlevelse
description: Gjennomfør etterlevelsesanalyse av et NAV-system mot etterlevelseskatalogen og generer Markdown-rapport med kodebevis
license: MIT
metadata:
  domain: compliance
  tags: etterlevelse personvern gdpr sikkerhet wcag nav audit
---

# NAV Etterlevelsesanalyse

Analyser et NAV-system mot kravene i etterlevelseskatalogen og produser en Markdown-rapport
der hvert suksesskriterium er koblet til **konkret kodebevis** (fil, klasse, metode) eller
eksplisitt merket som manglende. Generer alltid både Markdown- og HTML-versjon av rapporten.
Alle detaljblokker skal være lukket som standard i både Markdown og HTML.

**Analysen kan ikke starte før repo er valgt og brukeren har bekreftet at
dokumentasjon finnes i etterlevelseskatalogen** — se Steg 0.

Kravkilde og verktøy: `etterlevelse/` i `infotek-parent` — se `etterlevelse/README.md`
(90 aktive krav, 270 suksesskriterier, 10 temaer).

> **Navnekollisjon å være obs på:** `infotek-parent/etterlevelse/` er den delte
> verktøymappa (skript + delt kravkilde). `repos/<repo-navn>/etterlevelse/`
> er en *annen* mappe — den ligger inni det analyserte repoet og inneholder
> rapporten og repo-spesifikk `krav.json`. Bruk alltid full sti
> (`repos/<repo-navn>/etterlevelse/...`) når du refererer til repo-mappa, for
> å unngå forveksling med verktøymappa.

## Arbeidsflyt

| Steg | Hva | Output |
|------|-----|--------|
| 0.1 | 🚧 **Sperre:** avklar hvilket repo — bruk oppgitt navn, ellers `fzf`-valg | Bekreftet `<repo-navn>` |
| 0.2 | Opprett `etterlevelse/`-mappe i repoet og fastsett filnavn | `repos/<repo-navn>/etterlevelse/` |
| 0.3 | 🚧 **Sperre:** be bruker opprette/bekrefte dokumentasjon i etterlevelseskatalogen, og bekrefte at delt kravkilde er oppdatert | Bekreftelse før analysen starter |
| 1 | Systemprofil — hva gjør systemet, hvem bruker det, hvilke PII | Profiltabell |
| 2 | Filtrer krav basert på profil — `ekstraher.py --vis` | Relevansliste |
| 3 | Finn kodebevis per suksesskriterium | Bevistabell |
| 4 | Generer Markdown-rapport inkrementelt | `repos/<repo-navn>/etterlevelse/ETTERLEVELSE.md` |
| 5 | Konverter Markdown til HTML | `repos/<repo-navn>/etterlevelse/etterlevelse-rapport.html` |
| 6 | Handlingsplan med prioriterte funn | Tiltakstabell |
| 7 | Verifiser fullstendighet — `verifiser.py` | Exit code 0 |
| 8 | Be bruker importere/lime inn rapporten i dokumentasjonen | Bekreftelse fra bruker |

**Regler som ikke kan hoppes over:**

1. **Skriv aldri rapporten i én operasjon.** Lag filen tom først med
   `<!-- PLACEHOLDER -->`-ankere, deretter fyll inn seksjonsvis med `edit`.
   Store rapportgenereringer feiler ofte midt i.
2. **Kjør `verifiser.py` før levering.** Uten dette blir suksesskriterier utelatt —
   det skjer hver gang kravene leses manuelt.

3. **Generer alltid HTML i tillegg til Markdown.** Når Markdown-rapporten er
   ferdig, generer en lesbar HTML-versjon med
   `scripts/render-markdown-html.py`, med
   `repos/<repo-navn>/etterlevelse/ETTERLEVELSE.md` som input og
   `repos/<repo-navn>/etterlevelse/etterlevelse-rapport.html` som output.

4. **Lukk alt som standard.** Bruk `<details>` uten `open` i rapporten, slik at
   alle kravseksjoner starter lukket og leseren kan åpne det som er relevant.

5. **Steg 0.1 er en sperre — spør hvilket repo før noe annet.** Ikke gjett eller
   plukk et repo fra kontekst. Hvis brukeren allerede oppga et repo-navn
   (f.eks. «lag etterlevelsesrapport for infotrygd-brukeroppslag»), bruk det
   direkte og hopp over listen. Hvis brukeren **ikke** oppga noe repo (f.eks.
   «start etterlevelsessjekk»), list opp managed repos og la brukeren velge
   interaktivt med piltaster via `fzf` (installert på maskinen):

   ```bash
   yq e '.repos[] | select(.managed == true) | .name' repos.yaml \
     | fzf --prompt="Velg repo for etterlevelsessjekk> " --height=15 --border
   ```

   Har ikke terminalen støtte for `fzf` (f.eks. ikke-interaktiv kjøring), fall
   tilbake til en nummerert liste og be brukeren skrive tallet — samme mønster
   som `scripts/pr-behandle.py` bruker for kjørings-valg.

   Vent på svar før du går videre til Steg 0.2. Bruk `repos/<repo-navn>` som
   base for alt videre arbeid.

6. **Steg 0.2 — fast filnavn og plassering, ingen variasjon.** Så snart repo er
   bekreftet (Steg 0.1), lag `etterlevelse/`-mappen i målrepoet hvis den ikke
   finnes — gjør dette **før** du spør om dokumentasjon i Steg 0.3, slik at
   rapportfiler og repo-spesifikk `krav.json` har fast plassering:

   ```bash
   mkdir -p repos/<repo-navn>/etterlevelse
   ```

   Bruk alltid disse faste navnene, uavhengig av repo — det gjør rapportene
   forutsigbare på tvers av alle managed repos:

   | Fil | Sti |
   |-----|-----|
   | Markdown-rapport | `repos/<repo-navn>/etterlevelse/ETTERLEVELSE.md` |
   | HTML-versjon (obligatorisk) | `repos/<repo-navn>/etterlevelse/etterlevelse-rapport.html` |

   Legg også inn en lenke til rapportfilene i repoets `README.md` (egen
   «Ressurser»-seksjon), slik at rapporten er lett å finne fra repoforsiden.

7. **Steg 0.3 er en sperre — ikke bare et spørsmål.** Selve etterlevelseskatalogen
   (`https://etterlevelse.ansatt.nav.no/dokumentasjoner`) krever Azure AD-innlogging
   og kan ikke nås eller fylles ut automatisk fra denne skillen. **Ikke start
   systemprofil eller kodeanalyse (Steg 1+) før brukeren har svart.** Spør alltid,
   og vær eksplisitt på at denne skillen bruker delt kravkilde:

   > Har dere allerede en dokumentasjon for `<repo-navn>` på
   > https://etterlevelse.ansatt.nav.no/dokumentasjoner? Hvis ikke, opprett en
   > ny dokumentasjon der først (velg riktig team/system).
   >
   > Bekreft deretter at delt kravkilde `etterlevelse/suksesskriterier.html`
   > er riktig og oppdatert for denne kjøringen.

   Vent på svar. Fortsett kun når brukeren bekrefter at dokumentasjonen finnes
   eller er opprettet, **og** at `etterlevelse/suksesskriterier.html` skal brukes
   som kravkilde.

   Kjør deretter ekstraksjonen:

   ```bash
   # Delt kravkilde (obligatorisk)
   python3 etterlevelse/ekstraher.py \
     etterlevelse/suksesskriterier.html \
     repos/<repo-navn>/etterlevelse/krav.json
   ```

   Dette gir en **repo-spesifikk kravfil** (`repos/<repo-navn>/etterlevelse/krav.json`)
   basert på delt kilde. Bruk `repos/<repo-navn>/etterlevelse/krav.json` videre
   i Steg 2–3 for kravfiltrering og kodebevis.

   Bekreft at tallene fra ekstraksjonen er 90 krav / 270 SK før du går videre —
   avviker de, er katalogen endret og forventningene i `SKILL.md` må oppdateres
   først. Analyserapporten er et supplement med kodebevis, ikke en erstatning
   for registrert dokumentasjon i katalogen.

8. **Be bruker importere den ferdige rapporten.** Når
   `repos/<repo-navn>/etterlevelse/ETTERLEVELSE.md` er verifisert (Steg 7), er
   den kun lagret i git — den er ikke synlig i etterlevelseskatalogen. Avslutt
   derfor alltid med å be brukeren lime inn eller importere rapportens innhold
   i dokumentasjonen på `https://etterlevelse.ansatt.nav.no/dokumentasjoner`,
   siden dette verktøyet ikke har API-tilgang til katalogen og importen må
   gjøres manuelt av bruker.

## Begrepsbruk — les før du skriver

Rapporten leses av jurister og personvernombud. Feil begrepsbruk utløser unødige
runder fordi ord som «innsyn» har presis rettslig betydning.

| Skriv | Ikke skriv | Hvorfor |
|-------|-----------|---------|
| **oppslag**, oppslagsverktøy, oppslagsløsning | innsyn, innsynsverktøy, innsynsløsning | «Innsyn» = den registrertes rett etter personvernforordningen art. 15 og fvl. §§ 18–21. Fagsystemer der saksbehandler slår opp opplysninger gjør **oppslag** i kraft av tjenstlig behov |
| **oppslagslogg** | innsynslogg | Auditloggen dokumenterer oppslag. «Innsynsrapport» er derimot riktig om ArcSight-rapporten den registrerte kan be om |
| **lesetilgang**, henter data | innsyn i data | Unngå ordet der det ikke er tale om innsynsrett |
| **behandler personopplysninger** | bruker persondata | Følg forordningens ordbruk |
| **tjenstlig behov** | trenger tilgang | Rettslig vilkår, ikke praktisk behov |

**«Innsyn» skal likevel stå uendret når det er:**

1. **Kravnavn eller SK-tekst fra katalogen** — f.eks. K150.2 «NAV må kunne gi partene
   innsyn i sakens opplysninger». Siter alltid ordrett; `verifiser.py` og revisor
   matcher mot katalogen.
2. **Faktiske navn i koden** — `InnsynController`, `/api/innsyn/bruker`,
   pakkestien `no.nav.historisk.innsyn`. Rapporten skal beskrive koden som den er.
3. **Den rettslige betydningen** — «rutine for innsynsforespørsler», «innsynsrapport
   fra Team Auditlogging».

Legg inn en kort begrepsnote under Systemprofil når systemet er et oppslagssystem,
slik at leseren forstår hvorfor `innsyn` likevel forekommer i kodereferanser.

## Steg 1: Systemprofil

Kjør disse for å bygge profilen. Bruk `repos/<navn>` som base.

```bash
BASE=repos/<repo-navn>
cat $BASE/README.md
cat $BASE/nais/*.json $BASE/.nais/*.json 2>/dev/null
find $BASE/nais $BASE/.nais -name "*.yaml" 2>/dev/null | xargs cat
find $BASE -name "application*.yml" -not -path "*/target/*" -not -path "*/test/*" | xargs cat
find $BASE -name "pom.xml" -o -name "build.gradle.kts" | head -3 | xargs cat | grep -E "artifactId|implementation"
find $BASE -name "package.json" -not -path "*/node_modules/*" | head -2 | xargs cat | grep -E "@navikt|react|next"
```

Fyll ut denne tabellen — den styrer hvilke krav som er relevante:

| Egenskap | Hvordan avgjøre fra kode |
|----------|--------------------------|
| PERSONOPPLYSNINGER | Søk etter `Foedselsnummer`, `fnr`, `ident`, PDL-integrasjon |
| VEDTAKSBEHANDLING | Finnes `Vedtak`-entiteter, skriveoperasjoner, `@Transactional` write? |
| INTERN_SKJERMFLATE | `azure.application.enabled: true` + `intern.nav.no`-ingress |
| EKSTERN_SKJERMFLATE | `idporten.enabled: true` eller `nav.no`-ingress uten `intern` |
| EGETUTVIKLETSYSTEM | Egen kildekode i repo (ikke bare config) |
| PORTALLOSNING | Aggregerer flere backends i én flate |

### Integrasjoner å lete etter

```bash
grep -rn "pdl-api\|tilgangsmaskin\|populasjonstilgangskontroll\|dokarkiv\|saf\|dokdist\|kabal\|helved\|kafka\|texas\|tokenx\|wonderwall" \
  $BASE/nais $BASE/.nais 2>/dev/null
```

| Komponent | Signal i kode |
|-----------|---------------|
| PDL | `pdl-api` i accessPolicy, `PdlClient` |
| Azure AD | `azure.application.enabled` |
| Wonderwall | `azure.sidecar.enabled: true` |
| TokenX | `tokenx.enabled: true` |
| Tilgangsmaskin | `populasjonstilgangskontroll` i outbound |
| Auditlogg | `audit.nais`, `CEF:0`, `logback-syslog4j` |
| Kafka | `kafka:` i nais.yaml, `KafkaConsumer` |
| Database | `datasource.url`, Flyway-migrasjoner, `cloudsql` |

## Steg 2: Filtrer krav

**Les aldri kravene direkte fra HTML-kilden.** Suksesskriterier blir utelatt —
flere krav har 5–8 SK, og SK-numrene er verken sekvensielle eller sorterte.
Bruk verktøyene i `etterlevelse/`:

```bash
# Kravlisten ligger ferdig ekstrahert i etterlevelse/krav.json
# Regenerer kun hvis katalogen er oppdatert:
python3 etterlevelse/ekstraher.py
```

Forventet: `90 krav, 270 suksesskriterier`. Avviker tallene, er katalogen endret —
oppdater forventningen i denne skillen.

Skriv ut alle SK for kravene du skal vurdere — **gjør dette før du skriver rapporten**:

```bash
python3 etterlevelse/ekstraher.py --vis K154.1 K255.1 K267.1 K218.1
```

Trenger du å filtrere programmatisk:

```bash
python3 -c "
import json
krav = json.load(open('etterlevelse/krav.json'))
for k in krav:
    if k['tema'] in ('personvern', 'infosikkerhet'):
        print(f\"{k['id']:9} [{len(k['sks'])} SK] {k['navn']}\")
"
```

### Hvilke temaer er relevante

Bruk profilen til å avgjøre. Typisk er 35–40 av 90 krav relevante for et oppslagssystem.

| Tema | Relevant når |
|------|--------------|
| Personvern (19 krav) | PERSONOPPLYSNINGER = Ja |
| Informasjonssikkerhet (4 krav) | Alltid |
| Saksbehandling (21 krav) | VEDTAKSBEHANDLING = Ja. Ellers kun K154 (taushetsplikt), K205, K218 |
| Økonomi (15 krav) | Systemet utbetaler eller fatter økonomiske vedtak |
| Arkiv (ca. 10 krav) | Systemet lagrer dokumenter eller er journalpliktig |
| Interoperabilitet (4 krav) | Alltid — særlig K264 (autoritative kilder) |
| Universell utforming (4 krav) | Har brukergrensesnitt |
| Statistikk (2 krav) | VEDTAKSBEHANDLING = Ja |
| Språk (2 krav) | EKSTERN_SKJERMFLATE = Ja |
| Elektronisk kommunikasjon (11 krav) | Kommuniserer med innbygger. K205/K218 gjelder alltid |

**Regel:** Marker aldri et krav som «ikke relevant» uten begrunnelse i rapporten.
Revisor må kunne se hvorfor kravet er utelatt.

### Full dekning av alle kriterier (obligatorisk)

Rapporten skal alltid ha **full dekning av alle 90 krav** i kravkilden, og hvert
krav skal vurderes i egen `<details>`-blokk med **alle suksesskriterier (SK) listet**.

1. Alle krav skal detaljvurderes (ingen krav kun i samleoversikt).
2. Alle SK for hvert krav skal ha status og begrunnelse, også ved `➖ Ikke aktuelt`.
3. Ikke bruk en separat «Full kravoversikt (90/90)»-seksjon som erstatning for
   detaljvurdering.
4. **Alle 270 suksesskriterier skal alltid besvares** i hver seksjon under de
   90 kravene (én rad per SK med status + begrunnelse).

### SK-numre er ikke sekvensielle — bind alltid til faktisk `n` (obligatorisk)

**Den vanligste feilen ved automatisert/skriptet generering:** å anta at SK-numrene
for et krav går 0, 1, 2, 3 … i rekkefølge. De gjør de **ikke** — `n`-verdiene i
`krav.json` er ofte hull i sekvensen og i vilkårlig rekkefølge. Eksempler fra faktiske
krav:

```
K255.1: SK 0, 2, 10, 5, 3, 9, 7, 8   (8 SK, ikke 0-7)
K253.1: SK 0, 1, 3, 6, 4, 5          (6 SK, ikke 0-5)
K264.1: SK 0, 1, 2, 3                (starter på 0, ikke 1)
K271.1: SK 0, 4                      (kun 2 SK, med hull)
```

Hvis du (eller et script) bygger SK-rader ved å anta sekvensiell rekkefølge, ender
begrunnelsen opp koblet til **feil SK-tekst**, eller reell SK-tekst blir aldri lest og
faller tilbake til en generisk frase som `Ikke aktuelt gitt systemprofilen.` uten
noen tilknytning til hva kriteriet faktisk sier — se f.eks. `SK 9 — Vi er varsomme
ved deling av andre geolokaliserende opplysninger enn adresse` under K255.1, som er
lett å overse fordi det ikke er SK 4 slik sekvensiell numrering ville tilsi.

**Regel:** Hent alltid de faktiske `n`-verdiene og SK-tekstene direkte fra
`krav.json` (`k[kid]['sks']`) for kravet du vurderer, og skriv begrunnelsen med
eksplisitt referanse til hva **den konkrete SK-teksten** ber om — ikke en
tema-generisk frase. Kjør gjerne:

```bash
python3 -c "
import json
k = {x['id']: x for x in json.load(open('etterlevelse/krav.json'))}
for s in k['K255.1']['sks']:
    print('SK', s['n'], '-', s['d'])
"
```

før du skriver rader for et krav, slik at hver rad er koblet til riktig `n` og
begrunnelsen er utfyllende nok til å vise at du har lest selve kriteriet — også
for `➖ Ikke aktuelt`-rader (forklar *hvorfor akkurat dette kriteriet* ikke gjelder,
ikke bare at temaet generelt er uaktuelt).

### Relevanskontroll før «ikke aktuelt» (obligatorisk)

Før du markerer et tema eller krav som `➖ Ikke aktuelt`, gjør alltid denne sjekken:

1. Er kravet egentlig dekket av et **nærliggende tema** (f.eks. dokumentasjon/sporbarhet under elektronisk kommunikasjon eller auditlogg), selv om hovedtemaet virker uaktuelt?
2. Finnes det tekniske spor i kode/konfig som likevel gjør kravet relevant (auth, audit, logger, hendelsesspor, feilhåndtering)?
3. Er «ikke aktuelt» begrunnet med **hva systemet faktisk gjør**, ikke bare systemtype?

Typisk fallgruve: å markere «Arkiv og journalføring» som ikke aktuelt og samtidig
glemme at **dokumentasjon av elektroniske aktiviteter** fortsatt kan være relevant
og skal vurderes under f.eks. `K218.1` (elektronisk kommunikasjon) og `K253.1`
(oppslagslogg/auditlogg).

### Krav som ALLTID skal vurderes

Disse gjelder uansett systemtype når systemet behandler personopplysninger:

| Krav | Hva |
|------|-----|
| K107.2 | Behandlingsgrunnlag dokumentert (behandlingsnummer i nais-config) |
| K109.1 | FNR kun der nødvendig |
| K253.1 | Oppslagslogg til ArcSight ved visning av PII |
| K255.1 | Adressebeskyttelse håndtert |
| K267.1 | Forsvarlig sikkerhetsnivå (7 suksesskriterier) |
| K154.1 | Taushetsplikt — rollebasert tilgang |
| K205.2 | Utenforstående får ikke innsyn |
| K218.1 | Identitet dokumentert på elektroniske aktiviteter |

## Steg 3: Finn kodebevis

For hvert relevant suksesskriterium: finn **fil + klasse + metode** som implementerer det,
eller dokumenter at bevis mangler. Ingen påstander uten filreferanse.

### K253.1 — Oppslagslogg (ArcSight)

```bash
grep -rn "CEF:0\|auditLogger\|audit:access" $BASE --include="*.kt" --include="*.xml"
grep -rn "logSoek\|logOppslag\|AuditLog" $BASE --include="*.kt"
```

Sjekk i rekkefølge:
1. Finnes en `AuditLog`-komponent som skriver CEF-format?
2. Kalles den **etter** at data er hentet, ikke før? (SK 1: logg kun ved faktisk visning)
3. Inneholder loggen `suid` (NAVident), `duid` (FNR), `flexString1` (Permit/Deny)?
4. Logges det ved både PERMIT og DENY?
5. Logges systembrukere? (skal ikke — sjekk `navIdent() ?: return`)

### K255.1 — Adressebeskyttelse

```bash
grep -rn "tilgangsmaskin\|populasjonstilgang\|skjerming\|adressebeskyttelse" $BASE --include="*.kt"
```

Kritisk: Kalles tilgangssjekken for **hvert** oppslag, eller bare ved innlogging?
Se etter `sjekkTilgang(fnr)` i service-laget før datauthenting.

### K267.1 — Forsvarlig sikkerhetsnivå (7 SK)

```bash
# SK0+1: Sårbarhetshåndtering
ls $BASE/.github/workflows/codeql.yml $BASE/.github/dependabot.yml

# SK2: Input-validering
grep -rn "@Valid\|require(\|validerIdentifikator\|modulo11" $BASE --include="*.kt"

# SK3: Hemmeligheter
grep -rn "vault:\|envFrom\|secretName" $BASE/nais $BASE/.nais 2>/dev/null
grep -rniE "password\s*=\s*\"|apikey\s*=\s*\"" $BASE --include="*.kt" --include="*.ts"

# SK6: Tilgangskontroll på ALLE endepunkter — viktigste sjekk
grep -rn "@Unprotected\|permitAll\|@Profile" $BASE --include="*.kt"
grep -rn "@RestController" $BASE --include="*.kt" -l
```

**SK6 er der man oftest finner reelle avvik.** For hver `@RestController`: verifiser
at den har `@Protected` eller tilsvarende. `@Unprotected` på endepunkter som
returnerer personopplysninger, forretningsdata, hemmeligheter eller muliggjør
tilstandsendringer er et kritisk funn.

Ikke klassifiser tekniske metadataendepunkter som `/tables` automatisk som
kritiske. Vurder alltid:

1. Hvilke data endepunktet faktisk returnerer — Hibernate-mappede tabell- og
   kolonnenavn er metadata, ikke databaseinnhold.
2. Om Nais `accessPolicy.inbound` begrenser trafikken til navngitte applikasjoner.
3. Om endepunktet har applikasjonsautentisering og eventuell admin-sjekk.
4. Om det finnes et dokumentert operativt behov for metadataoppslaget.
5. Om alternativet er direkte produksjonsdatabasetilgang med bredere
   rettigheter og høyere risiko.

Et metadataendepunkt med begrenset inbound-policy og legitimt operativt behov er
normalt et forsvar-i-dybden-funn, ikke et kritisk avvik. Anbefal som hovedregel
`@Protected` kombinert med eksisterende admin-autorisasjon, mens Nais-policyen
beholdes som ytre lag. Fjerning i produksjon er aktuelt bare når endepunktet ikke
har et reelt behov. Dokumenter og begrunn eventuell akseptert restrisiko.

### K109.1 — FNR-bruk og PII i logger

```bash
# PII-lekkasje i logger — GDPR-brudd hvis funnet
grep -rn "logger\.\|log\." $BASE --include="*.kt" | grep -iE "fnr|fødsel|foedsel|navn|adresse" | grep -v -i "auditlog"

# FNR i URL-path (skal være POST body)
grep -rn "@PathVariable.*fnr\|@RequestParam.*fnr" $BASE --include="*.kt"
```

### K195.1 / K196.6 — Universell utforming

```bash
grep -E "@navikt/ds-react|@navikt/ds-css" $BASE/**/package.json
grep -rn "axe\|a11y\|toMatchAriaSnapshot" $BASE --include="*.ts" --include="*.tsx" \
  --exclude-dir=node_modules
grep -rn "dangerouslySetInnerHTML" $BASE --include="*.tsx" --exclude-dir=node_modules
```

### K264.1 — Autoritative kilder

Verifiser at persondata hentes fra PDL, ikke fra lokal kopi eller annen kilde.

### NAIS-avvik som påvirker flere krav

```bash
grep -A6 "resources:" $BASE/nais/**/*.yaml   # CPU limits = feil (kun requests)
grep -A10 "accessPolicy:" $BASE/nais/**/*.yaml  # inbound må være eksplisitt
grep -n "maximumPoolSize\|maximum-pool-size" $BASE -r --include="*.yml"  # skal være ≤3
```

### Statuskoder i rapporten

| Status | Betydning |
|--------|-----------|
| ✅ Oppfylt | Konkret kodebevis funnet — fil og metode oppgitt |
| ⚠️ Delvis | Delvis implementert, eller krever dokumentasjon utenfor kode |
| ⚠️ Mangler bevis | Kan ikke verifiseres fra kodebase (typisk Behandlingskatalog-krav) |
| 🔴 Kritisk | Konkret avvik funnet i kode som må rettes |
| ➖ Ikke aktuelt | Ikke relevant gitt systemprofilen — **alltid med begrunnelse** |

## Steg 4: Generer Markdown-rapport

Legg rapporten i **det analyserte repoet** som `etterlevelse/ETTERLEVELSE.md`
(i repoets egen `etterlevelse/`-mappe, ikke den delte verktøymappa i
`infotek-parent`).

### Inkrementell generering — obligatorisk

Store filer feiler ofte midtveis. Følg denne rekkefølgen:

1. `create` — minimal stubb med HTML-kommentar-placeholders
2. `edit` — tittel + oppsummering → erstatt `<!-- SUMMARY -->`
3. `edit` — systemprofil → erstatt `<!-- PROFIL -->`
4. `edit` — ett tema om gangen → erstatt `<!-- TEMA-N -->`
5. `edit` — handlingsplan → erstatt `<!-- TILTAK -->`

Hver `edit` legger inn neste placeholder for påfølgende seksjon.
HTML-kommentarer er usynlige i rendret Markdown og fungerer som trygge ankerpunkter.

### Stubb

```markdown
# Etterlevelsesrapport — <system>

<!-- SUMMARY -->
<!-- PROFIL -->
<!-- TEMA-1 -->
<!-- TILTAK -->
```

### Header og oppsummering

```markdown
# Etterlevelsesrapport — infotrygd-brukeroppslag

| | |
|---|---|
| **System** | infotrygd-brukeroppslag |
| **Behandlingsnummer** | B780 |
| **Generert** | 2026-08-19 |
| **Kilde** | Kodeanalyse av `navikt/infotrygd-brukeroppslag` |
| **Kravreferanse** | `infotek-parent/etterlevelse/krav.json` (90 krav, 270 SK) |

## Oppsummering

| Status | Antall |
|--------|-------:|
| ✅ Oppfylt | 14 |
| ⚠️ Delvis / mangler dokumentasjon | 9 |
| 🔴 Kritisk funn | 3 |
| ➖ Ikke relevant | 22 |
```

### Systemprofil

```markdown
## Systemprofil

| Egenskap | Vurdering | Begrunnelse |
|----------|-----------|-------------|
| PERSONOPPLYSNINGER | ✅ Ja | FNR, navn, trygdehistorikk |
| VEDTAKSBEHANDLING | ❌ Nei | Kun oppslag — fatter ingen vedtak |
| INTERN_SKJERMFLATE | ✅ Ja | `intern.nav.no`, Azure AD |
| EKSTERN_SKJERMFLATE | ❌ Nei | Ingen ID-porten |
| EGETUTVIKLETSYSTEM | ✅ Ja | Kotlin + React |
| PORTALLOSNING | ❌ Nei | Dedikert applikasjon |

**Integrasjoner:** PDL · Azure AD (Wonderwall + OBO) · Tilgangsmaskin ·
Oracle/Infotrygd (FSS) · Vault · Audit syslog (CEF/ArcSight) · NAIS
```

### Temaseksjon — bruk `<details>` for kollaps

```markdown
## 🔴 Personvern

<details open>
<summary><strong>K253.1</strong> — Visning av PII skal skrives til oppslagslogg — ✅ Oppfylt</summary>

*Personvernforordningen art. 6*

| SK | Krav | Status | Bevis / Funn |
|----|------|--------|--------------|
| SK 0 | PII som vises logges til oppslagslogg | ✅ | `AuditLog.kt` skriver CEF til `audit.nais:6514`, kalles fra `BrukeroppslagService.hentData()` |
| SK 1 | Logger kun ved faktisk visning | ✅ | Kalles etter datauthenting, med PERMIT/DENY |
| SK 4 | Avklart med Team Auditlogging | ⚠️ | Kan ikke verifiseres fra kodebase |

</details>
```

Bruk `<details open>` for temaer med kritiske funn, `<details>` for resten.
Filreferanser settes i backticks — de blir klikkbare i GitHub når stien er relativ,
f.eks. `backend/src/main/kotlin/.../AuditLog.kt`.

### Temaoverskrifter

| Tema | Overskrift |
|------|-----------|
| Personvern | `## 🔴 Personvern` |
| Informasjonssikkerhet | `## 🛡️ Informasjonssikkerhet` |
| Saksbehandling | `## ⚖️ Saksbehandling og forvaltningsrett` |
| Universell utforming | `## ♿ Universell utforming` |
| Interoperabilitet | `## 🔗 Interoperabilitet` |
| Ikke-relevante temaer | `## ➖ Ikke aktuelle temaer` — samle i én tabell med begrunnelse |

## Steg 5: Handlingsplan
Avslutt rapporten med prioriterte tiltak. Kun funn med konkret filreferanse.

```markdown
## 🔴 Kritiske funn som krever tiltak

| Prioritet | Krav | Funn | Fil | Tiltak |
|-----------|------|------|-----|--------|
| ⚠️ Viktig | K267.1 SK6 | `/tables` er `@Unprotected` og viser Hibernate-mappet tabellstruktur; inbound-policy begrenser trafikken | `backend/.../TableController.kt` | Avklar operativt behov. Behold helst endepunktet med `@Protected` og admin-sjekk dersom alternativet er bredere DB-tilgang; fjern i produksjon hvis behov mangler |
| ⚠️ Viktig | K267.1 SK2 | Mangler modulo-11-validering av FNR | `backend/.../validerIdentifikator.kt` | Implementer modulo-11-sjekk |
| ⚠️ Bør gjøres | K196.6 SK5 | Ingen automatiserte UU-tester i pipeline | `frontend/playwright.config.ts` | Legg til `axe-playwright` |
```

Prioritering:

| Nivå | Kriterium |
|------|-----------|
| 🔴 Kritisk | PII-lekkasje, manglende tilgangskontroll, hardkodede hemmeligheter |
| ⚠️ Viktig | Manglende auditlogg-bekreftelse, svak validering, manglende adressebeskyttelse-UI |
| ⚠️ Bør gjøres | Manglende automatiserte UU-tester, dokumentasjonshull |

## Steg 6: Verifiser fullstendighet — obligatorisk

**Kjør alltid dette før du leverer.** Skriptet fanger den vanligste feilen i
etterlevelsesanalyse — utelatte suksesskriterier.

```bash
python3 etterlevelse/verifiser.py repos/<repo>/etterlevelse/ETTERLEVELSE.md
```

Skriptet sjekker seks ting og returnerer exit code 1 ved avvik:

| # | Sjekk | Typisk feil |
|---|-------|-------------|
| 1 | Alle SK dekket per detaljvurdert krav | K255.1 har 8 SK, ikke 2 |
| 2 | Ingen krav vurdert dobbelt | Samme krav i to temaseksjoner |
| 3 | Kravregnskapet går opp mot katalogen | Detaljvurdert + temanivå ≠ 90 |
| 4 | Statustall i oppsummeringen stemmer | Tallene skrives tidlig og blir utdaterte |
| 5 | Ingen gjenglemte `<!-- PLACEHOLDER -->` | Rest fra inkrementell bygging |
| 6 | Alle krav har statusemoji i overskriften | Glemt `— ✅ Oppfylt` i `<summary>` |
| 7 | Begrepsbruk — «oppslag» framfor «innsyn» *(rådgivende)* | «innsynsverktøy» om et oppslagssystem |

Forventet output ved suksess:

```
repos/infotrygd-brukeroppslag/etterlevelse/ETTERLEVELSE.md
  ✓ Alle 121 SK dekket for 38 detaljvurderte krav
  38 detaljvurdert + 52 på temanivå = 90 krav totalt
  Status i innhold: ✅ 6  ⚠️ 16  🔴 1  ➖ 15
```

Ved avvik — rett opp og kjør på nytt til det er grønt. Sjekk 4 slår ut nesten
alltid første gang, fordi oppsummeringstabellen skrives før innholdet er ferdig.

Verifiser alle repos samtidig:

```bash
python3 etterlevelse/verifiser.py --alle
```

> **Merk:** Verifiseringen krever at rapporten følger formatet i Steg 4 —
> `<summary><strong>KID</strong> — navn — status</summary>` og SK-rader som
> starter med `| SK N |`. Avvik fra formatet gir falske treff.


## Masseanalyse på tvers av repoer

Se hvilke managed repos som mangler rapport:

```bash
for repo in $(yq e '.repos[] | select(.managed == true) | .name' repos.yaml); do
  if [ -f "repos/$repo/etterlevelse/ETTERLEVELSE.md" ]; then
    n=$(grep -c '<summary><strong>K' "repos/$repo/etterlevelse/ETTERLEVELSE.md")
    printf "  %-40s ✓ %s krav vurdert\n" "$repo" "$n"
  else
    printf "  %-40s — ingen rapport\n" "$repo"
  fi
done
```

Verifiser alle eksisterende rapporter i én operasjon:

```bash
python3 etterlevelse/verifiser.py --alle
```

Kjør selve analysen **per repo i separate sesjoner** — ikke i én lang tråd. Hvert
system har egen profil og krever egen kravfiltrering. Å blande flere repoer i samme
kontekst gir sammenblandet kodebevis.

Når katalogen oppdateres med nye krav, avdekker `--alle` hvilke rapporter som er
utdaterte (kravregnskapet går ikke lenger opp mot 90).

**Copilot committer ikke.** Etter generert rapport, presenter denne for utvikleren:

```bash
git checkout -b docs/etterlevelse-rapport
git add etterlevelse/ETTERLEVELSE.md
git commit -m "docs: legg til etterlevelsesrapport mot NAV etterlevelseskatalog"
git push -u origin docs/etterlevelse-rapport
gh pr create --title "docs: etterlevelsesrapport" --body "Analyse mot etterlevelseskatalogen med kodebevis per suksesskriterium."
```

## Vanlige funn i infotek-repoene

Basert på analyse av `infotrygd-brukeroppslag`:

| Funn | Krav | Hvor det typisk sitter |
|------|------|------------------------|
| `@Unprotected` på debug/skjema-endepunkt | K267.1 SK6 | `TableController`, `DebugController` — risikovurder data, inbound-policy, admin-sjekk, operativt behov og alternativ DB-tilgang før prioritering |
| Manglende modulo-11-validering av FNR | K267.1 SK2 | `validerIdentifikator.kt` |
| CPU limits satt i nais.yaml | Plattformavvik | `nais/app/*.yaml` |
| Ingen axe/a11y i byggepipeline | K196.6 SK5 | `playwright.config.ts` |
| Behandlingsnummer satt, men katalog uverifisert | K107.2 SK1 | `nais/*.json` → `APP_BEHANDLINGSNUMMER` |
| Adressebeskyttelse blokkerer, men uten UI-merking | K255.1 SK2 | Feilmeldingskomponent |

Legacy-systemer mot Infotrygd/Oracle er typisk **ikke** omfattet av arkiv-, økonomi-
og statistikkrav siden de er rene oppslagsløsninger uten skriveoperasjoner.

## Relatert

| Ressurs | Bruk til |
|---------|----------|
| `etterlevelse/README.md` | Verktøybruk og oppdatering av kravkilden (rapportformat: se Steg 4 her) |
| `etterlevelse/krav.json` | Alle 90 krav med suksesskriterier — fasit for fullstendighet |
| `etterlevelse/ekstraher.py` | Regenerer `krav.json`, viser SK per krav (`--vis`) |
| `etterlevelse/verifiser.py` | Obligatorisk kvalitetssjekk av ferdig rapport |
| `$security-review` | Teknisk sikkerhetssjekk før commit |
| `$threat-model` | STRIDE-A trusselmodellering (K245.1 SK2) |
| `$nav-architecture-review` | ADR for arkitekturbeslutninger |
| `@security-champion-agent` | Compliance-spørsmål og verdivurdering |
| `@accessibility-agent` | WCAG-detaljer for K196.6 |
| Behandlingskatalogen | Verifiser K107.2, K111.1, K191.1 utenfor kode |

## Begrensninger

Denne skillen verifiserer **teknisk implementasjon**. Følgende kan ikke avgjøres
fra kodebasen og må verifiseres manuelt:

- Behandlingsgrunnlag og formålsvurdering (Behandlingskatalogen)
- Verdivurdering og risikovurdering (Seksjon for helhetlig sikkerhet og beredskap)
- Databehandleravtaler og tredjepartsrelasjoner
- Bekreftelse fra Team Auditlogging på loggmottak i produksjon
- Brukertesting med reelle brukere og hjelpemidler

Marker disse som «⚠️ Mangler bevis» — ikke som avvik.

## Svarformat (obligatorisk)

Svar alltid **punkt for punkt** i nummerert liste (`1. 2. 3.`), slik at hvert funn,
hver vurdering og hvert tiltak kan gjennomgås manuelt.
