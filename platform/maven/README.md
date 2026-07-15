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

```xml
<settings>
  <servers>
    <server>
      <id>github</id>
      <username>DITT_GITHUB_BRUKERNAVN</username>
      <password>DITT_PAT_MED_read:packages</password>
    </server>
  </servers>
</settings>
```

Hent PAT: GitHub → Settings → Developer settings → Personal access tokens → `read:packages`.

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
