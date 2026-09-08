---
name: nav-konfigopprydding
description: Rydd ubrukte Spring-, Nais-, Docker- og dependency-konfigurasjoner trygt i NAV-applikasjoner
license: MIT
metadata:
  domain: maintenance
  tags: spring nais docker configuration dependencies cleanup kotlin
---

# NAV konfigopprydding

Bruk denne skillen når en NAV-applikasjon har gamle properties, profiler,
konfigurasjonsklasser, miljøvariabler eller avhengigheter. Målet er å fjerne
bekreftet død konfigurasjon uten å endre oppstart, deploy, sikkerhet eller
konsumenters API-kontrakt.

## Sperrer

Ikke fjern uten særskilt avklaring:

- datasource-, Vault-, auth- eller sikkerhetskonfigurasjon
- aktive Spring-profiler med indirekte biblioteksbruk
- Nais `accessPolicy`, ingress, probes, Vault-mounts eller observability
- `open-in-view`, health-detaljer eller Swagger-produksjonsinnstillinger
- exception-håndtering eller fallback som kan være en etablert API-kontrakt
- lokal Compose-konfigurasjon flyttet til `src/main/resources`: testressurser
  pakkes ikke i applikasjons-JAR, men lokale profiler skal heller ikke følge med
  i produksjonsartefakten uten et reelt runtime-behov

## Arbeidsflyt

1. Start med en ren feature-branch. Ikke bland opprydding med sikkerhetsfiks
   med mindre endringen er direkte nødvendig for sikkerhetsfiksen.
2. Spor hver kandidat på tvers av hele repoet:

   ```bash
   rg -n 'PROPERTY|property\\.path|ClassName' .
   ```

   Søk i produksjonskode, tester, `application*.yml`, `logback*`,
   `docker-compose*`, Nais-manifester, Nais-variabelfiler og CI.
3. Skill mellom Nais og applikasjonen:
   - Nais bruker feltene under `spec` når podden opprettes.
   - `spec.env` videresender bare miljøvariabler til applikasjonen; Nais
     tolker normalt ikke `APP_*`-verdien.
   - En templatevariabel kan først fjernes når både manifestreferansen og
     verdien i `dev.json`/`prod.json` er borte.
4. Verifiser Spring-bruk indirekte. `@Component`/`@Configuration` kan oppdages
   av component scanning selv om de ikke importeres eksplisitt. Ikke fjern
   konfigurasjon bare fordi den mangler direkte Kotlin-referanser.
5. Fjern i små, selvstendige grupper:
   - død property + alle miljøspesifikke verdier
   - død wrapper-konfigurasjon
   - ubrukt profil + klasse + manifestaktivering
   - produksjonsavhengighet som kun brukes i tester → `test`-scope
   - redundant test-property først når profilen fortsatt får verdien via en
     annen, faktisk binding
6. Etter hver gruppe: valider JSON/YAML, søk etter gjenværende referanser og
   kjør repoets vanlige bygg samt nærmeste Spring-konteksttest.

### Vault-basert datasource

En manuell `DataSource`-bean kan være nødvendig når URL, brukernavn eller passord
leses fra Vault-monterte filer i stedet for vanlige Spring-properties. Ikke fjern
`spring.datasource.hikari` bare fordi standard `spring.datasource.url`, `username`
og `password` ikke brukes: Hikari-innstillinger kan fortsatt bindes til den manuelle
beanen med `@ConfigurationProperties`.

Spor filnavn særskilt. En lokal Compose-mount kan for eksempel hete `jdbcUrl`, mens
produksjonens standard er `jdbc_url`. Behold en Compose-spesifikk miljøoverstyring
når den bare løser denne lokale forskjellen; ikke opprett en produksjonspakket
`application-dev.yml` kun for å erstatte den.

## Vanlige trygge kandidater

- Properties uten noen binding eller faktisk kodebruk.
- Nais-templatevariabler som bare forsyner slike properties.
- Import-wrappere som kun importerer komponenter Spring allerede scanner.
- `@EnableScheduling` uten `@Scheduled`, scheduler eller tredjepartsbehov.
- Lokal debug-profil som kun aktiverer støyende logging.
- Produksjonsavhengighet som bare brukes av testkode.
- GraphQL-felt som hverken deserialiseres eller brukes av applikasjonen, etter at
  den faktiske query-kontrakten er testet.

## Validering

```bash
# Alle referanser må være borte, med unntak av tilsvarende tredjepartsnavn.
rg -n 'gammelProperty|GammelKlasse|gammel-profil' .

# Nais-variabelfiler må fortsatt være gyldig JSON.
node -e 'JSON.parse(require("fs").readFileSync("nais/dev.json", "utf8"))'
node -e 'JSON.parse(require("fs").readFileSync("nais/prod.json", "utf8"))'

# Følg repoets etablerte kommando, for eksempel:
mvn verify

# Ved profil-/ressursendringer: bygg rent og kontroller innholdet i artefakten.
mvn clean package -DskipTests
jar tf target/*.jar | grep 'BOOT-INF/classes/application-'
```

## Leveranse

Beskriv eksplisitt hva som ble fjernet, hvor det tidligere var konfigurert,
hvorfor det var dødt, og hvilke konfigurasjoner som bevisst ikke ble berørt.
