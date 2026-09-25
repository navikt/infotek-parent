# infotek-parent POM

Felles Maven parent POM for infotek-teamet. Arver fra `spring-boot-starter-parent` og setter godkjente versjoner for avhengigheter vi kontrollerer på tvers av alle repos.

## Bruk i child repo

```xml
<parent>
    <groupId>no.nav.infotek</groupId>
    <artifactId>infotek-parent</artifactId>
    <version>4.1.0</version>
</parent>
```

## Autentisering mot GitHub Packages

Parent POM publiseres til GitHub Packages og krever autentisering selv om repoet er public.

### Lokal utvikling — `~/.m2/settings.xml`

Sett `MAVEN_USERNAME` til ditt eget GitHub-brukernavn og velg én passordkilde:

```bash
export MAVEN_USERNAME=DITT_GITHUB_BRUKERNAVN

# Manuelt: les inn PAT uten shell-historikk
read -rs MAVEN_PASSWORD
export MAVEN_PASSWORD
make setup-maven-credentials

# Valgfritt på macOS/zsh: koble fremtidige shell til gh auth token
make setup-maven-credentials GH_TOKEN=1
```

Kjør bare kommandoen for valgt passordkilde. Med `GH_TOKEN=1` må GitHub CLI
være innlogget med `read:packages`. Scriptet legger en kommando, ikke tokenet,
i `~/.zshrc`; start et nytt shell etterpå. Du setter fortsatt
`MAVEN_USERNAME` selv i hvert shell. Uten `GH_TOKEN=1` må
`MAVEN_PASSWORD` være satt før kommandoen kjøres, og i alle shell som senere
kjører Maven. På andre plattformer og shell setter du begge variablene selv.

Kommandoen lager bare en manglende `github`-server, uten å skrive brukernavn
eller PAT til disk. Hvis serveren finnes, endrer den ingenting, men minner deg
om å bytte ut brukernavn og token som er lagret direkte. Hvis nødvendige
verdier mangler, stopper den før filene endres.

```xml
<settings>
  <servers>
    <server>
      <id>github</id>
      <username>${env.MAVEN_USERNAME}</username>
      <password>${env.MAVEN_PASSWORD}</password>
    </server>
  </servers>
</settings>
```

Et token med `read:packages` er normalt nok for nedlasting; private pakker kan
også kreve repo-tilgang og SSO. Oppdater GitHub CLI-scopes med
`gh auth refresh -h github.com -s read:packages` i en vanlig terminal.
Publisering krever `write:packages`. CI-eksempelet nedenfor bruker
`x-access-token`, men lokal bruk standardiserer ikke på det brukernavnet.

Eller bruk `nais login` som oppdaterer credentials automatisk.

### npm/pnpm — `~/.npmrc`

```
//npm.pkg.github.com/:_authToken=DITT_PAT
@navikt:registry=https://npm.pkg.github.com
```

### CI — GitHub Actions

```yaml
- uses: actions/setup-java@v4
  with:
    java-version: '25'
    distribution: temurin
    server-id: github
    server-username: MAVEN_USERNAME
    server-password: MAVEN_PASSWORD

- name: Build
  run: mvn --batch-mode verify
  env:
    MAVEN_USERNAME: x-access-token
    MAVEN_PASSWORD: ${{ secrets.GITHUB_TOKEN }}
```

Jobben trenger `permissions: packages: read`.

## Publiser ny versjon

```bash
# Fra infotek-parent repo:
make release-parent VERSION=4.1.1
```

Dette tagger og trigger GitHub Actions som publiserer til GitHub Packages.

## Styrte versjoner

Se `platform/maven/pom.xml` for fullstendig liste. Viktigste:

| Egenskap | Verdi |
|---|---|
| `spring-boot-starter-parent` | 4.1.0 |
| `kotlin.version` | 2.3.21 |
| `token-validation.version` | 6.0.11 |
| `tomcat.version` | 11.0.22 |
| `postgresql.version` | 42.7.7 |
| `testcontainers.version` | 1.21.4 |
| `mockk.version` | 1.14.2 |
| `mock-oauth2-server.version` | 5.0.2 |
