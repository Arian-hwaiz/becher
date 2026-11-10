"""Wettsteuer je Buchmacher auf das eigene Land einstellen.

    python scripts/set_tax.py --show            # aktuelle Einstellung anzeigen
    python scripts/set_tax.py --country OHNE    # Rohquoten vergleichen, keine Steuer (Standard)
    python scripts/set_tax.py --country AT      # Österreich: dem Spieler wird nichts abgezogen → Steuer 0
    python scripts/set_tax.py --country DE      # Deutschland: 5,3 % vom Einsatz bei Buchmachern mit deutscher Lizenz

Die Steuer steht in der Tabelle ``bookmakers`` (tax_rate, tax_mode) und geht in jede EV- und
Surebet-Rechnung ein. Einzelne Buchmacher lassen sich danach von Hand anpassen, z. B.
``UPDATE bookmakers SET tax_rate = 0.05, tax_mode = 'on_winnings' WHERE key = 'tipico';``
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

from common import db

# Buchmacher, die in Deutschland mit deutscher Lizenz anbieten und die 5,3 % an den Spieler weitergeben
GERMAN_TAXED = ("bet365", "tipico", "bwin", "betano", "unibet", "winamax", "admiral", "interwetten", "betathome")

PROFILES = {
    "OHNE": "Rohquoten ohne Steuer (Standard: Becher vergleicht Quoten, gewettet wird nicht)",
    "AT": "Österreich: Wettgebühr trägt der Buchmacher, kein Abzug beim Spieler",
    "DE": "Deutschland: 5,3 % vom Einsatz bei Buchmachern mit deutscher Lizenz",
}


def apply_country(conn, country: str) -> int:
    """Setzt die Steuer für alle Buchmacher. Gibt die Anzahl besteuerter Buchmacher zurück."""
    country = country.upper()
    if country not in PROFILES:
        raise ValueError(f"unbekanntes Land {country!r}, möglich: {', '.join(PROFILES)}")
    conn.execute("UPDATE bookmakers SET tax_rate = 0, tax_mode = 'none'")
    if country == "DE":
        cur = conn.execute(
            "UPDATE bookmakers SET tax_rate = 0.053, tax_mode = 'on_stake' WHERE key = ANY(%s) AND kind = 'soft'",
            (list(GERMAN_TAXED),))
        return cur.rowcount
    return 0


def show(conn) -> None:
    rows = conn.execute("SELECT name, kind, tax_rate, tax_mode, commission FROM bookmakers ORDER BY kind, name").fetchall()
    for r in rows:
        tax = f"{float(r['tax_rate']) * 100:.1f} % ({r['tax_mode']})" if float(r["tax_rate"]) else "keine Steuer"
        com = f", Kommission {float(r['commission']) * 100:.0f} %" if float(r["commission"]) else ""
        print(f"  {r['name']:<20} {r['kind']:<9} {tax}{com}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", choices=sorted(PROFILES), type=str.upper)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    with db.connect() as conn:
        if args.country:
            n = apply_country(conn, args.country)
            print(f"{PROFILES[args.country]} → {n} Buchmacher mit Steuer. Danach neu scannen: python scripts/scan.py")
        show(conn)


if __name__ == "__main__":
    main()
