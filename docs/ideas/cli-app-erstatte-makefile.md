# Plan: Erstatte Makefile med interaktiv CLI-app

## Problemstilling

Dagens verktøy i `infotek-parent` er bygget på:
- **Makefile** (604 linjer) — bash-tung, vanskelig å vedlikeholde, ingen interaktivitet
- **Python-scripts** (~2 500 linjer, 14 filer) — allerede brukt for kompleks logikk
- **Avhengigheter**: `yq`, `gh`, `mvn`, `pnpm`, `git` — alt shell-callouts

Spørsmålet: bør vi erstatte dette med en skikkelig CLI-app? Og hva skal den i så fall skrives i?

---

## Nåsituasjon — hva gjør Makefile/scripts egentlig?

| Gruppe | Targets | Kompleksitet |
|--------|---------|--------------|
| git-operasjoner | clone, fetch, pull, status, clean-branches, stage-all, multi-commit, push-all, merge-main | Medium — bash-loops over repos.yaml |
| gh-administrasjon | add-repo, detach-repo, apply-ruleset, pr-all, pr-status | Høy — Python, GitHub API |
| Maven | versions, update-kotlin, release | Medium — XML-parsing, git/gh |
| pnpm / frontend | versions, install, biome-check, update-npmrc, migrate-config, release | Høy — Python, filmanipulering |
| Dokumentasjon | docs (AGENTS.md), update-readme | Medium — Python, GitHub API |
| Oppsett | setup | Lav — brew install |

Allerede delvis migrert til Python der det trengs interaktivitet (pr-all.py, pr-status.py m.fl.).

---

## Språkvalg — analyse

### Kotlin (teamets primærspråk)

**Fordeler:**
- Teamet kan det — lav inngangsbarriere, lettere å vedlikeholde
- Rik CLI-støtte: `kotlinx-cli`, `mordant` (farger/tabeller), `clikt` (populær CLI-DSL)
- TUI-interaktivitet: `mordant`, `Inquirer.kt`
- Kan kalle shell-kommandoer enkelt

**Ulemper:**
- **JVM-oppstartstid: 200–500 ms** — merkbar for hyppige CLI-kall
- Løsning: **GraalVM Native Image** → native binary, ~10 ms oppstart, men komplisert build-setup
- Native Image + Kotlin: fungerer godt per 2025, men krever litt konfigurasjon

### Rust

**Fordeler:**
- **Oppstartstid: <5 ms** — raskest mulig
- Utmerket CLI-økosystem: `clap` (arg-parsing), `ratatui` (TUI), `dialoguer` (interaktive prompts), `indicatif` (progress bars)
- Enkelt å distribuere: én statisk binary, ingen runtime-avhengigheter
- `ratatui` er nå veldig modent — fullverdig terminal UI

**Ulemper:**
- Teamet kan ikke Rust — **signifikant læringskurve**
- Eierskap/borrow checker er en annen tankemodell
- Komplisert kode tar tid å skrive riktig

### C

**Ulemper:**
- Raskest mulig, men **feil verktøy for oppgaven** — manuell minnehåndtering, ingen standardbibliotek for HTTP/YAML/JSON
- Vil ta 10× lengre tid å skrive enn Rust for samme funksjonalitet
- **Anbefales ikke.**

### Python (status quo — forbedret)

**Fordeler:**
- Allerede i bruk for komplekse deler
- `typer` + `rich` gir flott interaktiv CLI med lite kode
- Lavest friksjon: kan bygge på eksisterende scripts

**Ulemper:**
- Oppstartstid ~100 ms, men ikke et reelt problem for dette use-caset
- Ikke teamets foretrukne språk langsiktig

---

## Anbefaling

### Kortsiktig (nå → 6 mnd): Forbedre Python-scripts + thin Makefile

Makefile fungerer som **entry-point/discovery** (`make help`), men Python gjør jobben.
- Flytt all logikk ut av Makefile-bash og inn i Python
- Bruk `typer` + `rich` for bedre interaktivitet og feilmeldinger
- Legg til `fzf`-lignende prompter med `InquirerPy` der det gir verdi
- Minimalt arbeid, stor gevinst

### Langsiktig alternativ A: Kotlin + GraalVM Native Image

```
infotek-cli/
  src/main/kotlin/
    commands/
      GitCommands.kt    # git-clone, git-status, etc.
      GhCommands.kt     # pr-all, pr-status, etc.
      MvnCommands.kt
      PnpmCommands.kt
    model/
      ReposConfig.kt    # repos.yaml deserialisering
    ui/
      Table.kt          # mordant tabeller
      Prompts.kt        # interaktive prompts
  build.gradle.kts      # GraalVM native image plugin
```

**Stack:**
- `clikt` — CLI-DSL (arg-parsing, subcommands, autocomplete)
- `mordant` — farger, tabeller, progress bars
- `kaml` — YAML-parsing for repos.yaml
- `ktor-client` — GitHub API-kall (erstatter `gh`-CLI-callouts)
- GraalVM Native Image — native binary via `./gradlew nativeCompile`

**Distribusjon:** GitHub Releases, `brew install` via custom tap, eller bare `make setup` som laster ned binary.

### Langsiktig alternativ B: Rust

**Stack:**
- `clap` — arg-parsing med autocomplete
- `ratatui` + `crossterm` — fullverdig terminal UI (dashboard-visning av status)
- `dialoguer` — interaktive prompts
- `serde` + `serde_yaml` — repos.yaml
- `octocrab` — GitHub API
- `tokio` — async for parallelle git-operasjoner

**Særlig egnet for:** interaktive dashboards (git-status over mange repos som oppdaterer seg i sanntid), parallelle operasjoner med progress bars.

---

## Interaktivitetsmuligheter

Uavhengig av språk — hva kan gjøres bedre interaktivt?

| Feature | Verdi | Teknologi |
|---------|-------|-----------|
| Fuzzy-søk i repos ved pr-all | Høy | fzf / dialoguer / InquirerPy |
| Live git-status dashboard (oppdateres mens fetch kjører) | Høy | ratatui / blessed |
| Autocomplete for make-targets | Medium | clikt / clap |
| Interaktiv konflikthåndtering ved merge-main | Medium | prompt |
| Farget diff-visning ved version-bump | Lav | mordant / rich |

---

## Beslutningstrinn

```
Vil vi gjøre dette?
├─ Nei → behold Makefile + Python, lev godt
├─ Ja, lite investering → forbedre Python (typer + rich)
├─ Ja, teamet vil lære Kotlin tooling → Kotlin + GraalVM
└─ Ja, vi vil ha det raskeste og beste TUI → Rust (invester i læring)
```

---

## AI-assistert utvikling (Copilot / coding agent)

Et viktig argument **for Rust** i en agentisk workflow:

**Rust-kompilatoren er en gratis fasit for AI-agenter.**

| Språk | Feil oppdages | AI-feedback-loop |
|---|---|---|
| **Rust + clap** | Kompileringstid | `cargo check` (~1–2s) gir presis feil + forslag. AI ser hva som er galt uten å kjøre koden. |
| **Kotlin + clikt** | Kompileringstid | Kompilerer også, men JVM-feil kan være verbose og GraalVM-konfig er støyende. |
| **Python + typer** | Kjøretid | Feil krever faktisk kjøring av koden — AI må ha testcases for å se feilen. |

**Konklusjon:** For agentisk utvikling er Rust faktisk *bedre* enn Python, ikke verre. Kompilatoren gir deterministisk, presis tilbakemelding som AI kan resonnere direkte på. `cargo check` er rask nok til at iterasjonsloopen er tight.

For en enkel CLI (uten TUI) er Rust + `clap` + `serde_yaml` relativt rett frem — ingen komplekse lifetimes, og `clap` v4 med derive-makroer er veldokumentert med mye treningsdata.

---

## Vurderingskriterier for fremtidig beslutning

- [ ] Makefile-frustrasjoner dokumentert (hva er faktisk smertepunktene?)
- [ ] Brukes `make`-kommandoene hyppig nok til at oppstartstid betyr noe?
- [ ] Er teamet interessert i å lære Rust?
- [ ] Er det ønskelig med et TUI-dashboard for git-status?
- [ ] Vil vi ha CLI-distribusjon via brew/binary, eller er `make` fint nok?

---

## Konklusjon

**Anbefalt sti:**
1. **Nå**: Ingenting (Makefile + Python fungerer)
2. **Neste forbedring**: Migrer resterende bash i Makefile til Python med `typer` + `rich` — mest verdi for minst innsats
3. **Ambisiøst**: Kotlin + GraalVM Native Image — teamets språk, native hastighet, rik TUI-støtte
4. **Drøm**: Rust med `ratatui` — men krever at teamet investerer tid i å lære Rust

**C er ikke aktuelt** — for mye arbeid, for lite gevinst over Rust.
