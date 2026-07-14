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

## 5. AI-verktøy

Kopier AI-konfig til dine repos:

```bash
cp ai/AGENTS.md ../mitt-repo/AGENTS.md
cp -r ai/.github ../mitt-repo/.github
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
