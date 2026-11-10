import importlib.util
import os
from pathlib import Path

import pytest

URL = os.environ.get("BECHER_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="BECHER_TEST_DATABASE_URL nicht gesetzt")

spec = importlib.util.spec_from_file_location("set_tax", Path(__file__).parent.parent / "scripts" / "set_tax.py")
set_tax = importlib.util.module_from_spec(spec)
spec.loader.exec_module(set_tax)


def test_country_profiles_switch_tax():
    from common import db

    with db.connect(URL) as conn:
        db.apply_schema(conn)
        before = {r["key"]: (r["tax_rate"], r["tax_mode"]) for r in conn.execute("SELECT key, tax_rate, tax_mode FROM bookmakers").fetchall()}
        try:
            assert set_tax.apply_country(conn, "AT") == 0
            assert conn.execute("SELECT count(*) AS n FROM bookmakers WHERE tax_rate <> 0").fetchone()["n"] == 0
            assert set_tax.apply_country(conn, "de") >= 3
            row = conn.execute("SELECT tax_rate, tax_mode FROM bookmakers WHERE key='tipico'").fetchone()
            assert float(row["tax_rate"]) == 0.053 and row["tax_mode"] == "on_stake"
            assert float(conn.execute("SELECT tax_rate FROM bookmakers WHERE key='pinnacle'").fetchone()["tax_rate"]) == 0
            with pytest.raises(ValueError):
                set_tax.apply_country(conn, "XX")
        finally:
            for key, (rate, mode) in before.items():
                conn.execute("UPDATE bookmakers SET tax_rate=%s, tax_mode=%s WHERE key=%s", (rate, mode, key))
