# Kostenkonzept

Stand: 9. November 2026 · gehört zu [01-betburger-analyse-und-konzept.md](01-betburger-analyse-und-konzept.md)

Baust du selbst, kostet das erste Jahr etwa **38.000 bis 89.000 €**. Mit externen Entwicklern sind es etwa **130.000 bis 230.000 €**. Die größten Posten sind Quoten-Daten und Marketing; die Server selbst sind günstig. Alle Werte sind Schätzungen aus Erfahrungswerten, keine Angebote, und gelten netto.

## Laufende Kosten pro Monat

| Posten | Phase 0: Validieren | Phase 1: MVP | Phase 2: Live + Schutz | Phase 3: Skalieren |
| --- | --- | --- | --- | --- |
| Server (Hetzner) | 0–20 € | 60–100 € | 250–400 € | 600–1.000 € |
| Odds-API | 0–100 € | 200–600 € | 500–1.500 € | 1.000–3.000 € |
| Proxies (Länder-IPs) | 0 € | 50–150 € | 200–500 € | 500–1.000 € |
| Tools (Domain, E-Mail, Monitoring) | 20 € | 50–100 € | 100–200 € | 100–200 € |
| Marketing | 0 € | 200–500 € | 1.000–2.000 € | 2.000–5.000 € |
| Steuerberater | 0 € | 100–300 € | 100–300 € | 200–300 € |
| **Summe pro Monat** | **20–140 €** | **660–1.750 €** | **2.150–4.900 €** | **4.400–10.500 €** |

Zahlungsgebühren kommen dazu: bei einem Merchant of Record wie Paddle etwa 5 % vom Umsatz.

## Einmalkosten

| Posten | Wann | Kosten |
| --- | --- | --- |
| Betfair Live-App-Key (privat) | Phase 0 | ca. 350 €; für ein kommerzielles Produkt ist eine Vendor-Lizenz nötig, Preis anfragen |
| Test-Bankroll für eigene Wetten | Phase 0 | 1.000–3.000 € (Kapital, das zurückkommt oder verloren geht, kein Verbrauch) |
| Firmengründung (UG oder GmbH, Notar, Register) | Phase 1 | 500–1.000 € (GmbH zusätzlich 12.500 € eingezahltes Stammkapital) |
| Rechtsberatung (Werbung, Affiliate, Scraping) | Phase 1 | 1.000–1.500 € |
| AGB, Datenschutz, Impressum | Phase 1 | 1.000–3.000 € |

## Summe pro Phase

| Phase | Dauer | Selbst gebaut | Mit Freelancern (ca. 80 €/h) |
| --- | --- | --- | --- |
| Phase 0: Validieren | 3 Wochen | 400–500 € + Bankroll | 400–500 € + Bankroll (Prototyp baust du selbst) |
| Phase 1: MVP | 3 Monate | 4.500–10.800 € | + 32.000–48.000 € (400–600 h) |
| Phase 2: Live + Schutz | 3 Monate | 6.500–14.700 € | + 32.000–48.000 € (400–600 h) |
| Phase 3: Skalieren | 6 Monate | 26.400–63.000 € | + 29.000–48.000 € (60–100 h pro Monat) |
| **Erstes Jahr** | **ca. 12,5 Monate** | **ca. 38.000–89.000 €** | **ca. 130.000–230.000 €** |

## Ab wann es sich trägt

Bei einem durchschnittlichen Abo-Umsatz von etwa 80 € pro zahlendem Nutzer (Mischung aus den Preisstufen) brauchst du zur Kostendeckung:

- **Phase 1:** etwa 10–25 zahlende Nutzer
- **Phase 2:** etwa 30–65 zahlende Nutzer
- **Phase 3:** etwa 60–140 zahlende Nutzer

Entwicklerkosten sind hier nicht eingerechnet. Mit Freelancern verschiebt sich der Break-even um mehrere Monate.

## Wo man sparen kann

- Phase 0 und 1 komplett selbst bauen (mit KI-Unterstützung realistisch) und Freelancer nur für einzelne Collector oder das Frontend holen.
- Marketing in Phase 1 fast nur über kostenlose Rechner-Seiten (SEO), Telegram-Gruppen und Foren.
- Odds-API mit kleinem Paket und wenigen Buchmachern starten; Live-Daten erst ab Phase 2 kaufen.
- Erst eine UG gründen (ab 1 € Stammkapital) statt einer GmbH.

**Offen:** echte Angebote von 2–3 Odds-API-Anbietern und die Betfair-Vendor-Lizenz. Diese beiden Posten können die Rechnung am stärksten verschieben.
