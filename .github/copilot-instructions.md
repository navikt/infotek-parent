# GitHub Copilot-instruksjoner for infotek-teamet

## Dette repoet — infotek-parent

`infotek-parent` er teamets umbrella-repo. Det inneholder ikke appkode, men verktøy og felles konfig for alle team-repos.

### Viktige filer

| Fil/mappe | Formål |
|-----------|--------|
| `repos.yaml` | Kilde til sannhet — alle teamets repos med org, namespace, default_branch |
| `Makefile` | Alle kommandoer for å jobbe på tvers av repos |
| `config.json` | Konfig for scripts (diff-grenser, merge-strategi, skip-repos, artifact-mønstre) |
| `repos/` | Klonede repos (gitignored) — klones hit av `make git-clone` |
| `platform/maven/pom.xml` | Maven parent POM — publisert til GitHub Packages |
| `platform/pnpm/package.json` | `@navikt/infotek-frontend-config` — eksporterer felles tsconfig og biome-konfig |
| `platform/pnpm/tsconfig.base.json` | Felles TypeScript-konfig |
| `platform/pnpm/biome.base.json` | Felles Biome-konfig |
| `platform/npm/.npmrc` | Teamstandard for npm/pnpm |
| `scripts/` | Python-scripts for masseoppdateringer og PR-behandling |
| `scripts/pr-behandle.py` | Interaktiv PR-behandler — behandler PRer på tvers av repos |
| `scripts/vis-artifakt.py` | Last ned og vis CI-artifakter (logg, playwright-rapport) fra GitHub Actions |
| `ai/AGENTS.md` | Auto-generert repo-oversikt (ikke rediger manuelt) |

### Makefile-kommandoer

```bash
make git-clone              # klon alle repos til repos/
make git-status             # branch + status for alle repos
make mvn-versions           # maven-versjoner på tvers
make pnpm-versions          # frontend-versjoner på tvers
make git-fetch / git-pull / git-default

make git-multi-commit MSG="chore: ..."   # commit på tvers (blokkerer på default-branch)
make git-push-all                        # push alle feature-branches
make pr-lag                              # interaktiv PR-oppretter

make pr                                  # behandle åpne PRer interaktivt (ekskl. Dependabot)
make pr-dependabot                       # behandle Dependabot-PRer interaktivt
make pr-alle                             # behandle alle PRer inkl. Dependabot
make pr-help                             # vis arbeidsflyt og valg per PR

make mvn-update-kotlin VERSION=2.x.y    # bump kotlin i alle repos + PR
make pnpm-update-npmrc                   # sync .npmrc til teamstandard + PR
make mvn-release VERSION=4.x.x          # publiser Maven parent POM
make pnpm-release VERSION=1.x.x         # publiser frontend-config
make setup                               # ny maskin — installer alle verktøy
```

### Kun managed repos i Makefile-scripts

Alle Makefile-targets og scripts som itererer over repos **skal kun gjelde managed repos**. Bruk alltid `select(.managed == true)` i yq-spørringer:

```makefile
yq e '.repos[] | select(.managed == true) | .name + " " + .default_branch' $(REPOS_FILE)
```

Aldri bruk `.repos[]` uten `select(.managed == true)` i targets som gjør endringer eller sjekker branches. Umanagede repos skal ikke røres.

### Bruk Makefile først ved masseoperasjoner

Når vi gjør samme operasjon i mange repoer, skal Copilot foreslå Makefile-kommandoer før manuelle git-steg per repo.

- Commit i mange repoer: `make git-multi-commit MSG="chore: ..."`
- Stage i mange repoer: `make git-stage-all`
- Push i mange repoer: `make git-push-all`
- Opprett PR-er i mange repoer: `make pr-lag`
- Synk `.npmrc` i mange repoer: `make pnpm-update-npmrc`

Bruk manuelle `git add/commit/push/gh pr create` når endringen gjelder ett repo, eller når du trenger kontroll per repo.

### Protected branches — viktig

Alle repos har beskyttet `main`/`master`. **Aldri commit direkte til default-branch.**

### Copilot gjør IKKE commits eller push

**Copilot lager aldri git-commits eller kjører `git push`.**
Etter at Copilot har gjort filendringer, presenter commit-meldingen og la utvikleren kjøre:

```bash
git add -A
git commit -m "<melding>"
git push -u origin <branch>
gh pr create --title "<tittel>" --body "<beskrivelse>"
```

Riktig arbeidsflyt (utvikler kjører selv):
```bash
git checkout -b chore/min-endring
# Copilot gjør filendringer
git add -A
git commit -m "chore: beskrivelse"
git push -u origin chore/min-endring
gh pr create
```

Hvis du ved en feil har commitet til default-branch:
```bash
git checkout -b chore/min-endring
git checkout main
git reset --hard HEAD~1
```

## Om teamet og kodebasen

Infotek-teamet forvalter historiske pensjonsdata og ytelser i Nav.
Repos er fordelt på org `navikt` med namespace `infotek`, `infotrygd` og `historisk` i Nais.

Se `ai/AGENTS.md` for fullstendig repo-oversikt.

## Stack

- **Backend:** Kotlin + Spring Boot (noen Ktor), Maven
- **Frontend:** React/Vite, pnpm, TypeScript, Biome
- **Plattform:** Nais (GCP og FSS)
- **Auth:** TokenX (brukerkontekst), Azure AD (maskin-til-maskin)
- **Database:** PostgreSQL med Flyway

## Viktige regler

- Ikke logg PII (fødselsnummer, navn, adresse) — bruk sakId/behandlingId
- `HikariCP`: bruk `maximumPoolSize=3` i Nais-miljø
- Aldri sett CPU-limits i nais.yaml — bruk kun requests
- Alle endepunkter skal ha `accessPolicy.inbound` i nais.yaml
- Bruk versjoner fra parent POM (`navikt/infotek-parent`) — ikke overstyr uten begrunnelse
- Default-branches er beskyttet — alltid bruk feature-branch

## Kodestil

- Norsk i commit-meldinger og dokumentasjon
- Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`
- Kotlin: idiomatisk stil, bruk `data class`, `sealed class`, extension functions
