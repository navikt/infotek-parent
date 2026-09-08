---
name: nav-logghygiene
description: Rydd og vurder logging i NAV-applikasjoner uten å lekke personopplysninger eller endre API-atferd
license: MIT
metadata:
  domain: observability
  tags: logging security pii nais opentelemetry kotlin spring
---

# NAV logghygiene

Bruk denne skillen for å gjennomgå logger, exceptions, HTTP-klientinstrumentering og
loggkonfigurasjon i NAV-applikasjoner. Målet er driftsnyttige logger uten
personopplysninger, tokens, eksterne respons-bodyer eller unødvendig støy.

## Prinsipper

1. Logg én gang ved ansvarlig nivå. En integrasjon oversetter tekniske feil til en
   kontrollert domene-feil; den sentrale exception-handleren logger uventede feil.
   Unngå at samme exception logges med stack trace på flere nivåer.
2. Ikke logg fødselsnummer, navn, adresse, access token, `Authorization`, `Cookie`,
   request-/response-body eller ekstern fritekst. Ikke flytt rå data til secure log
   uten dokumentert behov, tilgangsstyring og forvaltningsansvar.
3. Oppslagslogg er et unntak: behold den separate, godkjente audit-/ArcSight-loggen
   som dokumenterer faktisk oppslag med riktig beslutning (`PERMIT` eller `DENY`).
4. Bruk `warn` for kjente, håndterte driftsfeil. Bruk `error` med stack trace for
   uventede feil som når felles exception-handler. Ikke logg forventede 4xx-avslag.
5. Ikke endre API-fallback eller feilkoder som del av en loggrydding. Avklar
   konsumentkontrakt først, særlig der en `catch` i dag gir degradert svar.

## Nais-observability

Foretrekk Nais OpenTelemetry auto-instrumentering for HTTP-server/-klient, database,
metrikker og tracing:

```yaml
observability:
  autoInstrumentation:
    enabled: true
    runtime: java
```

Når dette er aktivert, fjern egenbygde interceptorer som kun logger eller timer hvert
utgående HTTP-kall. Unngå egne metrikktagger med rå `host` eller `path` med mindre
kardinalitet, tilgang og driftsbehov er vurdert.

Ikke fjern en interceptor som videresender `Nav-CallId` eller `Nav-Consumer-Id` kun
fordi OpenTelemetry er aktivt. `traceparent` er tracing-propagasjon; call-id og
consumer-id kan være en separat integrasjonskontrakt for korrelasjon, audit og
feilsøking hos kildesystemet. Fjern ekstra header-varianter først etter bekreftelse
fra hvert kildesystem.

## Arbeidsflyt

1. Kartlegg `logger.*`, `log.*`, `LoggerFactory`, `catch`, `@ControllerAdvice`,
   `logback*`, `ClientHttpRequestInterceptor` og `MeterRegistry`.
2. Følg hver feil fra integrasjon til HTTP-svar. Dokumenter hvilke catches som
   oversetter feil, skriver auditlogg eller bevarer en etablert fallback.
3. Fjern flytlogger og suksesslogger som ikke har tydelig driftsverdi. Behold
   kontrollert logging for tokenfeil, eksterne systemfeil, degradert svar og
   uventede exceptions.
4. Saniter før data blir del av exception-melding eller logger. Foretrekk
   allowlistede feilkoder, status, systemnavn og exception-type.
5. Sjekk manifestet for Nais auto-instrumentering før custom HTTP-logger og
   metrikker fjernes.
6. Kjør eksisterende målrettede tester og repoets vanlige bygg. Test spesielt at
   auditlogg, statuskoder og fallback-svar er uendret.

## Kotlin/Spring-mønstre

```kotlin
logger.warn(
    "Kall til kildesystem feilet. kildesystem={}, status={}, feiltype={}",
    kildesystem,
    status,
    cause.javaClass.simpleName,
)
```

```kotlin
@ExceptionHandler
fun exception(e: Exception): ResponseEntity<Feilmelding> {
    logger.error("Uhåndtert exception", e)
    return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(generiskFeil)
}
```

Ikke bruk strenginterpolering for logger. Parametrisert SLF4J-logging reduserer både
formatfeil og unødvendig konstruksjon når nivået er deaktivert.

## Sjekkliste

- [ ] Ingen tokens, PII, headers, URI-query eller eksterne responser logges.
- [ ] Forventede 4xx-feil logges ikke.
- [ ] Håndterte 5xx-feil logger kun sikker kontekst uten stack trace.
- [ ] Uventede feil logges én gang sentralt med stack trace.
- [ ] Auditlogg er urørt og separat fra ordinær applikasjonslogging.
- [ ] Nais OpenTelemetry erstatter redundante HTTP-logger/metrikker.
- [ ] API-atferd, statuskoder og etablerte fallbacks er uendret.
