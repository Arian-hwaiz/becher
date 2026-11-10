"""Becher Admin-Bereich: getrennt von der Nutzeransicht, eigene Adresse.

    streamlit run dashboard/admin.py --server.port 8502     # http://localhost:8502

Zeigt Anbieter & Scraper (Liste und Detailansicht je Anbieter) und die Collector-Läufe.
Optionaler Passwortschutz: ADMIN_PASSWORD in .env setzen.
Die Seiten selbst stehen in dashboard/app.py; diese Datei schaltet nur den Bereich um.
"""
import os
import runpy
from pathlib import Path

os.environ["BECHER_BEREICH"] = "admin"
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
