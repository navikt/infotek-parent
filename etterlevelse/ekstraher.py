#!/usr/bin/env python3
"""
Ekstraherer alle krav og suksesskriterier fra etterlevelse/suksesskriterier.html
til strukturert JSON i etterlevelse/krav.json.

JSON-filen brukes som fasit av etterlevelse/verifiser.py og av
skillen .github/skills/nav-etterlevelse/ ved analyse av enkeltrepoer.

Bruk:
    python3 etterlevelse/ekstraher.py [KILDE] [MAAL]
    python3 etterlevelse/ekstraher.py --vis K154.1 K255.1
"""

import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

HER = Path(__file__).resolve().parent
KILDE_DEFAULT = HER / "suksesskriterier.html"
MAAL_DEFAULT = HER / "krav.json"

TEMA_NAVN = {
    "personvern": "Personvern",
    "infosikkerhet": "Informasjonssikkerhet",
    "saksbehandling": "Saksbehandling og forvaltningsrett",
    "okonomi": "Økonomi",
    "arkiv": "Arkiv og journalføring",
    "el_kom": "Elektronisk kommunikasjon",
    "uu": "Universell utforming",
    "inter_og_samh": "Interoperabilitet og samhandling",
    "stat_styr": "Statistikk og styringsinformasjon",
    "sprak": "Språk",
}


def strip_tags(s: str) -> str:
    """Fjern HTML-tagger og normaliser whitespace."""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def parse(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = f.read()

    temaer = re.findall(
        r'<div class="tema-section" id="tema-([^"]+)">(.*?)'
        r'(?=<div class="tema-section"|<script>)',
        raw,
        re.S,
    )
    if not temaer:
        sys.exit(f"Fant ingen tema-seksjoner i {path} — er formatet endret?")

    krav = []
    for tema, blokk in temaer:
        for del_ in re.split(r'<hr class="krav-divider"/>', blokk):
            kid = re.search(r'krav-id">([^<]+)', del_)
            if not kid:
                continue
            navn = re.search(r'krav-name">([^<]+)', del_)
            lov = re.search(r'krav-law" title="([^"]*)"', del_)
            sks = re.findall(
                r'sk-num">SK&nbsp;(\d+)</span><span class="sk-desc">(.*?)</span>',
                del_,
                re.S,
            )
            krav.append(
                {
                    "tema": tema,
                    "tema_navn": TEMA_NAVN.get(tema, tema),
                    "id": strip_tags(kid.group(1)),
                    "navn": strip_tags(navn.group(1)) if navn else "",
                    "lov": html.unescape(lov.group(1)) if lov else "",
                    "sks": [{"n": n, "d": strip_tags(d)} for n, d in sks],
                }
            )
    return krav


def vis(krav: list[dict], ider: list[str]) -> None:
    """Skriv ut suksesskriterier for gitte krav-IDer."""
    indeks = {k["id"]: k for k in krav}
    ukjent = [i for i in ider if i not in indeks]
    if ukjent:
        sys.exit(f"Ukjent krav-ID: {', '.join(ukjent)}")

    for kid in ider:
        k = indeks[kid]
        print(f"\n\033[1m{k['id']}\033[0m [{len(k['sks'])} SK] {k['navn']}")
        if k["lov"]:
            print(f"  \033[2m{k['lov']}\033[0m")
        for s in k["sks"]:
            print(f"   SK{s['n']}: {s['d']}")


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "--vis":
        krav = parse(KILDE_DEFAULT)
        if len(args) < 2:
            sys.exit("Bruk: --vis K154.1 [K255.1 ...]")
        vis(krav, args[1:])
        return

    kilde = Path(args[0]) if args else KILDE_DEFAULT
    maal = Path(args[1]) if len(args) > 1 else MAAL_DEFAULT

    krav = parse(kilde)
    with open(maal, "w", encoding="utf-8") as f:
        json.dump(krav, f, ensure_ascii=False, indent=1)
        f.write("\n")

    antall_sk = sum(len(k["sks"]) for k in krav)
    print(f"\033[1m{maal.name}\033[0m — {len(krav)} krav, {antall_sk} suksesskriterier\n")

    for tema, n in Counter(k["tema"] for k in krav).most_common():
        sk = sum(len(k["sks"]) for k in krav if k["tema"] == tema)
        print(f"  {TEMA_NAVN.get(tema, tema):38} {n:3} krav  {sk:4} SK")

    uten_sk = [k["id"] for k in krav if not k["sks"]]
    if uten_sk:
        print(f"\n  ⚠ Krav uten suksesskriterier: {', '.join(uten_sk)}")


if __name__ == "__main__":
    main()
