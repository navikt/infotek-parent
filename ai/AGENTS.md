# AGENTS.md — Infotek

Dette er felles AI-instruksjoner for infotek-teamet. Brukes av GitHub Copilot, Claude og andre AI-verktøy.

## Om teamet

Infotek-teamet jobber med historiske pensjonsdata og ytelser. Teamet har repos fordelt på flere GitHub-orger:
`navikt`, `historisk`, `infotryg` og `infotek`.

## Konvensjoner

- **Språk:** Norsk i commit-meldinger, kommentarer og dokumentasjon
- **Branching:** `main` er default branch. Feature-branches: `feat/<beskrivelse>`, bugfix: `fix/<beskrivelse>`
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`)
- **PR-er:** Minst én godkjenning før merge. Squash merge til main.
- **Java-versjon:** Se parent POM i `platform/maven/parent-pom.xml`
- **Avhengigheter:** Bruk versjoner definert i parent POM — ikke overstyr uten begrunnelse

## Stack

- **Backend:** Kotlin + Spring Boot (noen Ktor)
- **Bygg:** Maven med felles parent POM
- **Plattform:** Nais (GCP)
- **Auth:** TokenX (brukerkontekst), Azure AD (maskin-til-maskin)
- **Database:** PostgreSQL med Flyway-migrasjoner

## Viktige mønstre

- Ikke logg PII (fødselsnummer, navn, adresse) — bruk sakId/behandlingId i logger
- Bruk `HikariCP` med `maximumPoolSize=3` i Nais-miljø
- Aldri sett CPU-limits i Nais — bruk kun requests
- Alle nye endepunkter skal ha `accessPolicy.inbound` i nais.yaml

---

<!-- AUTO-GENERATED:REPOS START -->

## Teamets repos

| Repo | Org | Namespace | Miljøer | Forvaltet |
|------|-----|-----------|---------|-----------|
| [infotek-databaseuttrekk](https://github.com/navikt/infotek-databaseuttrekk) | `navikt` | `infotek` | dev-gcp | ✅ |
| [infotek-statistikk](https://github.com/navikt/infotek-statistikk) | `navikt` | `infotek` | dev-gcp | ✅ |
| [infotrygd-brukeroppslag](https://github.com/navikt/infotrygd-brukeroppslag) | `navikt` | `infotrygd` | dev-fss, prod-fss, dev-gcp, prod-gcp | ✅ |
| [infotrygd-feed-proxy-v2](https://github.com/navikt/infotrygd-feed-proxy-v2) | `navikt` | `infotrygd` | dev-fss, prod-fss | ✅ |
| [infotrygd-hentsaksliste](https://github.com/navikt/infotrygd-hentsaksliste) | `navikt` | `infotrygd` | dev-fss, prod-fss | ✅ |
| [infotrygd-replikering](https://github.com/navikt/infotrygd-replikering) | `navikt` | `infotrygd` | dev-fss, prod-fss | ✅ |
| [infotrygd-facade](https://github.com/navikt/infotrygd-facade) | `navikt` | `infotrygd` | — | ✅ |
| [historisk-avstandskalkulator](https://github.com/navikt/historisk-avstandskalkulator) | `navikt` | `historisk` | dev-gcp | ✅ |
| [historisk-gravferdkalkulator](https://github.com/navikt/historisk-gravferdkalkulator) | `navikt` | `historisk` | dev-gcp | ✅ |
| [historisk-exodus](https://github.com/navikt/historisk-exodus) | `navikt` | `historisk` | dev-fss, prod-fss | ✅ |
| [historisk-pensjon](https://github.com/navikt/historisk-pensjon) | `navikt` | `historisk` | dev-gcp, prod-gcp | ✅ |
| [historisk-regnskap](https://github.com/navikt/historisk-regnskap) | `navikt` | `historisk` | dev-gcp, prod-gcp | ✅ |
| [historisk-tidsbegrenset-uforestonad](https://github.com/navikt/historisk-tidsbegrenset-uforestonad) | `navikt` | `historisk` | dev-gcp, prod-gcp | ✅ |
| [historisk-riddler](https://github.com/navikt/historisk-riddler) | `navikt` | `historisk` | dev-gcp | ✅ |
| [historisk-valutakalkulator](https://github.com/navikt/historisk-valutakalkulator) | `navikt` | `historisk` | dev-gcp | ✅ |
| [historisk-avgiftssystem](https://github.com/navikt/historisk-avgiftssystem) | `navikt` | `historisk` | dev-gcp, prod-gcp | ❌ |

<!-- AUTO-GENERATED:REPOS END -->
