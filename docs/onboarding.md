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

Dette installerer: Homebrew, `yq`, `git`, `gh` (GitHub CLI), Maven, pnpm,
`nais-cli`, Java (Temurin), GitHub Copilot CLI, `cplt` og `nav-pilot`.

> **Merk:** Første gang kjøres `gh auth login` interaktivt — følg instruksjonene.

Setup spør også om cplt skal konfigureres for Maven, pnpm og Playwright.
Steget gir lesetilgang til `~/.m2/settings.xml` og `~/.npmrc`, tillater
kjøring fra Playwright- og pnpm-dlx-cachene, og installerer shell-integrasjonen
slik at `copilot` kjører gjennom cplt. Scriptet viser også forslagene i
`.cplt.toml` og spør separat før hver tillatelse godkjennes. Det bruker aldri
`cplt trust accept --all`. Kjør steget senere med:

```bash
python3 scripts/setup-cplt.py
```

Prosjektets `.cplt.toml` foreslår Docker, JVM attach og tilgang til lokale
porter for Testcontainers, Docker Compose og utviklingstjenester. Den
interaktive trust-gjennomgangen er del av setup-scriptet. Tillatelser kan også
godkjennes manuelt:

```bash
cplt trust
cplt trust accept allow_docker
cplt trust accept allow_jvm_attach
cplt trust accept allow_localhost_any
```

> **Linux og Docker:** `allow_docker` gir agenten tilgang til Docker- eller
> Podman-daemonen. På en vanlig Linux-maskin er dette i praksis root-tilgang
> til verten: agenten kan starte en privilegert container eller montere
> vertens filsystem og lese eller endre filer utenfor cplt-sandboxen. Dette
> gjelder selv om kommandoen ikke bruker `sudo`. Godkjenn bare tillatelsen på
> en maskin der du aksepterer denne risikoen. Bruk rootless Docker/Podman,
> en dedikert VM eller container dersom verten ikke skal eksponeres.
>
> Installer og bruk Bubblewrap på Linux. På kjerner før 7.1 er maskering via
> Bubblewrap den sentrale beskyttelsen mot container-daemonens Unix-socket når
> `allow_docker` ikke er godkjent. Kjør `cplt doctor` og rett advarsler før du
> starter agenten.
>
> **Linux og localhost:** `allow_localhost_any` kan ikke begrenses til
> localhost av Landlock. cplt deaktiverer derfor TCP connect-filtreringen på
> Linux når denne tillatelsen er aktiv. Den er nødvendig for enkelte
> dynamiske test- og byggeverktøy, men åpner også direkte TCP-forbindelser til
> eksterne verter. Foretrekk konkrete `allow.localhost`-porter når
> arbeidsflyten tillater det.
>
> Rotens `.cplt.toml` brukes når cplt startes fra `infotek-parent`. Den arves
> ikke automatisk når cplt startes direkte inne i et repo under `repos/`.

> **Utklippstavle (macOS):** cplt blokkerer utklippstavlen som standard, så
> `pbcopy`/`pbpaste` feiler inne i en agent-økt. Dette er en bevisst
> sikkerhetsdefault — en agent med tilgang kan lese alt du nylig har kopiert
> (passord, tokens) og skrive vilkårlig innhold til utklippstavlen din. Godkjenn
> derfor bare på egen maskin, aldri i `infotek-parent`s felles `.cplt.toml`.
> Legg dette i din personlige `~/.config/cplt/config.toml`
> (opprett filen med `cplt --init-config` om den ikke finnes):
>
> ```toml
> [sandbox]
> deny_clipboard = false
> ```

## 3. Klon alle team-repos

```bash
make git-clone
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
make git-status
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
make git-multi-commit MSG="chore: beskrivelse"   # stopper med feil hvis du er på default-branch

# 4. Push
make git-push-all

# 5. Lag PRer interaktivt
make gh-pr-all
```

## Nyttige kommandoer

| Kommando | Beskrivelse |
|---|---|
| `make help` | Vis alle kommandoer |
| `make git-fetch` | Fetch fra alle repos |
| `make git-pull` | Pull på alle repos |
| `make git-default` | Switch til main/master + pull alle |
| `make git-status` | Oversikt over alle repos med branch-, merget- og PR-status |
| `make git-prune-merged DRY_RUN=1` | Preview: bytt til default branch og slett lokale merged branches som ikke er foran upstream |
| `make mvn-versions` | Maven-versjoner på tvers |
| `make pnpm-versions` | Frontend-versjoner på tvers |
| `make gh-add-repo ORG=navikt REPO=navn` | Legg til nytt repo |

## Tilgang og systemer

- [ ] GitHub-tilgang: be teamlead om tilgang til `navikt`, `historisk`, `infotryg`, `infotek`
- [ ] Nais: [https://console.nav.cloud.nais.io](https://console.nav.cloud.nais.io)
- [ ] GCP: tilgang tildeles via Nais Console
- [ ] Slack: `#infotek` (intern), `#nais` (plattform)

## Kontakter

- **Teamlead:** _fyll inn_
- **Plattformkontakt:** _fyll inn_
