# engine – Rechenkern

- `surebet.py`: generischer Löser für Surebets und Middles über eine Auszahlungsmatrix. Ersetzt die 21 Formeltypen von Betburger (siehe `docs/konzept/06`). Enthält Steuer- und Kommissionsumrechnung (`effective_price`), Lay→Back (`lay_to_back`), Handicap- und Totals-Szenarien inkl. Viertellinien (`handicap`, `total`).
- geplant (Phase 3): `devig.py` (multiplikativ, Power, Shin), `valuebet.py` (EV nach Steuer, Referenz-Alter, Konfidenz), `kelly.py`.

Beispiel:

```python
from engine import surebet as sb
sb.simple([2.10, 2.10]).percent        # 5.0  (% Marge)
sb.total(2.0, 2.5, 2.0, 3.5)           # Middle: percent 0.0, max_percent 100.0
sb.effective_price(2.0, tax_rate=0.053, tax_mode="on_stake")   # 1.894
```
