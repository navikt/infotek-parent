# infotek-parent

Infotek-teamets felles plattform-repo. Her finner du verktøy for å jobbe med alle teamets repos, felles dokumentasjon og AI-konfigurasjon.

## Kom i gang (ny maskin / ny utvikler)

```bash
git clone git@github.com:navikt/infotek-parent.git
cd infotek-parent
make setup      # installer verktøy (brew, java, gh-cli, nais-cli)
make clone      # klon alle team-repos til ./repos/
```

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
| `make update-frontend-deps` | Bump frontend-avhengigheter fra `platform/pnpm/catalog.json` + lager PRer |

### Publisering

| Kommando | Beskrivelse |
|----------|-------------|
| `make release-parent VERSION=4.1.1` | Publiser ny versjon av Maven parent POM |
| `make release-frontend-config VERSION=1.1.0` | Publiser ny versjon av `@navikt/infotek-frontend-config` |

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
│       ├── package.json    # @navikt/infotek-frontend-config
│       ├── tsconfig.base.json
│       ├── biome.base.json
│       └── catalog.json    # godkjente frontend-versjoner
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
