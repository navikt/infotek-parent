# infotek-parent

Infotek-teamets felles plattform-repo. Her finner du verktøy for å jobbe med alle teamets repos, felles dokumentasjon og AI-konfigurasjon.

## Team-ressurser

| Ressurs | Lenke |
|---------|-------|
| 📋 Trello | [infotek](https://trello.com/b/Cq9dr1ZA/infotek) |
| 📖 Confluence | [Team Infotek](https://confluence.adeo.no/spaces/Infotek/pages/823662296/Team+Infotek) |
| 🚀 Nais Console (infotek) | [console.nav.cloud.nais.io/team/infotek](https://console.nav.cloud.nais.io/team/infotek) |
| 🚀 Nais Console (infotrygd) | [console.nav.cloud.nais.io/team/infotrygd](https://console.nav.cloud.nais.io/team/infotrygd) |
| 🚀 Nais Console (historisk) | [console.nav.cloud.nais.io/team/historisk](https://console.nav.cloud.nais.io/team/historisk) |

## Kom i gang (ny maskin / ny utvikler)

```bash
gh repo clone navikt/infotek-parent
cd infotek-parent
make setup      # installer verktøy (brew, java, gh-cli, nais-cli)
make clone      # klon alle team-repos til ./repos/
```

> **Forutsetter** at `gh` er installert og autentisert (`gh auth login`).
> Alternativt hvis SSH er satt opp: `git clone git@github.com:navikt/infotek-parent.git`

`make setup` installerer:
- `yq`, `git`, `gh` — grunnverktøy
- `nais/tap/nais` — Nais CLI
- `temurin` — Java JDK
- `navikt/tap/cplt` — GitHub Copilot CLI
- `navikt/tap/nav-pilot` — Nav Pilot AI-assistent



```
make help
```

### Repo-administrasjon

| Kommando | Beskrivelse |
|----------|-------------|
| `make clone` | Klon alle repos fra `repos.yaml` til `./repos/` (krever `make setup` først) |
| `make fetch` | `git fetch` på alle repos |
| `make pull` | `git pull` på alle repos |
| `make default` | Switch til default branch + pull alle repos |
| `make status` | Vis branch, status og parent POM-versjon for alle repos |
| `make versions` | Vis nøkkelversjoner (Java, Kotlin, Aksel, Node…) på tvers |
| `make add-repo ORG=navikt REPO=ny-app` | Registrer nytt repo i `repos.yaml` |

### Masseoppdateringer

| Kommando | Beskrivelse |
|----------|-------------|
| `make multi-commit MSG="chore: ..."` | Commit staged endringer i alle repos med samme melding |
| `make push-all` | Push alle repos som er foran remote |
| `make pr-all TITLE="chore: ..."` | Lag PRer for alle repos på feature-branch |
| `make update-kotlin VERSION=2.x.y` | Bump `kotlin.version` i alle repos + lager PRer |
| `make update-npmrc` | Synkroniser `.npmrc` til teamstandard + lager PRer |
| `make update-frontend-deps` | Bump frontend-avhengigheter fra `platform/pnpm/package.json` + lager PRer |

### Publisering

| Kommando | Beskrivelse |
|----------|-------------|
| `make release-maven VERSION=1.0.0` | Publiser ny versjon av Maven parent POM |
| `make release-npm VERSION=1.0.0` | Publiser ny versjon av `@navikt/infotek-frontend-config` |

### Typisk arbeidsflyt for endringer på tvers

```bash
# 1. Gjør endringen i berørte repos
# 2. Stage filene
git -C repos/mitt-repo add .github/dependabot.yml

# 3. Commit på tvers
make multi-commit MSG="chore: legg til dependabot.yml"

# 4. Push
make push-all

# 5. Lag PRer
make pr-all TITLE="chore: legg til dependabot.yml" BODY="Ukentlig Dependabot for Maven, npm og GitHub Actions."
```

## Struktur

```
infotek-parent/
├── repos.yaml              # kilde til sannhet — alle team-repos
├── Makefile                # alle kommandoer
├── ai/
│   └── AGENTS.md           # AI-oversikt over teamets repos og konvensjoner
├── .github/
│   ├── copilot-instructions.md
│   ├── copilot-review-instructions.md
│   ├── dependabot.yml
│   └── workflows/
│       ├── publish-parent-pom.yml
│       └── publish-frontend-config.yml
├── docs/
│   └── onboarding.md
├── platform/
│   ├── maven/
│   │   └── pom.xml         # Maven parent POM — arver spring-boot-starter-parent
│   ├── npm/
│   │   └── .npmrc          # teamstandard for npm/pnpm
│   └── pnpm/
│       ├── package.json    # @navikt/infotek-frontend-config + versjonskatalog
│       ├── tsconfig.base.json
│       └── biome.base.json
├── scripts/
│   ├── gen-agents.py
│   ├── fmt-table.py
│   ├── merge-npmrc.py
│   └── update-frontend-deps.py
└── repos/                  # alle klonede team-repos (gitignored)
```

## Legg til et nytt repo

```bash
make add-repo ORG=navikt REPO=min-app DESC="Beskrivelse av appen"
```

Dette oppdaterer `repos.yaml` og regenererer `ai/AGENTS.md` automatisk.

<!-- AUTO-GENERATED:README-REPOS START -->

## Teamets repos

### 🟦 `infotek` — [Nais Console](https://console.nav.cloud.nais.io/team/infotek)

| Repo | Beskrivelse | Miljøer | Nais |
|------|-------------|---------|------|
| [infotek-databaseuttrekk](https://github.com/navikt/infotek-databaseuttrekk) | Applikasjon for å hente ut bruksdata av infotrygdrutiner | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/infotek/app/dev-gcp/infotek-databaseuttrekk) |
| [infotek-statistikk](https://github.com/navikt/infotek-statistikk) | Infotrygd statistikk  faste uttrekk for å lage månedsrapport. | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/infotek/app/dev-gcp/infotek-statistikk) |

### 🟧 `infotrygd` — [Nais Console](https://console.nav.cloud.nais.io/team/infotrygd)

| Repo | Beskrivelse | Miljøer | Nais |
|------|-------------|---------|------|
| [infotrygd-brukeroppslag](https://github.com/navikt/infotrygd-brukeroppslag) | Intern app for brukerstøtte | dev-fss, prod-fss, dev-gcp, prod-gcp | [dev-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/dev-fss/infotrygd-brukeroppslag) · [prod-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/prod-fss/infotrygd-brukeroppslag) · [dev-gcp](https://console.nav.cloud.nais.io/team/infotrygd/app/dev-gcp/infotrygd-brukeroppslag) · [prod-gcp](https://console.nav.cloud.nais.io/team/infotrygd/app/prod-gcp/infotrygd-brukeroppslag) |
| [infotrygd-feed-proxy-v2](https://github.com/navikt/infotrygd-feed-proxy-v2) | — | dev-fss, prod-fss | [dev-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/dev-fss/infotrygd-feed-proxy-v2) · [prod-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/prod-fss/infotrygd-feed-proxy-v2) |
| [infotrygd-hentsaksliste](https://github.com/navikt/infotrygd-hentsaksliste) | Erstatter oppslag via bussen mot Infotrygd | dev-fss, prod-fss | [dev-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/dev-fss/infotrygd-hentsaksliste) · [prod-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/prod-fss/infotrygd-hentsaksliste) |
| [infotrygd-replikering](https://github.com/navikt/infotrygd-replikering) | — | dev-fss, prod-fss | [dev-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/dev-fss/infotrygd-replikering) · [prod-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/prod-fss/infotrygd-replikering) |
| [infotrygd-facade](https://github.com/navikt/infotrygd-facade) ⚠️ | — | — | — |

### 🟩 `historisk` — [Nais Console](https://console.nav.cloud.nais.io/team/historisk)

| Repo | Beskrivelse | Miljøer | Nais |
|------|-------------|---------|------|
| [historisk-avstandskalkulator](https://github.com/navikt/historisk-avstandskalkulator) | historisk-avstandskalkulator | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-avstandskalkulator) |
| [historisk-gravferdkalkulator](https://github.com/navikt/historisk-gravferdkalkulator) | Kalkulator for å regne ut stønad til gravferdsstønad og båretransport | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-gravferdkalkulator) |
| [historisk-exodus](https://github.com/navikt/historisk-exodus) | — | dev-fss, prod-fss | [dev-fss](https://console.nav.cloud.nais.io/team/historisk/app/dev-fss/historisk-exodus) · [prod-fss](https://console.nav.cloud.nais.io/team/historisk/app/prod-fss/historisk-exodus) |
| [historisk-pensjon](https://github.com/navikt/historisk-pensjon) | — | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-pensjon) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-pensjon) |
| [historisk-regnskap](https://github.com/navikt/historisk-regnskap) | — | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-regnskap) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-regnskap) |
| [historisk-tidsbegrenset-uforestonad](https://github.com/navikt/historisk-tidsbegrenset-uforestonad) | — | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-tidsbegrenset-uforestonad) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-tidsbegrenset-uforestonad) |
| [historisk-riddler](https://github.com/navikt/historisk-riddler) | historisk-riddler: Beregninger av gamle infotrygdytelser | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-riddler) |
| [historisk-valutakalkulator](https://github.com/navikt/historisk-valutakalkulator) | Valutakalkulator som viser historiske vekslingskurser. | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-valutakalkulator) |
| [historisk-avgiftssystem](https://github.com/navikt/historisk-avgiftssystem) ⚠️ | — | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-avgiftssystem) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-avgiftssystem) |

<!-- AUTO-GENERATED:README-REPOS END -->
