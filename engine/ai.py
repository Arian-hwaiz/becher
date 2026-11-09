"""KI-Schicht (Phase 6): Treffer erklären und priorisieren, Wochenbericht, Auswertung.

Die KI rechnet nicht selbst. Sie bekommt die Zahlen, die Becher bereits berechnet hat
(Treffer, Referenzen, eigene Wetten, CLV je Buchmacher und Markt, Zustand der Collector),
und liefert Einordnung, Prioritäten und Hinweise in verständlichem Deutsch.

* ``build_context``: liest alles Nötige aus der Datenbank in ein JSON-fähiges Dict (ohne KI).
* ``clv_by_market_type``: deterministische Auswertung CLV je Markttyp (ohne KI).
* ``assess_opportunities``: Claude ordnet die aktuellen Treffer ein (strukturierte Antwort).
* ``weekly_report``: Claude schreibt einen Wochenbericht (Markdown).
* ``save_report``: legt jede Antwort samt Tokenverbrauch in ``ai_reports`` ab.

Modell: ``AI_MODEL`` in .env (Standard claude-opus-5-5), Denktiefe ``AI_EFFORT`` (Standard medium).
Lehnt das Modell eine Anfrage ab (stop_reason "refusal"), springt serverseitig ein Ersatzmodell ein
(``fallbacks="default"``); bleibt es bei der Ablehnung, wirft ``assess_opportunities`` einen ``AIRefused``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from common.config import settings

log = logging.getLogger(__name__)

SYSTEM = """Du bist der Analyst des privaten Quoten-Scanners „Becher“. Du bekommst Zahlen, die Becher
bereits berechnet hat: Valuebets (EV nach deutscher Wettsteuer, konservativer EV mit Unsicherheitsband,
faire Quote aus scharfen Referenzen wie Pinnacle oder der Betfair-Börse), Surebets, eigene Wetten mit
CLV (Closing Line Value) sowie den Zustand der Datensammlung.

Regeln:
- Rechne die Kennzahlen nicht neu, sondern ordne sie ein. Wenn Zahlen fehlen oder alt sind, sag das.
- Positiver CLV über viele Wetten ist der einzige belastbare Beleg für eine Kante; kurzfristiger Gewinn nicht.
- Achte auf Risiken: alte Referenzquoten, dünne Liquidität, nur eine Referenz, sehr hohe Prozente (oft Fehlerquoten,
  Limitgefahr beim Buchmacher), Märkte kurz vor Anpfiff, auffällig viele Treffer bei einem Buchmacher.
- Schreibe Deutsch, knapp, konkret, ohne Floskeln. Keine Wettempfehlung als Garantie formulieren."""


class AIRefused(RuntimeError):
    """Das Modell hat die Anfrage abgelehnt (stop_reason refusal), auch nach Fallback."""


# ---------------------------------------------------------------- Kontext (ohne KI)

def clv_by_market_type(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT m.type, count(*) AS n, avg(b.clv) AS clv, count(b.clv) AS n_clv,
                  coalesce(sum(coalesce(b.payout, 0) - b.stake) FILTER (WHERE b.result <> 'open'), 0) AS profit
           FROM bets b JOIN markets m ON m.id = b.market_id GROUP BY m.type ORDER BY n DESC"""
    ).fetchall()
    return [{"market": r["type"], "bets": r["n"], "avg_clv": _f(r["clv"]), "with_clv": r["n_clv"], "profit": _f(r["profit"])}
            for r in rows]


def build_context(conn, hours: int = 24, max_opportunities: int = 40, now: datetime | None = None) -> dict[str, Any]:
    """Alles, was die KI braucht, als JSON-fähiges Dict."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    opps = conn.execute(
        """SELECT DISTINCT ON (o.market_id, o.bookmaker_id, o.outcome, o.kind)
                  o.found_at, o.kind, o.outcome, o.price, o.fair_price, o.ev, o.ev_conservative, o.method,
                  o.reference_age_s, o.details, k.name AS bookmaker, k.kind AS bookmaker_kind,
                  e.home_name, e.away_name, e.start_time, l.name AS league, s.name AS sport, m.type, m.line
           FROM opportunities o JOIN markets m ON m.id = o.market_id JOIN events e ON e.id = m.event_id
           JOIN leagues l ON l.id = e.league_id JOIN sports s ON s.id = l.sport_id
           LEFT JOIN bookmakers k ON k.id = o.bookmaker_id
           WHERE o.found_at >= %s AND e.start_time > %s
           ORDER BY o.market_id, o.bookmaker_id, o.outcome, o.kind, o.found_at DESC""",
        (since, now),
    ).fetchall()
    opps = sorted(opps, key=lambda r: float(r["ev_conservative"] or 0), reverse=True)[:max_opportunities]
    bets = conn.execute(
        """SELECT b.placed_at, k.name AS bookmaker, b.outcome, b.stake, b.price, b.fair_price_at_bet, b.result, b.payout, b.clv,
                  e.home_name, e.away_name, m.type
           FROM bets b JOIN bookmakers k ON k.id = b.bookmaker_id
           LEFT JOIN markets m ON m.id = b.market_id LEFT JOIN events e ON e.id = m.event_id
           ORDER BY b.placed_at DESC LIMIT 200"""
    ).fetchall()
    by_bm = conn.execute(
        """SELECT k.name, count(*) AS n, avg(b.clv) AS clv, count(b.clv) AS n_clv,
                  coalesce(sum(coalesce(b.payout, 0) - b.stake) FILTER (WHERE b.result <> 'open'), 0) AS profit
           FROM bets b JOIN bookmakers k ON k.id = b.bookmaker_id GROUP BY k.name ORDER BY n DESC"""
    ).fetchall()
    runs = conn.execute(
        """SELECT source, count(*) AS n, sum(CASE WHEN ok THEN 1 ELSE 0 END) AS ok, max(finished_at) AS last,
                  avg(snapshots) AS snapshots
           FROM collector_runs WHERE started_at >= %s GROUP BY source""",
        (since,),
    ).fetchall()
    coverage = conn.execute(
        """SELECT k.name, k.kind, count(*) AS n, max(o.observed_at) AS last_seen
           FROM odds_snapshots o JOIN bookmakers k ON k.id = o.bookmaker_id
           WHERE o.observed_at >= %s GROUP BY k.name, k.kind ORDER BY n DESC""",
        (since,),
    ).fetchall()
    return {
        "generated_at": now.isoformat(timespec="minutes"),
        "window_hours": hours,
        "opportunities": [
            {
                "found_at": _ts(r["found_at"]), "kind": r["kind"], "sport": r["sport"], "league": r["league"],
                "event": f"{r['home_name']} – {r['away_name']}", "start_time": _ts(r["start_time"]),
                "market": r["type"] + (f" {r['line']}" if r["line"] is not None else ""),
                "bookmaker": r["bookmaker"], "outcome": r["outcome"], "price": _f(r["price"]), "fair_price": _f(r["fair_price"]),
                "ev_pct": _pct(r["ev"]), "ev_conservative_pct": _pct(r["ev_conservative"]), "method": r["method"],
                "reference_age_s": r["reference_age_s"],
                "references": (r["details"] or {}).get("references"), "legs": (r["details"] or {}).get("legs"),
                "arb_pct": (r["details"] or {}).get("percent"),
            }
            for r in opps
        ],
        "bets": [
            {"placed_at": _ts(r["placed_at"]), "event": f"{r['home_name']} – {r['away_name']}" if r["home_name"] else None,
             "market": r["type"], "bookmaker": r["bookmaker"], "outcome": r["outcome"], "stake": _f(r["stake"]),
             "price": _f(r["price"]), "fair_price_at_bet": _f(r["fair_price_at_bet"]), "result": r["result"],
             "payout": _f(r["payout"]), "clv_pct": _f(r["clv"])}
            for r in bets
        ],
        "clv_by_bookmaker": [{"bookmaker": r["name"], "bets": r["n"], "avg_clv": _f(r["clv"]), "with_clv": r["n_clv"], "profit": _f(r["profit"])}
                             for r in by_bm],
        "clv_by_market": clv_by_market_type(conn),
        "collectors": [{"source": r["source"], "runs": r["n"], "ok": r["ok"], "last": _ts(r["last"]), "avg_snapshots": _f(r["snapshots"])}
                       for r in runs],
        "coverage": [{"bookmaker": r["name"], "kind": r["kind"], "snapshots": r["n"], "last_seen": _ts(r["last_seen"])} for r in coverage],
    }


def _f(x) -> float | None:
    return None if x is None else round(float(x), 4)


def _pct(x) -> float | None:
    return None if x is None else round(float(x) * 100, 2)


def _ts(x) -> str | None:
    return None if x is None else x.isoformat(timespec="minutes")


# ---------------------------------------------------------------- Strukturierte Antworten

class Pick(BaseModel):
    event: str = Field(description="Spiel wie im Kontext")
    bookmaker: str
    market: str
    outcome: str
    priority: int = Field(ge=1, le=5, description="1 = zuerst anschauen, 5 = eher lassen")
    reason: str = Field(description="Ein bis zwei Sätze, warum")
    risks: list[str] = Field(default_factory=list, description="konkrete Risiken, leer wenn keine")


class Assessment(BaseModel):
    summary: str = Field(description="Drei bis fünf Sätze Gesamtbild")
    picks: list[Pick]
    warnings: list[str] = Field(default_factory=list, description="Auffälligkeiten an Daten oder Collectoren")
    suggested_settings: list[str] = Field(default_factory=list, description="konkrete Vorschläge für Schwellen/Filter, optional")


# ---------------------------------------------------------------- Aufrufe

def _client():
    import anthropic  # erst hier, damit der Rest ohne das Paket läuft

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY fehlt in .env")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _ask(prompt: str, output_schema: dict | None = None, client=None, max_tokens: int = 8000):
    """Eine Anfrage an Claude. Gibt (Text, Antwortobjekt) zurück."""
    client = client or _client()
    kwargs: dict[str, Any] = {}
    if output_schema is not None:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": output_schema}, "effort": settings.ai_effort}
    else:
        kwargs["output_config"] = {"effort": settings.ai_effort}
    resp = client.beta.messages.create(
        model=settings.ai_model,
        max_tokens=max_tokens,
        system=SYSTEM,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    if resp.stop_reason == "refusal":
        raise AIRefused(getattr(getattr(resp, "stop_details", None), "explanation", "") or "abgelehnt")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return text, resp


def _schema(model: type[BaseModel]) -> dict:
    s = model.model_json_schema()
    _strict(s)
    return s


def _strict(node: Any) -> None:
    """additionalProperties=false und alle Felder required, wie die API es für json_schema verlangt."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for v in node.values():
            _strict(v)
    elif isinstance(node, list):
        for v in node:
            _strict(v)


def assess_opportunities(context: dict[str, Any], client=None) -> tuple[Assessment, Any]:
    """Claude priorisiert die aktuellen Treffer. Gibt (Assessment, Antwortobjekt) zurück."""
    prompt = ("Ordne die aktuellen Treffer ein und priorisiere sie. Berücksichtige den bisherigen CLV je Buchmacher "
              "und Markt sowie den Zustand der Collector. Antworte nur mit dem geforderten JSON.\n\n"
              f"Kontext (JSON):\n{json.dumps(context, ensure_ascii=False)}")
    text, resp = _ask(prompt, _schema(Assessment), client)
    return Assessment.model_validate_json(text), resp


def weekly_report(context: dict[str, Any], client=None) -> tuple[str, Any]:
    """Claude schreibt den Wochenbericht als Markdown."""
    prompt = ("Schreibe den Wochenbericht für Becher als Markdown mit den Abschnitten: Gesamtbild, Eigene Wetten und CLV "
              "(je Buchmacher und Markt), Auffällige Treffer, Datenqualität und Collector, Empfehlungen für nächste Woche. "
              "Höchstens 500 Wörter. Nenne Zahlen aus dem Kontext, erfinde keine.\n\n"
              f"Kontext (JSON):\n{json.dumps(context, ensure_ascii=False)}")
    return _ask(prompt, None, client)


def save_report(conn, kind: str, content: str, resp: Any, context_hours: int) -> int:
    usage = getattr(resp, "usage", None)
    row = conn.execute(
        """INSERT INTO ai_reports (kind, model, context_hours, input_tokens, output_tokens, content)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (kind, getattr(resp, "model", settings.ai_model), context_hours,
         getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None), content),
    ).fetchone()
    return row["id"]
