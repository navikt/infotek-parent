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

Dette installerer: Homebrew, `yq`, `git`, `gh` (GitHub CLI), `nais-cli`, og Java (Temurin).

> **Merk:** Første gang kjøres `gh auth login` interaktivt — følg instruksjonene.

## 3. Klon alle team-repos

```bash
make clone
```

Alle repos klones til samme nivå som `team-platform/`, dvs. `../`:

```
~/dev/
├── team-platform/   ← dette repoet
├── historisk-pensjon/
├── infotrygd-feed/
└── ...
```

## 4. Verifiser oppsett

```bash
make status
```

Du skal se alle repos med branch `main` og status `✅ ren`.

## 5. Autentisering mot GitHub Packages

Teamet bruker GitHub Packages for både Maven (Java/Kotlin) og npm (frontend).

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

> `ignore-scripts` og `min-release-age` bør ligge globalt i `~/.npmrc` — da gjelder de uansett hvilket prosjekt du jobber i, ikke bare infotek-repos.  
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

## Nyttige kommandoer

| Kommando | Beskrivelse |
|---|---|
| `make help` | Vis alle kommandoer |
| `make fetch` | Fetch fra alle repos |
| `make pull` | Pull på alle repos |
| `make main` | Switch til main + pull alle |
| `make status` | Oversikt over alle repos |
| `make add-repo ORG=navikt REPO=navn DESC="..."` | Legg til nytt repo |

## Tilgang og systemer

- [ ] GitHub-tilgang: be teamlead om tilgang til `navikt`, `historisk`, `infotryg`, `infotek`
- [ ] Nais: [https://console.nav.cloud.nais.io](https://console.nav.cloud.nais.io)
- [ ] GCP: tilgang tildeles via Nais Console
- [ ] Slack: `#infotek` (intern), `#nais` (plattform)

## Kontakter

- **Teamlead:** _fyll inn_
- **Plattformkontakt:** _fyll inn_
