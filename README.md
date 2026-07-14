# infotek-parent

Infotek-teamets felles plattform-repo. Her finner du verktøy for å jobbe med alle teamets repos, felles dokumentasjon og AI-konfigurasjon.

## Kom i gang (ny maskin / ny utvikler)

```bash
git clone git@github.com:navikt/infotek-parent.git
cd infotek-parent
make setup      # installer verktøy (brew, java, gh-cli, nais-cli)
make clone      # klon alle team-repos til ./
```

## Vanlige kommandoer

```bash
make help                                       # vis alle kommandoer
make status                                     # branch/status for alle repos
make fetch                                      # fetch på alle repos
make pull                                       # pull på alle repos
make main                                       # switch til main + pull alle
make add-repo ORG=navikt REPO=ny-app DESC="..."  # registrer nytt repo
```

## Struktur

```
team-platform/
├── repos.yaml          # kilde til sannhet — alle team-repos
├── Makefile            # alle kommandoer
├── ai/
│   ├── AGENTS.md       # AI-oversikt over teamets repos og konvensjoner
│   └── .github/        # Copilot-instruksjoner
├── docs/
│   ├── onboarding.md   # steg-for-steg guide for ny utvikler
│   ├── conventions.md  # kodestandarder og konvensjoner
│   ├── adr/            # architecture decision records
│   └── runbooks/       # driftsrutiner
└── platform/maven/
    └── parent-pom.xml  # felles Maven BOM og plugin-konfig
```

## Legg til et nytt repo

```bash
make add-repo ORG=navikt REPO=min-app DESC="Beskrivelse av appen"
```

Dette oppdaterer `repos.yaml` og regenererer `ai/AGENTS.md` automatisk.
