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
make git-clone  # klon alle team-repos til ./repos/
```

> **Forutsetter** at `gh` er installert og autentisert (`gh auth login`).
> Alternativt hvis SSH er satt opp: `git clone git@github.com:navikt/infotek-parent.git`

`make setup` installerer:
- `yq`, `git`, `gh`, `maven`, `pnpm` — grunnverktøy
- `nais/tap/nais` — Nais CLI
- `temurin` — Java JDK
- `copilot-cli` — GitHub Copilot CLI
- `navikt/tap/cplt` — sandbox for GitHub Copilot CLI
- `navikt/tap/nav-pilot` — Nav Pilot AI-assistent

Setup kan også konfigurere cplt for Maven/Testcontainers, Docker Compose,
pnpm/Playwright og lokale utviklingstjenester. Maskinspesifikke tillatelser
legges i `~/.config/cplt/config.toml`, mens prosjektets `.cplt.toml` må
godkjennes med `cplt trust`. Les Linux-advarslene i
[`docs/onboarding.md`](docs/onboarding.md) før du godkjenner Docker eller
ubegrenset localhost.

```
make help
```

### Repo-administrasjon

| Kommando | Beskrivelse |
|----------|-------------|
| `make git-clone` | Klon alle repos fra `repos.yaml` til `./repos/` (krever `make setup` først) |
| `make git-fetch` | `git fetch` på alle repos |
| `make git-pull` | `git pull` på alle repos |
| `make git-default` | Switch til default branch + pull alle repos |
| `make git-update` | Vis status og spør om trygg checkout til default branch og `pull --ff-only` for parent og managed repos |
| `make git-status` | Vis branch, status, merget/PR-ikoner og parent POM-versjon for alle repos |
| `make git-prune-merged [DRY_RUN=1]` | Bytt til default branch og slett lokale merged branches som ikke er foran upstream (skipper dirty repos) |
| `make mvn-versions` | Vis Maven-versjoner (Java, Kotlin, parent POM…) på tvers |
| `make pnpm-versions` | Vis frontend-versjoner (Node, pnpm, Aksel) på tvers |
| `make gh-add-repo ORG=navikt REPO=ny-app` | Registrer nytt repo i `repos.yaml` |
| `make idea-sync-maven` | Synk `.idea/misc.xml` slik at IntelliJ ser alle Maven-repos i `repos/` som moduler (kjøres automatisk av `make git-clone`) |

> **IntelliJ:** Maven-modullisten i `.idea/misc.xml` synkes automatisk hver gang du kjører `make git-clone`. Kun `managed: true`-repos i `repos.yaml` med en `pom.xml` tas med. Åpne prosjektet i IntelliJ og trigg «Reload All Maven Projects» (Maven-panelet) om modulene ikke dukker opp automatisk.

### Masseoppdateringer

| Kommando | Beskrivelse |
|----------|-------------|
| `make git-multi-commit MSG="chore: ..."` | Commit staged endringer i alle repos med samme melding |
| `make git-push-all` | Push alle repos som er foran remote |
| `make pr-lag BRANCH=navn` | Lag PRer for alle repos på feature-branch |
| `make mvn-update-kotlin VERSION=2.x.y` | Bump `kotlin.version` i alle repos + lager PRer |
| `make pnpm-update-npmrc` | Synkroniser `.npmrc` til teamstandard + lager PRer |
| `make pnpm-install` | Kjør `pnpm install` i alle frontend-mapper på tvers av repos |

### PR-behandling

| Kommando | Beskrivelse |
|----------|-------------|
| `make pr` | Behandle PRer interaktivt — velg modus ved oppstart (alle, dependabot, mine, andres…) |
| `make pr-lag` | Lag PRer interaktivt — velg repos, tittel og body |
| `make pr-rerun` | Rerun feilede CI-sjekker på åpne PRer |

Valg per PR: `[a]` Godkjenn · `[b]` Godkjenn+auto-merge (Dependabot) · `[m]` Merge · `[u]` Update-branch · `[r]` Rerun CI · `[p]` Artifakter · `[v]` Åpne · `[s]` Skip · `[n]` Neste repo

Konfig i `config.json`: `diff_max_lines`, `merge_strategy`, `skip_repos`, `dependabot_skip_repos`, artifact-mønstre.

### Publisering

| Kommando | Beskrivelse |
|----------|-------------|
| `make mvn-release VERSION=1.0.0` | Publiser ny versjon av Maven parent POM |
| `make pnpm-release VERSION=1.0.0` | Publiser ny versjon av `@navikt/infotek-frontend-config` |

### Typisk arbeidsflyt for endringer på tvers

```bash
# 1. Sørg for kjent starttilstand
make git-update

# 2. Gjør endringen i berørte repos
# 3. Stage filene
git -C repos/mitt-repo add .github/dependabot.yml

# 4. Commit på tvers
make git-multi-commit MSG="chore: legg til dependabot.yml"

# 5. Push
make git-push-all

# 6. Lag PRer
make pr-lag
```

`make git-update` inkluderer parent-repoet og alle `managed: true`-repos. Den fetcher remote og viser lokale/utrackede endringer, divergens, lokale commits foran remote, detached HEAD eller manglende kloner med forslag til manuell håndtering. Den spør om brukeren vil bytte repoer til default branch og oppdatere med `pull --ff-only` når det er trygt. Den gjør aldri commit, push, merge, rebase eller overskriver lokale endringer, og er ikke en sperre for videre arbeid.

Før AI gjør endringer skal den sjekke status og spørre brukeren om `make git-update` skal kjøres. Brukeren kan avslå og fortsette med eksisterende branch- og repo-status.

## Struktur

```
infotek-parent/
├── repos.yaml              # kilde til sannhet — alle team-repos
├── Makefile                # alle kommandoer
├── config.json             # konfig for scripts (diff, merge-strategi, skip-repos)
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
│       ├── package.json    # @navikt/infotek-frontend-config
│       ├── tsconfig.base.json
│       └── biome.base.json
├── scripts/
│   ├── pr-behandle.py      # interaktiv PR-behandler på tvers av repos
│   ├── vis-artifakt.py     # last ned og vis CI-artifakter fra GitHub Actions
│   ├── gen-agents.py
│   ├── fmt-table.py
│   └── merge-npmrc.py
└── repos/                  # alle klonede team-repos (gitignored)
```

## Legg til et nytt repo

```bash
make gh-add-repo ORG=navikt REPO=min-app DESC="Beskrivelse av appen"
```

Dette oppdaterer `repos.yaml` og regenererer `ai/AGENTS.md` automatisk.

> **Merk:** Alle Makefile-targets (`git-fetch`, `git-pull`, `git-status`, `mvn-versions`, `git-clean-branches` osv.) kjøres kun på repos med `managed: true` i `repos.yaml`. Umanagede repos røres ikke.

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
| [infotrygd-replikering](https://github.com/navikt/infotrygd-replikering) | Grafana status for replikering av Infotrygd data | dev-fss, prod-fss | [dev-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/dev-fss/infotrygd-replikering) · [prod-fss](https://console.nav.cloud.nais.io/team/infotrygd/app/prod-fss/infotrygd-replikering) |
| [infotrygd-facade](https://github.com/navikt/infotrygd-facade) ⚠️ | — | — | — |

### 🟩 `historisk` — [Nais Console](https://console.nav.cloud.nais.io/team/historisk)

| Repo | Beskrivelse | Miljøer | Nais |
|------|-------------|---------|------|
| [historisk-avstandskalkulator](https://github.com/navikt/historisk-avstandskalkulator) | historisk-avstandskalkulator | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-avstandskalkulator) |
| [historisk-gravferdkalkulator](https://github.com/navikt/historisk-gravferdkalkulator) | Kalkulator for å regne ut stønad til gravferdsstønad og båretransport | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-gravferdkalkulator) |
| [historisk-exodus](https://github.com/navikt/historisk-exodus) | — | dev-fss, prod-fss | [dev-fss](https://console.nav.cloud.nais.io/team/historisk/app/dev-fss/historisk-exodus) · [prod-fss](https://console.nav.cloud.nais.io/team/historisk/app/prod-fss/historisk-exodus) |
| [historisk-pensjon](https://github.com/navikt/historisk-pensjon) | Oppslag på historiske pensjonsdata fra Infotrygd | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-pensjon) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-pensjon) |
| [historisk-regnskap](https://github.com/navikt/historisk-regnskap) | Oppslag på historiske regnskapsdata fra Infotrygd | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-regnskap) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-regnskap) |
| [historisk-tidsbegrenset-uforestonad](https://github.com/navikt/historisk-tidsbegrenset-uforestonad) | Oppslag på historiske data fra Infotrygd for tidsbegrenset uførestønad, rehabiliteringspenger, attføring | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-tidsbegrenset-uforestonad) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-tidsbegrenset-uforestonad) |
| [historisk-riddler](https://github.com/navikt/historisk-riddler) | historisk-riddler: Beregninger av gamle infotrygdytelser | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-riddler) |
| [historisk-valutakalkulator](https://github.com/navikt/historisk-valutakalkulator) | Valutakalkulator som viser historiske vekslingskurser. | dev-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-valutakalkulator) |
| [historisk-avgiftssystem](https://github.com/navikt/historisk-avgiftssystem) ⚠️ | — | dev-gcp, prod-gcp | [dev-gcp](https://console.nav.cloud.nais.io/team/historisk/app/dev-gcp/historisk-avgiftssystem) · [prod-gcp](https://console.nav.cloud.nais.io/team/historisk/app/prod-gcp/historisk-avgiftssystem) |

<!-- AUTO-GENERATED:README-REPOS END -->
