"""Telegram-Benachrichtigung bei neuen Treffern.

Bot anlegen: in Telegram @BotFather → /newbot → Token in .env (TELEGRAM_BOT_TOKEN).
Chat-ID: dem Bot eine Nachricht schicken, dann https://api.telegram.org/bot<TOKEN>/getUpdates
aufrufen und ``chat.id`` in .env (TELEGRAM_CHAT_ID) eintragen.

``format_opportunity`` ist eine reine Funktion (testbar), ``send`` schickt den Text.
``notify_new`` verschickt Treffer oberhalb einer Schwelle und merkt sich, was schon gemeldet
wurde (im Speicher je Prozess; nach Neustart wird höchstens einmal doppelt gemeldet).
"""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

from common.config import settings
from engine.scan import Opportunity

log = logging.getLogger(__name__)

_sent: set[str] = set()


def _key(o: Opportunity) -> str:
    return f"{o.kind}|{o.market_id}|{o.bookmaker_id}|{o.outcome}"


def format_opportunity(o: Opportunity, names: dict[int, str], event: dict | None = None) -> str:
    """Kurztext für Telegram (HTML)."""
    head = ""
    if event:
        head = f"<b>{event.get('home_name')} – {event.get('away_name')}</b>\n{event.get('league', '')} · {event.get('start_time')}\n"
    market = (event or {}).get("market", "")
    if o.kind == "value":
        pct = (o.ev_conservative or 0) * 100
        return (f"💰 <b>Valuebet {pct:.2f} %</b>\n{head}{market}\n"
                f"{names.get(o.bookmaker_id, o.bookmaker_id)}: <b>{o.outcome} @ {o.price}</b> · fair {o.fair_price}\n"
                f"EV {(o.ev or 0) * 100:.2f} % · Referenz vor {o.reference_age_s} s · {o.method}")
    legs = "\n".join(f"  {names.get(l['bookmaker_id'], l['bookmaker_id'])}: {l['outcome']} @ {l['price']} (Einsatz {l['stake'] * 100:.1f} %)"
                     for l in o.details.get("legs", []))
    return f"🔒 <b>Surebet {o.details.get('percent', 0):.2f} %</b>\n{head}{market}\n{legs}"


def send(text: str, token: str | None = None, chat_id: str | None = None, client: httpx.Client | None = None) -> bool:
    token = token or settings.telegram_bot_token
    chat_id = chat_id or settings.telegram_chat_id
    if not token or not chat_id:
        log.debug("Telegram nicht konfiguriert, Nachricht verworfen")
        return False
    c = client or httpx.Client(timeout=15)
    r = c.post(f"https://api.telegram.org/bot{token}/sendMessage",
               json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    if r.status_code != 200:
        log.warning("Telegram-Fehler %s: %s", r.status_code, r.text[:200])
        return False
    return True


def notify_new(conn, found: Iterable[Opportunity], min_percent: float = 1.0) -> int:
    """Meldet neue Treffer mit konservativem Prozent ≥ min_percent. Gibt Anzahl gesendeter Nachrichten zurück."""
    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        return 0
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM bookmakers").fetchall()}
    sent = 0
    for o in found:
        pct = (o.ev_conservative or 0) * 100
        if pct < min_percent or _key(o) in _sent:
            continue
        ev = conn.execute(
            """SELECT e.home_name, e.away_name, e.start_time, l.name AS league, m.type, m.line
               FROM markets m JOIN events e ON e.id = m.event_id JOIN leagues l ON l.id = e.league_id WHERE m.id=%s""",
            (o.market_id,),
        ).fetchone()
        info = dict(ev) if ev else None
        if info:
            info["market"] = info["type"] + (f" {info['line']}" if info.get("line") is not None else "")
            info["start_time"] = info["start_time"].strftime("%d.%m. %H:%M")
        if send(format_opportunity(o, names, info)):
            _sent.add(_key(o))
            sent += 1
    return sent
