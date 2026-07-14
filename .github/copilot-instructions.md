# GitHub Copilot-instruksjoner for infotek-teamet

## Om teamet og kodebasen

Infotek-teamet forvalter historiske pensjonsdata og ytelser i Nav.
Repos er fordelt på org `navikt` med namespace `infotek`, `infotrygd` og `historisk` i Nais.

Se `ai/AGENTS.md` for fullstendig repo-oversikt og teamkonvensjoner.

## Stack

- **Backend:** Kotlin + Spring Boot (noen Ktor), Maven
- **Frontend:** React / Next.js
- **Plattform:** Nais (GCP og FSS)
- **Auth:** TokenX (brukerkontekst), Azure AD (maskin-til-maskin)
- **Database:** PostgreSQL med Flyway

## Viktige regler

- Ikke logg PII (fødselsnummer, navn, adresse) — bruk sakId/behandlingId
- `HikariCP`: bruk `maximumPoolSize=3` i Nais-miljø
- Aldri sett CPU-limits i nais.yaml — bruk kun requests
- Alle endepunkter skal ha `accessPolicy.inbound` i nais.yaml
- Bruk versjoner fra parent POM (`navikt/infotek-parent`) — ikke overstyr uten begrunnelse

## Kodestil

- Norsk i commit-meldinger og dokumentasjon
- Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`
- Kotlin: idiomatisk stil, bruk `data class`, `sealed class`, extension functions
