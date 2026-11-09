"""Spielt infra/schema.sql in die Datenbank ein (idempotent).

    python scripts/init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

import logging

from common import db


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with db.connect() as conn:
        db.apply_schema(conn)
        n = conn.execute("SELECT count(*) AS n FROM bookmakers").fetchone()["n"]
    logging.info("Schema eingespielt, %d Buchmacher angelegt.", n)


if __name__ == "__main__":
    main()
