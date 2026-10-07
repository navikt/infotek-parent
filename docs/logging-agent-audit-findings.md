# Funn om syslog4j i auditlogging

Kontrollen viser deklarert avhengighet og appenderbruk, ikke effektiv Maven-avhengighetsgraf.
Vedlikeholdsstatus for `com.papertrailapp:logback-syslog4j` er ikke bekreftet.
Ikke fjern eller bytt auditlogg som del av generell loggrydding.

| Repo | Funn |
|---|---|
| platform/maven | `platform/maven/pom.xml:81` (versjon styrt i dependencyManagement) |
| infotek-databaseuttrekk | `repos/infotek-databaseuttrekk/backend/pom.xml:94` (direkte avhengighet)<br>`repos/infotek-databaseuttrekk/backend/src/main/resources/logback-spring.xml:30` (Syslog4jAppender) |
| infotek-statistikk | ingen treff |
| infotrygd-the-final-countdown | ingen treff |
| infotrygd-brukeroppslag | `repos/infotrygd-brukeroppslag/backend/pom.xml:104` (direkte avhengighet)<br>`repos/infotrygd-brukeroppslag/backend-for-frontend/pom.xml:73` (direkte avhengighet)<br>`repos/infotrygd-brukeroppslag/pom.xml:64` (versjon styrt i dependencyManagement)<br>`repos/infotrygd-brukeroppslag/backend/src/main/resources/logback-spring.xml:27` (Syslog4jAppender)<br>`repos/infotrygd-brukeroppslag/backend-for-frontend/src/main/resources/logback-spring.xml:27` (Syslog4jAppender) |
| infotrygd-feed-proxy-v2 | ingen treff |
| infotrygd-hentsaksliste | `repos/infotrygd-hentsaksliste/backend/pom.xml:116` (direkte avhengighet)<br>`repos/infotrygd-hentsaksliste/pom.xml:68` (versjon styrt i dependencyManagement)<br>`repos/infotrygd-hentsaksliste/backend/src/main/resources/logback-spring.xml:27` (Syslog4jAppender) |
| infotrygd-replikering | ingen treff |
| historisk-exodus | `repos/historisk-exodus/pom.xml:118` (direkte avhengighet)<br>`repos/historisk-exodus/src/main/resources/logback-spring.xml:28` (Syslog4jAppender) |
| historisk-pensjon | `repos/historisk-pensjon/pom.xml:143` (direkte avhengighet)<br>`repos/historisk-pensjon/src/main/resources/logback-spring.xml:26` (Syslog4jAppender) |
| historisk-regnskap | `repos/historisk-regnskap/pom.xml:119` (direkte avhengighet)<br>`repos/historisk-regnskap/src/main/resources/logback-spring.xml:28` (Syslog4jAppender) |
| historisk-tidsbegrenset-uforestonad | `repos/historisk-tidsbegrenset-uforestonad/pom.xml:152` (direkte avhengighet)<br>`repos/historisk-tidsbegrenset-uforestonad/src/main/resources/logback-spring.xml:28` (Syslog4jAppender) |

## Mulig erstatning

Undersøk `net.logstash.logback:logstash-logback-encoder` med `LogstashTcpSocketAppender` og `PatternLayoutEncoder` som kandidat for TCP. Prosjektet dokumenterer TCP, valgfri TLS og støtte for vilkårlig Logback-encoder. Det er **ikke** en verifisert direkte erstatning: sjekk syslog-framing, CEF-felt, Logback-versjon, mottakerkrav og hva som skjer når tilkobling eller asynkron kø feiler. Standardoppsettet kan miste hendelser ved full kø. Bevar `PERMIT`/`DENY` og verifiser levering til auditmottakeren før et bytte.

Kilder: [Papertrails beskrivelse av TCP/TLS](https://github.com/papertrail/logback-syslog4j), [logstash-logback-encoders TCP-dokumentasjon](https://github.com/logfellow/logstash-logback-encoder#tcp-appenders), [Logbacks innebygde syslog-appender](https://logback.qos.ch/manual/appenders.html#SyslogAppender).
