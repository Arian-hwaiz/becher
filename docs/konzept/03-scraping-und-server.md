# Datenerhebung bei Buchmachern und Server

Stand: 9. November 2026 · Schätzwerte, nicht aktuell geprüft

> Überholt in Teilen (10. 11. 2026): Odds-API, Hetzner-Server und Proxies sind durch den lokalen Betrieb ersetzt, siehe [07-gesamtplan-unabhaengiger-kern.md](07-gesamtplan-unabhaengiger-kern.md).

Für den Start reicht ein einziger Server. Die eigentlichen Kosten und Mühen stecken in Proxies und in der Wartung der Scraper.

## Wie man an die Quoten kommt

Man scrapt nicht das HTML. Fast jede Buchmacher-Seite lädt ihre Quoten im Hintergrund als JSON nach, live meist per WebSocket.

So findet man die Endpunkte: Seite in Chrome öffnen, F12, Reiter "Network", nach "Fetch/XHR" bzw. "WS" filtern, ein Spiel anklicken. Diese Endpunkte fragt ein Collector (ein kleines Programm pro Buchmacher) direkt ab.

- **Prematch:** Abfrage alle 30–120 Sekunden, je nach Wichtigkeit
- **Live:** dauerhafte WebSocket-Verbindung, sonst zu langsam
- **Manche Buchmacher** brauchen einen echten Browser (Playwright), weil sie Tokens erzeugen. Das kostet viel mehr Rechenleistung.
- **Mobile-Apps** haben oft eigene, stabilere APIs.

## Server

- **Start:** ein Dedicated Server bei Hetzner (Deutschland/Finnland), 8–16 Kerne, 64 GB RAM, ca. 50–100 € im Monat. Darauf laufen Collector, Redis, Datenbank und Engine. Für 20–30 Buchmacher im Prematch reicht das gut.
- **Später für Live:** Collector auf mehrere kleine Server verteilen, Datenbank und Engine getrennt. Standort EU, nah an den Buchmachern.

## Engpässe

- **Proxies:** Buchmacher sperren Rechenzentrums-IPs und zeigen je nach Land andere Quoten. Nötig sind Proxies mit IPs aus dem jeweiligen Land (z. B. deutsche für deutsche Anbieter). Oft der größte laufende Posten: grob 100 bis mehrere hundert Euro im Monat.
- **Wartung:** Die Seiten ändern sich ständig. Pro Buchmacher regelmäßigen Reparaturaufwand einplanen; Monitoring pro Collector, das meldet, wenn keine Daten mehr kommen.
- **Rechtlich:** Scraping verstößt meist gegen die AGB der Buchmacher. Vor dem Start prüfen lassen.

## Empfehlung

Mit einer gekauften Odds-API starten und eigene Collector nur für die 3–5 Buchmacher bauen, die dort fehlen oder zu langsam sind.
