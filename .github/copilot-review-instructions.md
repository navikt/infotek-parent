# Copilot code review-instruksjoner for infotek

Ved code review, sjekk alltid:

## Sikkerhet
- Logges det PII (fnr, navn, adresse)? → Avvis, bruk sakId i stedet
- Er nye endepunkter beskyttet med riktig auth (TokenX/Azure AD)?
- Har nais.yaml `accessPolicy.inbound` for alle nye apper?
- Har produksjonskonfig fallback for secrets, credentials, auth,
  tilgangskontroll, audit, database, schema eller eksterne endepunkter?
  Slike verdier skal være obligatoriske og feile ved oppstart. Lokale defaults
  skal ligge i en eksplisitt lokal/testprofil som ikke kan aktiveres i prod.

## Kotlin/Java
- Brukes versjoner fra infotek parent POM, eller overskrives de lokalt?
- Er HikariCP konfigurert med `maximumPoolSize=3` for Nais-miljø?
- Ingen CPU-limits i nais.yaml?

## Generelt
- Er feilhåndtering på plass (ikke bare happy path)?
- Er det tester for ny logikk?
- Er Flyway-migrasjoner bakoverkompatible?
