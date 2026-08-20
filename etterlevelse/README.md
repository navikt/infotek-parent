# Etterlevelse

Kravkilde og verktøy for å analysere infotek-repoene mot NAVs etterlevelseskatalog.

| Fil | Formål |
|-----|--------|
| `suksesskriterier.html` | Kravkilden — eksport fra etterlevelseskatalogen. **90 krav, 270 suksesskriterier** |
| `krav.json` | Strukturert uttrekk. Auto-generert — ikke rediger manuelt |
| `ekstraher.py` | Leser HTML-kilden → `krav.json`, og slår opp krav med `--vis` |
| `verifiser.py` | Kvalitetssjekk av en ferdig `ETTERLEVELSE.md` |

**Arbeidsdeling:** Denne mappa inneholder data og verktøy. *Hvordan* analysen
gjennomføres — kravfiltrering, grep-oppskrifter, rapportformat og begrepsbruk —
står i `.github/skills/nav-etterlevelse/SKILL.md`, som er eneste kilde for de
reglene. Ikke dupliser dem hit.

## Bruk

```bash
# Slå opp alle suksesskriterier for gitte krav
python3 etterlevelse/ekstraher.py --vis K154.1 K255.1

# Verifiser en rapport
python3 etterlevelse/verifiser.py repos/infotrygd-brukeroppslag/ETTERLEVELSE.md

# Verifiser alle rapporter under repos/
python3 etterlevelse/verifiser.py --alle

# Regenerer krav.json (kun nødvendig ved ny katalogeksport)
python3 etterlevelse/ekstraher.py
```

Skriptene finner sine egne filer relativt til `etterlevelse/`, så de kan kjøres fra
hvilken som helst katalog.

## Hvorfor verifiser.py finnes

Den vanligste feilen i etterlevelsesanalyse er **utelatte suksesskriterier**. Flere
krav har 5–8 SK, og SK-numrene er verken sekvensielle eller sorterte i kilden. I
første analyse av `infotrygd-brukeroppslag` manglet 7 krav til sammen 20
suksesskriterier — K255.1 hadde kun 2 av 8 SK vurdert.

Skriptet sjekker sju ting:

| # | Sjekk | Feiler |
|---|-------|--------|
| 1 | Alle SK dekket per detaljvurdert krav | ✅ |
| 2 | Ingen krav vurdert dobbelt | ✅ |
| 3 | Kravregnskapet går opp (detaljvurdert + temanivå = 90) | ✅ |
| 4 | Statustallene i oppsummeringen stemmer med innholdet | ✅ |
| 5 | Ingen gjenglemte `<!-- PLACEHOLDER -->` | ✅ |
| 6 | Alle krav har statusemoji i overskriften | ✅ |
| 7 | Begrepsbruk — «oppslag» framfor «innsyn» | rådgivende |

Sjekk 1–6 gir exit code 1 ved avvik og egner seg i CI. Sjekk 7 skriver kun en
advarsel — reglene bak den står i SKILL.md.

Verifiseringen forutsetter rapportformatet definert i SKILL.md. Endres formatet,
må parsingen i `verifiser.py` oppdateres i samme slengen.

## Oppdatere kravkilden

Katalogen endres over tid. Ved ny eksport:

```bash
cp ~/Downloads/suksesskriterier.html etterlevelse/
python3 etterlevelse/ekstraher.py           # forventet: 90 krav, 270 SK
python3 etterlevelse/verifiser.py --alle    # avdekker utdaterte rapporter
```

Avviker tallene fra 90/270, er katalogen endret. Oppdater da forventningen i
`SKILL.md`, og kjør `--alle` for å se hvilke rapporter som ikke lenger går opp mot
kravregnskapet.

## Analyserte repos

| Repo | Rapport | Kritiske funn |
|------|---------|---------------|
| `infotrygd-brukeroppslag` | ✅ Komplett — 38 krav / 121 SK | 1 — `/tables` er `@Unprotected` |
