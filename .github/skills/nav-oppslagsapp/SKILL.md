---
name: nav-oppslagsapp
description: Planlegg og bygg interne Nav-oppslagsapper med React-frontend, Spring Boot BFF/backend, Nais, Azure AD/Wonderwall, Azure OBO, lokal mock OIDC og CI
license: MIT
metadata:
  domain: architecture
  tags: oppslagsapp react spring-boot bff nais azure-ad wonderwall obo mock-oidc ci
---

# Nav-oppslagsapp

Bruk denne skillen når du skal lage eller modernisere en intern Nav-oppslagsapp med React-frontend og Spring Boot i backend. Skillen passer også når du skal velge arkitektur, sette opp Nais, auth og lokal utvikling.

## Når du skal bruke den

- Ny intern app for saksbehandlere.
- Modernisering av en eksisterende oppslagsapp.
- Vurdering av auth, integrasjoner, probes eller CI.
- Lokalt oppsett med Wonderwall og mock-oidc.

## Arkitekturvalg

Start med dataflyten, ikke teknologien.

- Monolitt: bruk når UI, auth og datahenting er små og deler samme audience. Det gir færrest deployer og minst drift.
- Separat frontend og backend: bruk når frontend kan snakke direkte med backend, og backend ikke trenger eget audience eller OBO.
- Frontend + BFF + fag-backend: bruk når backend trenger eget audience, eller når den skal kalle PDL, Tilgangsmaskin eller andre systemer med OBO.

**Anbefaling:** Velg frontend/BFF + fag-backend når du har brukerinnlogging i nettleseren og samtidig trenger et eget backend-audience. Da holder BFF oversikten over browser-auth, mens fag-backend får egen grense, egne probes og egne outbound-regler. Ulempen er flere ledd, men det er riktig pris når auth og integrasjoner skal holdes adskilt.

🔴 Rød sone: auth, OBO og accessPolicy. Gå gjennom disse nøye.

## Sperrer

- Ikke hardkod appnavn, namespace, gruppe-ID-er eller secrets.
- Ikke skjul manglende auth bak midlertidige defaults i produksjonskonfig.
- Ikke dropp `accessPolicy.inbound` eller outbound-regler.
- Ikke bruk frontend direkte mot fag-backend når backend trenger eget audience.
- Ikke legg inn CPU-limits i Nais. Bruk bare requests.

## Nais-oppsett

- Bruk egne manifest for frontend og backend når appen har egen BFF eller fag-backend.
- Sett `accessPolicy.inbound` eksplisitt for hver tjeneste.
- Legg inn `accessPolicy.outbound` for alle kilder backend kaller.
- Bruk separate liveness- og readiness-probes. Legg til startup-probe når oppstarten er treg.
- Les audience, klient-id-er og andre miljøverdier fra miljøvariabler. Hardkod dem ikke i kode eller manifest.

Eksempel på inngående tilgang:

```yaml
accessPolicy:
  inbound:
    rules:
      - application: <frontend-app>
```

## Autentisering

- Bruk Wonderwall foran frontend når appen er for ansatte.
- Bruk Azure AD som identitetskilde for saksbehandlerinnlogging.
- Bruk Azure OBO i fag-backend når den skal kalle videre på vegne av brukeren.
- Bruk token-claims og roller fra IDP. Ikke legg inn egne identitetskart i kode.

Når backend trenger eget audience og OBO, skal frontend ikke snakke direkte med fag-kilder. La BFF ta imot brukerens forespørsel og la fag-backend gjøre domenekallene.

## Lokal utvikling

- Bruk mock-oidc til å simulere Azure AD lokalt.
- Start Wonderwall og ingress i samme oppsett som frontend og backend.
- Test at innlogging, claims og ruter fungerer gjennom den samme flyten som i Nais.
- Bruk Playwright eller tilsvarende E2E-tester mot lokal innlogging.

Typisk lokal flyt er:

```bash
docker compose up -d mock-oidc wonderwall ingress
```

Bruk samme mønster som i referanseappene: frontend går gjennom Wonderwall, og backend får token fra mock-oidc eller Azure AD-liknende oppsett.

## CI

- Bygg og test frontend og backend i samme pipeline.
- Valider Nais-manifest, JSON og YAML før deploy.
- Kjør E2E med mock-oidc slik at auth-flyten testes uten ekte Azure AD.
- Legg inn Dependabot for Maven, pnpm, Docker og GitHub Actions.

Et godt CI-oppsett gjør dette i rekkefølge: bygg, enhetstester, manifestvalidering, E2E og deploy.

## Referansemønstre

Bruk disse repoene som mønster når du trenger noe å følge:

- `infotrygd-brukeroppslag` for full oppslagsapp med frontend, BFF, backend, Wonderwall, OBO og lokal mock-oidc.
- `infotek-personkort` for en enklere oppslagsapp uten unødig DB- eller Kafka-kompleksitet i første fase.
- `historisk-pensjon` for lokal utvikling, Wonderwall, mock-oidc og E2E-flyt.
- `historisk-regnskap` for tilsvarende oppsett med tydelig Nais, CI og innloggingsflyt.

## Leveranse

- Forklar hvilken arkitektur du valgte og hvorfor.
- List hvilke auth-grenser og OBO-kall som finnes.
- Vis hvilke `accessPolicy`-regler og probes du satte opp.
- Beskriv lokal flyt med mock-oidc og CI-flyt med E2E.
