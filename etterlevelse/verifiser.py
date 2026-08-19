#!/usr/bin/env python3
"""
Verifiserer at en ETTERLEVELSE.md-rapport dekker alle suksesskriterier for
kravene den vurderer, og at statustallene i oppsummeringen stemmer.

Fanger den vanligste feilen i etterlevelsesanalyse: utelatte suksesskriterier.
Flere krav har 5-8 SK som er lette å overse ved manuell lesing.

Bruk:
    python3 etterlevelse/verifiser.py repos/<repo>/ETTERLEVELSE.md
    python3 etterlevelse/verifiser.py --alle
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HER = Path(__file__).resolve().parent
ROT = HER.parent
KRAV_FIL = HER / "krav.json"
RAPPORT_NAVN = "ETTERLEVELSE.md"

BOLD, DIM, RED, GREEN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m",
)

STATUS_EMOJI = ["✅", "⚠️", "🔴", "➖"]


def last_krav(krav_fil: Path = KRAV_FIL) -> dict:
    if not krav_fil.exists():
        sys.exit(
            f"{RED}Fant ikke {krav_fil}{RESET}\n"
            f"  Kjør: python3 etterlevelse/ekstraher.py"
        )
    return {k["id"]: k for k in json.loads(krav_fil.read_text(encoding="utf-8"))}


def finn_detaljvurderte(md: str) -> list[str]:
    """Krav som har egen <details>-blokk med SK-tabell."""
    return re.findall(r"<summary><strong>(K[\d.]+)</strong>", md)


def sk_i_blokk(md: str, kid: str) -> set[str]:
    """Suksesskriterie-numre nevnt i tabellen for ett krav."""
    etter = md.split(f"<strong>{kid}</strong>", 1)[1]
    blokk = etter.split("</details>", 1)[0]
    return set(re.findall(r"\|\s*SK\s*(\d+)\s*\|", blokk))


def statuser(md: str) -> list[str]:
    return [
        s.strip()
        for _, s in re.findall(
            r"<summary><strong>(K[\d.]+)</strong>.*?—\s*([^<]+)</summary>", md
        )
    ]


def oppsummering_tall(md: str) -> dict[str, int]:
    """Les tallene fra oppsummeringstabellen øverst i rapporten."""
    funn = {}
    for emoji in STATUS_EMOJI:
        for m in re.finditer(rf"\|\s*{re.escape(emoji)}[^|]*\|\s*(\d+)\s*\|", md):
            funn[emoji] = funn.get(emoji, 0) + int(m.group(1))
    return funn


def verifiser(sti: Path, krav: dict) -> bool:
    md = sti.read_text(encoding="utf-8")
    print(f"\n{BOLD}{sti}{RESET}")

    det = finn_detaljvurderte(md)
    if not det:
        print(f"  {RED}✗{RESET} Fant ingen detaljvurderte krav "
              f"(forventet <summary><strong>K...</strong>)")
        return False

    ukjent = [k for k in det if k not in krav]
    if ukjent:
        print(f"  {RED}✗{RESET} Ukjente krav-IDer: {', '.join(ukjent)}")
        return False

    ok = True

    # 1. Alle SK dekket per detaljvurdert krav
    mangler = []
    for kid in det:
        forventet = {s["n"] for s in krav[kid]["sks"]}
        funnet = sk_i_blokk(md, kid)
        if forventet - funnet:
            mangler.append((kid, len(forventet), sorted(forventet - funnet, key=int)))

    if mangler:
        ok = False
        print(f"  {RED}✗ Manglende suksesskriterier:{RESET}")
        for kid, tot, m in mangler:
            sk = ", ".join(f"SK{x}" for x in m)
            print(f"      {kid} ({tot} SK) mangler: {RED}{sk}{RESET}")
    else:
        sk_ant = sum(len(krav[k]["sks"]) for k in det)
        print(f"  {GREEN}✓{RESET} Alle {sk_ant} SK dekket for "
              f"{len(det)} detaljvurderte krav")

    # 2. Duplikate krav
    dupe = [k for k, n in Counter(det).items() if n > 1]
    if dupe:
        ok = False
        print(f"  {RED}✗{RESET} Krav vurdert flere ganger: {', '.join(dupe)}")

    # 3. Kravregnskap
    rest = len(krav) - len(set(det))
    print(f"  {DIM}{len(set(det))} detaljvurdert + {rest} på temanivå "
          f"= {len(krav)} krav totalt{DIM}{RESET}")

    # 4. Statustall mot oppsummering
    st = statuser(md)
    faktisk = {e: sum(e in s for s in st) for e in STATUS_EMOJI}
    oppgitt = oppsummering_tall(md)

    linje = "  ".join(f"{e} {faktisk[e]}" for e in STATUS_EMOJI)
    print(f"  {DIM}Status i innhold:{RESET} {linje}")

    avvik = [
        (e, faktisk[e], oppgitt[e])
        for e in STATUS_EMOJI
        if e in oppgitt and e != "➖" and oppgitt[e] != faktisk[e]
    ]
    if avvik:
        ok = False
        print(f"  {YELLOW}⚠ Oppsummeringstabellen stemmer ikke med innholdet:{RESET}")
        for e, f, o in avvik:
            print(f"      {e} oppgitt {o}, faktisk {f}")

    # 5. Gjenglemte placeholders
    rester = re.findall(r"<!-- [A-Z_]+ -->", md)
    if rester:
        ok = False
        print(f"  {RED}✗{RESET} Gjenglemte placeholders: {', '.join(set(rester))}")

    # 6. Krav uten status
    uten = [k for k, s in zip(det, st) if not any(e in s for e in STATUS_EMOJI)]
    if uten:
        ok = False
        print(f"  {RED}✗{RESET} Krav uten statusemoji i overskriften: "
              f"{', '.join(uten)}")

    # 7. Begrepsbruk (rådgivende — feiler ikke)
    sjekk_begrepsbruk(md)

    return ok


# Sammensetninger som nesten alltid er feil begrepsbruk i vår egen prosa.
# «Innsyn» alene er ikke med — det brukes legitimt i kravnavn fra katalogen,
# i kodereferanser (InnsynController) og i rettslig betydning (innsynsrett).
BEGREP_AVVIK = {
    "innsynsverktøy": "oppslagsverktøy",
    "innsynsløsning": "oppslagsløsning",
    "innsynssystem": "oppslagssystem",
    "innsynsflate": "oppslagsflate",
    "innsynslogg": "oppslagslogg",
    "innsynsportal": "oppslagsflate (eller presiser at det gjelder GDPR art. 15)",
    "innsynstjeneste": "oppslagstjeneste",
}

# Markører som viser at «innsyn» brukes i rettslig betydning eller om kode —
# da er ordet riktig og skal ikke flagges.
RETTSLIG_KONTEKST = (
    "art. 15",
    "artikkel 15",
    "gdpr",
    "personvernforordningen",
    "forvaltningsloven",
    "fvl.",
    "§ 18",
    "innsynsrett",
    "denne betydningen",
    "innsyncontroller",
    "/api/innsyn",
    "no.nav",
    "no/nav",
)


def sjekk_begrepsbruk(md: str) -> None:
    """Rådgivende: 'innsyn' har presis rettslig betydning og skremmer jurister
    når det brukes om ordinære saksbehandleroppslag."""
    funn = []
    for linje_nr, linje in enumerate(md.split("\n"), 1):
        lav = linje.lower()
        # Hopp over linjer der ordet brukes i rettslig betydning eller om kode
        if any(m in lav for m in RETTSLIG_KONTEKST):
            continue
        for feil, riktig in BEGREP_AVVIK.items():
            if feil in lav:
                funn.append((linje_nr, feil, riktig))

    if funn:
        print(f"  {YELLOW}⚠ Begrepsbruk — vurder 'oppslag' framfor 'innsyn':{RESET}")
        for nr, feil, riktig in funn:
            print(f"      linje {nr}: {YELLOW}{feil}{RESET} → {riktig}")
        print(f"      {DIM}Behold 'innsyn' i kravnavn fra katalogen, i kode-"
              f"referanser og der det gjelder innsynsrett{RESET}")


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "--alle":
        filer = sorted(
            list((ROT / "repos").glob(f"*/{RAPPORT_NAVN}"))
            + list((ROT / "repos").glob(f"*/etterlevelse/{RAPPORT_NAVN}"))
        )
        if not filer:
            sys.exit(f"Fant ingen {RAPPORT_NAVN} under repos/")
    elif args:
        filer = [Path(a) for a in args]
    else:
        sys.exit(__doc__.strip())

    mangler = [f for f in filer if not f.exists()]
    if mangler:
        sys.exit(f"{RED}Fant ikke:{RESET} {', '.join(str(f) for f in mangler)}")

    # Bruk repo-spesifikk krav.json (ved siden av rapporten) hvis den finnes —
    # det skjer når kravkatalogen er eksportert per repo fra
    # etterlevelse.ansatt.nav.no/dokumentasjoner. Faller ellers tilbake til
    # den delte etterlevelse/krav.json.
    resultat = []
    for f in filer:
        lokal_krav = f.parent / "krav.json"
        krav = last_krav(lokal_krav) if lokal_krav.exists() else last_krav()
        resultat.append(verifiser(f, krav))

    feil = resultat.count(False)
    print()
    if feil:
        print(f"{RED}{BOLD}✗ {feil} av {len(filer)} rapporter har avvik{RESET}")
        sys.exit(1)
    print(f"{GREEN}{BOLD}✓ {len(filer)} rapport(er) verifisert{RESET}")


if __name__ == "__main__":
    main()
