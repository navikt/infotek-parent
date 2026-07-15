# GitHub Copilot-instruksjoner for infotek-teamet

## Dette repoet — infotek-parent

`infotek-parent` er teamets umbrella-repo. Det inneholder ikke appkode, men verktøy og felles konfig for alle team-repos.

### Viktige filer

| Fil/mappe | Formål |
|-----------|--------|
| `repos.yaml` | Kilde til sannhet — alle teamets repos med org, namespace, default_branch |
| `Makefile` | Alle kommandoer for å jobbe på tvers av repos |
| `repos/` | Klonede repos (gitignored) — klones hit av `make clone` |
| `platform/maven/pom.xml` | Maven parent POM — publisert til GitHub Packages |
| `platform/pnpm/catalog.json` | Godkjente frontend-versjoner |
| `platform/pnpm/tsconfig.base.json` | Felles TypeScript-konfig |
| `platform/pnpm/biome.base.json` | Felles Biome-konfig |
| `platform/npm/.npmrc` | Teamstandard for npm/pnpm |
| `scripts/` | Python-scripts for masseoppdateringer |
| `ai/AGENTS.md` | Auto-generert repo-oversikt (ikke rediger manuelt) |

### Makefile-kommandoer

```bash
make clone              # klon alle repos til repos/
make status             # branch + status for alle repos
make versions           # nøkkelversjoner på tvers
make fetch / pull / default

make multi-commit MSG="chore: ..."   # commit på tvers (blokkerer på default-branch)
make push-all                        # push alle feature-branches
make pr-all                          # interaktiv PR-oppretter

make update-kotlin VERSION=2.x.y    # bump kotlin i alle repos + PR
make update-npmrc                    # sync .npmrc til teamstandard + PR
make release-parent VERSION=4.x.x   # publiser Maven parent POM
make release-frontend-config VERSION=1.x.x
make setup                           # ny maskin — installer alle verktøy
```

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
