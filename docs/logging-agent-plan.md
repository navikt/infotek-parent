# Plan: Midlertidig logging-agent for managed-repoer

## Problem og mål

`logging-agent` skal brukes systematisk på alle repoer med `managed: true` i
`repos.yaml`. Agenten skal kunne analysere logging, gjøre nødvendige endringer,
lage feature-branch og forberede pull request. Arbeidet skal styres fra én
sentral kommando i `infotek-parent`, og parent-repoet skal ha en statusrapport
per repo. Løsningen skal være midlertidig og kunne avvikles når alle repoer er
godkjent.

## Foreslått tilnærming

1. Legg til en eksplisitt, midlertidig logging-workflow i parent-repoet, helst
   som et Makefile-target som kaller et eget script.
2. Scriptet leser kun repoer filtrert med `managed == true` fra `repos.yaml`,
   validerer at arbeidskopiene finnes, og stopper trygt for dirty worktrees,
   feil branch eller manglende verktøy.
3. For hvert repo opprettes en standardisert feature-branch. Agenten får
   repoets lokale kontekst og følger `nav-logghygiene`: ingen PII, tokens,
   request-/response-body eller endring av API-fallbacks.
4. Agenten gjør endringer og tester lokalt. Scriptet samler resultatet,
   genererer en statusrapport per repo og oppretter eller forbereder PR med
   standardisert beskrivelse. Push og eventuelle irreversible GitHub-operasjoner
   må ha eksplisitt kontrollpunkt i arbeidsflyten.
5. Statusrapporten bruker faste statuser, for eksempel `ikke startet`,
   `blokkert`, `endret`, `tester feilet`, `PR opprettet`, `godkjent` og
   `ferdig`. Rapporten skal inneholde commit-/branch-/PR-lenke når dette finnes,
   samt årsak ved blokkering.
6. Når alle managed-repoer har dokumentert godkjent PR, markeres agenten som
   avviklet i dokumentasjonen. Den sentrale kommandoen beholdes ikke som
   permanent generell masseendringsmekanisme.

## Arbeidssteg

1. Kartlegg hvordan Copilot CLI/agenten kan startes deterministisk fra et
   script, og hvilke krav som gjelder for autentisering, interaktivitet og
   branch/PR-operasjoner.
2. Kartlegg eksisterende Git- og PR-hjelpere i Makefile og `scripts/`, og
   gjenbruk repo-utvalg, statuskontroll, branch-konvensjoner og eksisterende
   PR-flyt i stedet for å duplisere logikk.
3. Velg rapportformat og plassering. Rapporten bør være en ikke-generert,
   menneskelesbar fil under parent-repoets arbeidsområde eller en dedikert
   midlertidig statusmappe, med tydelig eierskap og oppdateringsrutine.
4. Implementer sentral kommando og orchestrator med:
   - kun `managed: true`
   - dry-run/forhåndsvisning
   - ett repo av gangen og isolert feilrapportering
   - preflight for klonet repo, dirty tree, branch og verktøy
   - standardisert branch-navn, for eksempel `chore/logging-hygiene`
   - eksplisitt håndtering av eksisterende branch/PR
   - validering av tester og relevante logger før PR-forberedelse
5. Definer agentprompten som en versjonert del av parent-repoet, med krav om
   kodebevis, minimal endring, tester og kontroll av API-atferd.
6. Legg til tester for parser, managed-filtrering, statusoverganger,
   blokkeringer, branch-navn, eksisterende PR og feilhåndtering. Legg til
   integrasjonstest eller testmodus som ikke kaller agenten/GitHub.
7. Oppdater README og relevant Copilot-dokumentasjon med bruk, begrensninger,
   midlertidighet, stoppkriterium og sikkerhetsregler.
8. Verifiser med script-tester, Makefile dry-run og eksisterende tester/build.

## Ferdigkriterier

Et repo regnes som ferdig først når alle punktene er oppfylt:

- logging er gjennomgått etter `nav-logghygiene`
- endringer er gjort med tilhørende tester
- relevante tester/build er grønne
- diff og logging vurderes av menneskelig code review
- PR er opprettet og godkjent/merget etter teamets vanlige prosess
- statusrapporten inneholder kodebevis, branch og PR-status

Hele initiativet er ferdig når alle `managed: true`-repoer oppfyller kriteriene,
eller et eksplisitt unntak er dokumentert med eier og begrunnelse.

## Avklarte forutsetninger

- `managed: false`-repoer skal ikke leses eller endres av orchestratoren.
- Endringer gjelder underrepoene, ikke automatisk parent-repoets egen logging.
- PR-er skal følge eksisterende branch- og reviewregler.
- Ingen commit eller push skal utføres skjult eller utenfor den dokumenterte
  kontrollflyten.
- Agenten er midlertidig; statusrapporten må gjøre avvikling etterprøvbar.
- En full kjøring krever `--all`. `--dry-run` viser utvalget uten å endre repoer.
- En eksisterende logging-branch blokkerer ny kjøring til den er gjennomgått
  manuelt.
- PR-flyten får bare repoer som passerte agent og tester i samme kjøring.
- Agent- og testkjøringer har tidsavbrudd. Feil, branch, `HEAD` og diff-hash
  skrives til testresultatet.

## Åpne spørsmål

- Nøyaktig mekanisme for å starte den registrerte `logging-agent` fra en lokal
  sentral kommando må verifiseres før implementering.
- Det må velges om PR-opprettelse skal utføres av orchestratoren eller overlates
  til eksisterende `make pr-lag`/manuell godkjenning etter agentkjøringen.
- Rapportens endelige filformat og om rapporten skal committes i parent-repoet
  må besluttes før implementering.

## Rød sone

Logging som kan inneholde PII, tokenhåndtering, exception-/fallback-atferd og
vurdering av auditlogg er rød sone. Agenten kan foreslå og teste endringer, men
utvikleren må kontrollere disse delene før PR og forklare avvik fra eksisterende
atferd. Orchestratoren skal ikke automatisk godkjenne eller merge slike endringer.
