---
name: repo-oppsett
description: Verifiser og fiks konfigurasjon i Infotek-repoer på tvers av GitHub, Nais, frontend, backend og database
license: MIT
metadata:
  domain: repository-maintenance
  tags: repo-oppsett github-actions nais frontend backend database spring kotlin pnpm maven
---

# Verifisering og fiks av repo-oppsett

Bruk denne skillen når et team-repo skal kontrolleres mot Infotek-teamets
standarder, eller når konkrete avvik skal fikses. Målet er å finne faktiske feil
og gjøre små, dokumenterte endringer. Ikke standardiser for standardiseringens
skyld.

## Omfang

Les `repos.yaml` i parent-repoet før du vurderer et underrepo. Bruk bare repoer med
`managed: true` i masseoperasjoner. Et enkelt repo kan gjennomgås når brukeren
ber om det, også hvis repoet er umanaged.

Skillen skal skille mellom:

- felles teamstandard som bør være lik i alle repoer
- teknologispesifikk konfigurasjon
- bevisste repo-spesifikke avvik
- lokale arbeidsfiler og eksisterende endringer som ikke skal overskrives

## Arbeidsflyt

1. Kjør `git status --short --branch` i parent-repoet og målrepoet.
2. Ikke kjør `git fetch`, `git pull` eller `make git-update`. Be utvikleren kjøre
   `make git-update` først når oppgaven gjelder oppdaterte arbeidskopier eller
   flere repoer.
3. Les repoets faktiske filer før du foreslår en fiks:
   `repos.yaml`, README, Makefile, pom.xml, package.json, `.npmrc`,
   `pnpm-workspace.yaml`, Nais-manifester, workflows og lokale instrukser.
4. Sammenlign med minst ett relevant referanserepo i samme stack.
5. Lag en avviksoversikt med fil, forventet standard, faktisk verdi og risiko.
6. Fiks bare verifiserte avvik. Be om avklaring før auth, deployrekkefølge,
   secrets, database eller API-kontrakter endres.
7. Kjør målrettet validering og vis hvilke avvik som fortsatt er bevisste.

## Fikseregler

- Ikke endre filer som ikke inngår i avviket.
- Behold repo-spesifikke valg når de har en dokumentert teknisk grunn.
- Ikke kopier et helt referanserepo. Overfør bare mønsteret som løser avviket.
- Ikke slett overrides, auth, secrets, migrasjoner eller workflow-steg uten å
  dokumentere hva som bruker dem og hvorfor de kan fjernes.
- Oppdater tester eller validering når fiksingen kan endre oppførsel.
- Stopp hvis en endring krever ny secret, ny tilgang, endret deployrekkefølge
  eller en uavklart auth-beslutning.

## Repo metadata og parent

Kontroller:

- `repos.yaml` har riktig `org`, `namespace`, `default_branch`, `managed` og
  `environments`.
- Makefile-targets bruker bare `select(.managed == true)` ved iterasjon over repoer.
- Parent POM brukes for delte Maven-versjoner.
- Felles pnpm- og Biome-konfigurasjon har én tydelig kilde til sannhet.
- `ai/AGENTS.md` og README-oversikter regenereres med etablerte Makefile-targets,
  ikke redigeres manuelt.

## GitHub og CI

Kontroller workflowene under `.github/workflows`:

- Actions er pinnet til full commit-SHA med versjonskommentar.
- Hver jobb har minste nødvendige `permissions`.
- Alle jobber har `timeout-minutes`.
- Deploy-workflows har `concurrency`.
- Pull request-workflowen bygger og tester samme artefakt som deploy-flyten.
- Frontend- og backend-steg bruker samme Node-, pnpm-, Java- og Maven-versjoner
  som repoet ellers.
- GitHub Packages krever eksplisitt auth når private pakker brukes.
- Secrets kommer fra GitHub Secrets eller Nais, aldri fra kildekode eller defaults.
- `pull_request_target` brukes ikke til å kjøre kode fra en PR-branch.

Ikke bytt deployrekkefølge, miljø, secrets eller reusable workflows uten at
utvikleren har godkjent endringen.

## Frontend

For React/Vite med pnpm kontrollerer du:

- `package.json` har tydelige `build`, `lint` eller `biome`, `format` og
  `typecheck`-scripts der repoet trenger dem.
- `.npmrc` bruker npmjs for offentlige pakker og GitHub Packages for interne
  `@navikt`- og `@nais`-pakker når de faktisk kommer derfra.
- `ignore-scripts=true` og `engine-strict=true` er med i teamstandarden.
- `pnpm-workspace.yaml` har supply-chain-innstillinger fra teamstandarden.
- Repo-spesifikke `overrides` beholdes til bruken er undersøkt. Fjern dem bare
  når lockfila og dependency-treet viser at de ikke lenger trengs.
- TypeScript- og Biome-konfigurasjon følger valgt standard. Ikke bland `extends`
  fra en publisert pakke med en lokal, eksplisitt konfigurasjon uten en grunn.
- `pnpm-lock.yaml` oppdateres med riktig pnpm-versjon etter dependency-endringer.
- Frontend bygges i CI før statiske filer kopieres til backend-image, hvis repoet
  bruker samlet deploy.

## Backend og auth

For Kotlin/Spring Boot kontrollerer du:

- Constructor injection brukes.
- Spring Security er stateless i produksjon.
- JWT-validering og gruppe-/rolle mapping er eksplisitt.
- Health-endepunkter er åpne for Nais-prober, mens API-endepunkter har auth.
- Lokal auth ligger i en eksplisitt local/test-profil og kan ikke aktiveres
  utilsiktet i produksjon.
- Produksjonsverdier for issuer, grupper, database, audit og eksterne endepunkter
  er obligatoriske.
- Auth-endringer vurderes som rød sone. Kontroller både backend-kode,
  frontend-flyt, Wonderwall/Azure sidecar og Nais-manifest.
- Ikke logg tokens, claims med personopplysninger eller brukerdata.

For Ktor eller Rapids & Rivers bruker du repoets Ktor-mønster i stedet for
Spring-reglene. Ikke innfør Ktor-, Koin- eller Arrow-avhengigheter i et
Spring-repo uten en egen beslutning.

## Database og Flyway

Kontroller:

- PostgreSQL-tilkobling og secrets er obligatoriske i produksjon.
- Hikari-poolen følger teamets Nais-standard.
- Flyway-migrasjoner er versjonerte med `V{n}__{beskrivelse}.sql`.
- Eksisterende migrasjoner endres ikke.
- SQL bruker parametre, ikke strengkonkatenering med input.
- Databaseendringer har test eller validering som dekker oppstart og migrering.
- Lokale defaults ligger i lokal/test-profil og lekker ikke inn i produksjon.

## Nais

Kontroller:

- `accessPolicy.inbound` finnes og er eksplisitt for alle endepunkter.
- Outbound-regler finnes for eksterne tjenester som krever dem.
- Ingen CPU-limits er satt. Bruk CPU requests.
- Liveness, readiness og eventuell startup-probe peker på faktiske health-endepunkter.
- Azure sidecar, application claims, ingress, Vault, database og observability
  samsvarer med backendens behov.
- Miljøspesifikke verdier kommer fra variabelfiler eller secrets, ikke hardkodede
  tokens eller passord.

## Validering

Bruk repoets egne kommandoer. Typiske målrettede kontroller er:

```bash
pnpm install --frozen-lockfile
pnpm exec biome check .
pnpm exec tsc -b
mvn --batch-mode clean verify
```

Valider også YAML, JSON og Nais-manifest med verktøy repoet allerede bruker.
Ved workflow-endringer kan `zizmor` brukes hvis det allerede finnes i oppsettet.
Ikke installer nye verktøy bare for å følge denne skillen.

## Leveranse

Rapporter:

- hvilke avvik som ble verifisert
- hvilke filer som ble fikset og hvorfor
- hvilke avvik som er bevisste og beholdes
- hvilke tester og valideringer som er kjørt
- eventuelle blokkeringer, særlig feilet CI, manglende auth eller utdatert arbeidskopi
