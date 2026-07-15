# Onboarding — Infotek

Velkommen til infotek-teamet! Følg disse stegene for å komme i gang.

## 1. Klon platform-repoet

```bash
git clone git@github.com:navikt/infotek-parent.git infotek
cd infotek
```

## 2. Sett opp maskinen

```bash
make setup
```

Dette installerer: Homebrew, `yq`, `git`, `gh` (GitHub CLI), `nais-cli`, Java (Temurin), `cplt` og `nav-pilot`.

> **Merk:** Første gang kjøres `gh auth login` interaktivt — følg instruksjonene.

## 3. Klon alle team-repos

```bash
make clone
```

Alle repos klones til `repos/` under dette repoet:

```
infotek/
├── repos/           ← alle klonede repos (gitignored)
│   ├── historisk-pensjon/
│   ├── infotrygd-feed-proxy-v2/
│   └── ...
├── Makefile
└── repos.yaml
```

## 4. Verifiser oppsett

```bash
make status
```

Du skal se alle repos med riktig branch og status `✅ ren`.

## 5. Autentisering mot GitHub Packages

Teamet bruker GitHub Packages for Maven (Java/Kotlin) og npm (frontend).

### Maven — `~/.m2/settings.xml`

```xml
<settings>
  <servers>
    <server>
      <id>github</id>
      <username>DITT_GITHUB_BRUKERNAVN</username>
      <password>DITT_PAT</password>
    </server>
  </servers>
</settings>
```

### npm/pnpm — `~/.npmrc`

```
//npm.pkg.github.com/:_authToken=DITT_PAT
@navikt:registry=https://npm.pkg.github.com
ignore-scripts=true
min-release-age=7d
engine-strict=true
```

> `ignore-scripts` og `min-release-age` bør ligge globalt i `~/.npmrc` — da gjelder de for alle prosjekter, ikke bare infotek.  
> `make setup` legger dette til automatisk.

> **PAT-krav:** `read:packages` (og `write:packages` om du skal publisere).  
> Opprett på: GitHub → Settings → Developer settings → Personal access tokens.  
> Eller kjør `nais login` som oppdaterer credentials automatisk.

## 6. AI-verktøy

Kopier AI-konfig til dine repos:

```bash
cp ai/AGENTS.md ../mitt-repo/AGENTS.md
cp -r .github/copilot-instructions.md ../mitt-repo/.github/
```

## Masseoppdateringer på tvers av repos

> ⚠️ **Default-branches er beskyttet.** Du kan ikke pushe direkte til `main` eller `master`.  
> Alltid lag en ny branch før du committer endringer som skal gå via PR.

```bash
# 1. Lag branch i alle berørte repos
git -C repos/mitt-repo checkout -b chore/min-endring

# 2. Gjør endringer, stage filene
git -C repos/mitt-repo add .github/dependabot.yml

# 3. Commit på tvers
make multi-commit MSG="chore: beskrivelse"   # stopper med feil hvis du er på default-branch

# 4. Push
make push-all

# 5. Lag PRer interaktivt
make pr-all
```

## Nyttige kommandoer

| Kommando | Beskrivelse |
|---|---|
| `make help` | Vis alle kommandoer |
| `make fetch` | Fetch fra alle repos |
| `make pull` | Pull på alle repos |
| `make main` | Switch til main/master + pull alle |
| `make status` | Oversikt over alle repos |
| `make versions` | Nøkkelversjoner på tvers |
| `make add-repo ORG=navikt REPO=navn` | Legg til nytt repo |

## Tilgang og systemer

- [ ] GitHub-tilgang: be teamlead om tilgang til `navikt`, `historisk`, `infotryg`, `infotek`
- [ ] Nais: [https://console.nav.cloud.nais.io](https://console.nav.cloud.nais.io)
- [ ] GCP: tilgang tildeles via Nais Console
- [ ] Slack: `#infotek` (intern), `#nais` (plattform)

## Kontakter

- **Teamlead:** _fyll inn_
- **Plattformkontakt:** _fyll inn_
