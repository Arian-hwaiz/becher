"""Becher Dashboard in zwei getrennten Bereichen.

    streamlit run dashboard/app.py                         # Nutzeransicht, http://localhost:8501
    streamlit run dashboard/admin.py --server.port 8502    # Admin-Bereich,  http://localhost:8502

Nutzeransicht: Treffer · Spiele · Quotenvergleich · Auswertung · FAQ.
Admin-Bereich: Anbieter & Scraper (Liste und Detailansicht je Anbieter) · Collector-Läufe.
Beide lesen direkt aus der Datenbank (DATABASE_URL aus .env). ``dashboard/admin.py`` setzt nur
BECHER_BEREICH=admin und führt diese Datei aus.
"""
from __future__ import annotations

import hmac
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit import config as _st_config

from common import db
from common.config import settings as _settings
from dashboard import queries as q
from engine import surebet as sb
from engine import account_health as ahmod
from engine import clv as clvmod
from engine import method_eval as memod

ADMIN = os.environ.get("BECHER_BEREICH", "nutzer") == "admin"   # gesetzt von dashboard/admin.py

st.set_page_config(page_title="Becher Admin" if ADMIN else "Becher", page_icon="🛠️" if ADMIN else "🍺",
                   layout="wide", initial_sidebar_state="auto")


def _reload_browser() -> None:
    """Seite im Browser neu laden. Streamlit übernimmt ein geändertes Farbschema erst beim Neuladen."""
    try:
        st.html("<script>window.location.reload()</script>", unsafe_allow_javascript=True)
    except TypeError:   # ältere Streamlit-Version ohne JavaScript in st.html
        import streamlit.components.v1 as _components

        _components.html("<script>window.parent.location.reload()</script>", height=0)


# Hell/Dunkel: die Wahl steht in der Datenbank (ui_settings) und gilt für beide Bereiche, auch nach einem Neustart.
try:
    with db.connect() as _conn:
        _saved_theme = q.get_ui_setting(_conn, "theme")
except Exception:  # noqa: BLE001  (Datenbank nicht erreichbar oder Schema älter: Standard verwenden)
    _saved_theme = None
THEME = _saved_theme if _saved_theme in ("light", "dark") else (_st_config.get_option("theme.base") or "light")
DARK = THEME == "dark"
if (_st_config.get_option("theme.base") or "light") != THEME:
    _st_config.set_option("theme.base", THEME)
    _reload_browser()
    st.stop()

_C = ({"card": "#1f1e1b", "line": "#3a3834", "dash": "#33312d", "meta": "#a3a09a", "value": "#4ade80", "arb": "#6ea8fe", "best": "#1e4d2b"}
      if DARK else
      {"card": "#fff", "line": "#e3e6ea", "dash": "#eee", "meta": "#6c757d", "value": "#1a7f37", "arb": "#0b5ed7", "best": "#d4edda"})

st.markdown(
    """
    <style>
    .opp {border:1px solid %(line)s; border-radius:8px; padding:10px 14px; margin-bottom:8px; background:%(card)s;}
    .opp .pct {font-size:1.6rem; font-weight:700; color:%(value)s;}
    .opp .pct.arb {color:%(arb)s;}
    .opp .meta {color:%(meta)s; font-size:0.85rem;}
    .meta {color:%(meta)s; font-size:0.85rem;}
    .st-key-themeswitch {position:fixed; top:0.75rem; right:1.25rem; z-index:1000001; width:auto !important;}
    .st-key-themeswitch label {margin-bottom:0;}
    .badge-admin {background:#b7791f; color:#fff; border-radius:6px; padding:2px 8px; font-size:0.8rem; font-weight:600;}
    .stMainBlockContainer {padding-top:4.5rem;}
    .opp .ev {font-size:1.05rem; font-weight:600;}
    .opp a.bk { text-decoration: none; } a.bk:hover { text-decoration: underline; }
.bk {font-weight:600;}
    .leg {display:flex; justify-content:space-between; padding:3px 0; border-top:1px dashed %(dash)s;}
    .leg .odd {font-weight:700; font-size:1.05rem;}
    </style>
    """ % _C,
    unsafe_allow_html=True,
)


def _save_theme() -> None:
    choice = "dark" if st.session_state["theme_dark"] else "light"
    try:
        with db.connect() as conn:
            q.set_ui_setting(conn, "theme", choice)
    except Exception:  # noqa: BLE001  (ohne Tabelle gilt die Wahl bis zum Neustart)
        pass
    _st_config.set_option("theme.base", choice)
    st.session_state["_theme_reload"] = True


with st.container(key="themeswitch"):
    st.toggle("🌙 Dunkel", value=DARK, key="theme_dark", on_change=_save_theme, help="Zwischen hellem und dunklem Farbschema wechseln")
if st.session_state.pop("_theme_reload", False):
    _reload_browser()
    st.stop()


@st.cache_data(ttl=15, show_spinner=False)
def _cached(name: str, *args):
    fn = getattr(q, name)
    with db.connect() as conn:
        return fn(conn, *args)


def load(fn, *args):
    return _cached(fn.__name__, *args)


def local_time(ts) -> pd.Timestamp:
    """Zeitpunkt in Wiener Zeit, für alle Anzeigen im Dashboard."""
    t = pd.Timestamp(ts)
    return (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert("Europe/Vienna")


def fmt_age(ts) -> str:
    if ts is None or pd.isna(ts):
        return "–"
    s = int((datetime.now(timezone.utc) - pd.Timestamp(ts).to_pydatetime()).total_seconds())
    if s < 90:
        return f"{s} Sek."
    if s < 5400:
        return f"{s // 60} Min."
    return f"{s // 3600} Std."


OUTCOME_LABEL = {"home": "1", "draw": "X", "away": "2", "over": "Über", "under": "Unter"}
MARKET_LABEL = {"h2h": "Sieger", "totals": "Über/Unter", "spreads": "Handicap"}


def bk_link(bid, name, event_id, urls: dict, links: dict) -> str:
    """Buchmachername als Link: Deep-Link zum Event, sonst Startseite, sonst nur Text."""
    url = links.get(bid) or urls.get(bid)
    if not url:
        return f"<span class='bk'>{name}</span>"
    return f"<a class='bk' href='{url}' target='_blank' title='{url}'>{name} ↗</a>"


def market_text(row) -> str:
    t = MARKET_LABEL.get(row["type"], row["type"])
    if row["line"] is not None and not pd.isna(row["line"]):
        t += f" ({row['line']})"
    return t


def outcome_text(row, outcome: str) -> str:
    lab = OUTCOME_LABEL.get(outcome, outcome)
    if row["type"] == "totals" and row["line"] is not None and not pd.isna(row["line"]):
        return f"{'TO' if outcome == 'over' else 'TU'}({row['line']})"
    if row["type"] == "spreads" and row["line"] is not None and not pd.isna(row["line"]):
        line = float(row["line"])
        return f"AH{lab}({line:+g})" if outcome == "home" else f"AH{lab}({-line:+g})"
    return lab


# ---------------------------------------------------------------- Menü

# Menüleiste oben, in Gruppen. Die Seitenleiste bleibt für die Filter der jeweiligen Seite frei.
# (Gruppe, Titel im Menü, interner Schlüssel, Adresse, Symbol)
MENU_NUTZER = [
    ("", "Treffer", "Scanner", "treffer", ":material/radar:"),
    ("", "Spiele", "Spiele", "spiele", ":material/sports_soccer:"),
    ("", "Quotenvergleich", "Quoten je Event", "quoten", ":material/compare_arrows:"),
    ("Auswertung", "Überblick", "Überblick", "ueberblick", ":material/monitoring:"),
    ("Auswertung", "Wetten & CLV", "Wetten", "wetten", ":material/receipt_long:"),
    ("Auswertung", "KI-Auswertung", "KI", "ki", ":material/psychology:"),
    ("Hilfe", "FAQ & Glossar", "FAQ", "faq", ":material/help:"),
]
# Admin-Bereich: eigene Adresse (Port 8502), eigenes Menü, getrennt von der Nutzeransicht
MENU_ADMIN = [
    ("", "Anbieter & Scraper", "Administration", "anbieter", ":material/settings:"),
    ("", "Collector-Läufe", "Collector-Läufe", "laeufe", ":material/history:"),
]
MENU = MENU_ADMIN if ADMIN else MENU_NUTZER


def _nothing() -> None:   # die Seiten werden unten in einer Kette gerendert; st.Page braucht nur ein Ziel
    return None


_nav: dict[str, list] = {}
for _group, _title, _key, _path, _icon in MENU:
    _nav.setdefault(_group, []).append(
        st.Page(_nothing, title=_title, icon=_icon, url_path=_path, default=(_key == MENU[0][2])))
st.logo(str(Path(__file__).parent / ("logo-admin.svg" if ADMIN else "logo.svg")), size="large")
_current = st.navigation(_nav, position="top")
_current.run()
page = next(k for _, t, k, _, _ in MENU if t == _current.title)

if ADMIN and _settings.admin_password and not st.session_state.get("admin_ok"):
    st.title("Becher Admin")
    with st.form("admin_login"):
        _pw = st.text_input("Passwort", type="password")
        if st.form_submit_button("Anmelden"):
            if hmac.compare_digest(_pw.encode(), _settings.admin_password.encode()):
                st.session_state["admin_ok"] = True
                st.rerun()
            st.error("Passwort stimmt nicht.")
    st.caption("Das Passwort steht als ADMIN_PASSWORD in der Datei .env.")
    st.stop()

try:
    summary = load(q.summary)
except Exception as exc:  # noqa: BLE001
    st.error(f"Keine Datenbankverbindung: {exc}")
    st.info("Datenbank starten mit `docker compose -f infra/docker-compose.yml up -d`, dann `python scripts/init_db.py`.")
    st.stop()

# ---------------------------------------------------------------- Scanner

if page == "Scanner":
    with st.sidebar:
        st.subheader("Filter")
        kinds = st.multiselect("Art", ["value", "arb"], default=["value", "arb"],
                               format_func=lambda k: {"value": "Valuebets", "arb": "Surebets"}[k])
        hours = st.select_slider("Zeitraum", options=[1, 3, 6, 12, 24, 72, 168], value=24,
                                 format_func=lambda h: f"{h} h" if h < 48 else f"{h // 24} Tage")
        min_pct = st.slider("Mindest-Prozent", 0.0, 15.0, 0.0, 0.25, help="Valuebets: konservativer EV · Surebets: Marge")
        max_age = st.slider("Max. Alter (Minuten)", 1, 1440, 120)
        sort_by = st.selectbox("Sortierung", ["Prozent", "Alter", "Anstoß"])
        stake = st.number_input("Gesamteinsatz (€)", min_value=1.0, value=100.0, step=10.0)
        auto = st.toggle("Automatisch aktualisieren (15 s)", value=False)
        if st.button("Jetzt neu laden"):
            _cached.clear()
            st.rerun()

    feed = load(q.latest_opportunities, hours, 500)
    sports_all = sorted(feed["sport"].dropna().unique().tolist()) if not feed.empty else []
    books_all = sorted(feed["bookmaker"].dropna().unique().tolist()) if not feed.empty else []
    with st.sidebar:
        sports = st.multiselect("Sportarten", sports_all, default=sports_all)
        books = st.multiselect("Buchmacher", books_all, default=books_all)

    if not feed.empty:
        feed = feed[feed["kind"].isin(kinds)]
        if sports:
            feed = feed[feed["sport"].isin(sports)]
        if books:
            feed = feed[feed["bookmaker"].isna() | feed["bookmaker"].isin(books)]
        feed = feed.assign(pct=feed["ev_conservative"].fillna(0) * 100)
        feed = feed[feed["pct"] >= min_pct]
        age_s = (datetime.now(timezone.utc) - pd.to_datetime(feed["found_at"], utc=True)).dt.total_seconds()
        feed = feed[age_s <= max_age * 60]
        if sort_by == "Prozent":
            feed = feed.sort_values("pct", ascending=False)
        elif sort_by == "Alter":
            feed = feed.sort_values("found_at", ascending=False)
        else:
            feed = feed.sort_values("start_time")

    head_l, head_r = st.columns([3, 2])
    head_l.title("Treffer")
    head_r.metric("Treffer", 0 if feed.empty else len(feed),
                  help="Letzter Collector-Lauf: " + (fmt_age(summary["last_run"]["started_at"]) + " her" if summary["last_run"] else "noch keiner"))

    if feed.empty:
        st.info("Keine Treffer für diese Filter. Collector und Scan laufen lassen: "
                "`python -m collectors.run` und `python scripts/scan.py`.")
    else:
        names = load(q.bookmaker_names)
        urls = load(q.bookmaker_urls)
        for _, r in feed.iterrows():
            pct = r["pct"]
            is_arb = r["kind"] == "arb"
            links = load(q.event_links, int(r["event_id"]))
            with st.container():
                c1, c2, c3 = st.columns([1.1, 4, 2.4])
                with c1:
                    st.markdown(f"<div class='opp'><div class='pct {'arb' if is_arb else ''}'>{pct:.2f} %</div>"
                                f"<div class='meta'>{'Surebet' if is_arb else 'Valuebet'}<br>{r['sport']}<br>{fmt_age(r['found_at'])}</div></div>",
                                unsafe_allow_html=True)
                with c2:
                    start = local_time(r["start_time"]).strftime("%d.%m. %H:%M")
                    html = (f"<div class='opp'><div><b>{r['home_name']} – {r['away_name']}</b> "
                            f"<span class='meta'>· {r['league']} · {start}</span></div>"
                            f"<div class='meta'>{market_text(r)}</div>")
                    if is_arb:
                        for leg in r["details"].get("legs", []):
                            html += (f"<div class='leg'><span>{bk_link(leg['bookmaker_id'], names.get(leg['bookmaker_id'], leg['bookmaker_id']), r['event_id'], urls, links)} "
                                     f"&nbsp; {outcome_text(r, leg['outcome'])}</span>"
                                     f"<span class='odd'>{leg['price']:.2f}</span></div>")
                    else:
                        html += (f"<div class='leg'><span>{bk_link(r['bookmaker_id'], r['bookmaker'], r['event_id'], urls, links)} &nbsp; {outcome_text(r, r['outcome'])}</span>"
                                 f"<span class='odd'>{float(r['price']):.2f}</span></div>"
                                 f"<div class='meta'>fair {float(r['fair_price']):.2f} · EV {float(r['ev']) * 100:.2f} % · "
                                 f"konservativ {pct:.2f} % · Referenz {r['details'].get('references', [''])[0] if r['details'] else ''} "
                                 f"vor {r['reference_age_s']} s · Methode {r['method']}</div>")
                    html += "</div>"
                    st.markdown(html, unsafe_allow_html=True)
                with c3:
                    if is_arb:
                        legs = r["details"].get("legs", [])
                        prices = [l["price_effective"] for l in legs]
                        sol = sb.simple(prices, [l["outcome"] for l in legs])
                        stakes = sol.stakes_for(stake)
                        lines = "".join(
                            f"<div class='leg'><span>{names.get(l['bookmaker_id'], '')} {outcome_text(r, l['outcome'])}</span>"
                            f"<span class='odd'>{s:.2f} €</span></div>" for l, s in zip(legs, stakes))
                        profit = stake * sol.percent / 100
                        st.markdown(f"<div class='opp'><div class='meta'>Einsätze bei {stake:.0f} € (nach Steuer/Kommission)</div>{lines}"
                                    f"<div class='ev'>Gewinn {profit:+.2f} €</div></div>", unsafe_allow_html=True)
                    else:
                        kelly = (r["details"] or {}).get("kelly_quarter", 0) or 0
                        q_eff = (r["details"] or {}).get("price_effective", float(r["price"]))
                        ev_eur = stake * float(r["ev"])
                        st.markdown(f"<div class='opp'><div class='meta'>Bei {stake:.0f} € Einsatz</div>"
                                    f"<div class='leg'><span>effektive Quote</span><span class='odd'>{q_eff:.3f}</span></div>"
                                    f"<div class='leg'><span>erwarteter Gewinn</span><span class='odd'>{ev_eur:+.2f} €</span></div>"
                                    f"<div class='leg'><span>Viertel-Kelly</span><span class='odd'>{kelly * 100:.1f} % der Bank</span></div></div>",
                                    unsafe_allow_html=True)
    if auto:
        import time
        time.sleep(15)
        _cached.clear()
        st.rerun()

# ---------------------------------------------------------------- Überblick

elif page == "Überblick":
    st.title("Überblick")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Kommende Events", summary["events_upcoming"])
    c2.metric("Quoten letzte Stunde", f"{summary['snapshots_1h']:,}".replace(",", "."))
    c3.metric("Aktive Buchmacher (1 h)", summary["bookmakers_1h"])
    c4.metric("Valuebets (24 h)", summary["values_24h"])
    c5.metric("Surebets (24 h)", summary["arbs_24h"])

    last = summary["last_run"]
    if last is None:
        st.warning("Noch kein Collector-Lauf. Starten mit `python -m collectors.run --once`.")
    else:
        state = "✅ ok" if last["ok"] else f"❌ Fehler: {last['error']}"
        st.caption(f"Letzter Lauf ({last['source']}) vor {fmt_age(last['started_at'])}: {last['events']} Events, "
                   f"{last['snapshots']} Quoten · {state}")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Quoten pro Stunde (letzte 48 h)")
        per_hour = load(q.snapshots_per_hour, 48)
        if per_hour.empty:
            st.info("Noch keine Quoten gespeichert.")
        else:
            fig = px.bar(per_hour, x="hour", y="n", color="source", labels={"hour": "", "n": "Quoten", "source": "Quelle"})
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), legend_title_text="")
            st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader("Buchmacher-Abdeckung (1 h)")
        cov = load(q.coverage, 60)
        if cov.empty:
            st.info("Keine Quoten in der letzten Stunde.")
        else:
            cov["zuletzt"] = cov["last_seen"].map(fmt_age)
            st.dataframe(cov[["name", "kind", "n", "zuletzt"]].rename(columns={"name": "Buchmacher", "kind": "Typ", "n": "Quoten"}),
                         hide_index=True, use_container_width=True, height=320)

    st.subheader("Treffer der letzten 24 h")
    opps = load(q.opportunities, 24, 300)
    if opps.empty:
        st.info("Noch keine Treffer. Scan starten mit `python scripts/scan.py`.")
    else:
        a, b = st.columns(2)
        with a:
            fig = px.histogram(opps, x=opps["ev_conservative"].fillna(0) * 100, color="kind", nbins=30,
                               labels={"x": "Prozent (konservativ)", "kind": "Art"})
            fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with b:
            per_bm = opps.dropna(subset=["bookmaker"]).groupby("bookmaker").size().reset_index(name="n").sort_values("n")
            if not per_bm.empty:
                fig2 = px.bar(per_bm, x="n", y="bookmaker", orientation="h", labels={"n": "Treffer", "bookmaker": ""})
                fig2.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig2, use_container_width=True)

# ---------------------------------------------------------------- Quoten je Event

elif page == "Spiele":
    st.title("Spiele")
    st.caption("Alle kommenden Spiele, für die Quoten vorliegen. Mit dem Filter „Anbieter“ siehst du, was ein einzelner Scraper geholt hat.")
    bks = load(q.bookmakers_with_events)
    if bks.empty:
        st.info("Noch keine Quoten für kommende Spiele. Starte einen Scraper, zum Beispiel "
                "`python -m collectors.run --once --only admiral --scan`.")
    else:
        choices = {"Alle Anbieter": None} | {f"{r['name']} ({int(r['events'])} Spiele)": int(r["id"]) for _, r in bks.iterrows()}
        wanted_bk = st.query_params.get("anbieter") or ""   # von „Anbieter & Scraper“: /spiele?anbieter=<id>
        start = next((i for i, v in enumerate(choices.values()) if wanted_bk.isdigit() and v == int(wanted_bk)), 0)
        f1, f2, f3 = st.columns([2, 3, 2])
        bk_label = f1.selectbox("Anbieter", list(choices), index=start)
        bid = choices[bk_label]
        games = load(q.events_overview, bid)
        leagues = sorted(games["league"].unique())
        pick_leagues = f2.multiselect("Liga", leagues, placeholder="alle Ligen")
        text = f3.text_input("Suche", placeholder="Mannschaft …").strip().lower()
        if pick_leagues:
            games = games[games["league"].isin(pick_leagues)]
        if text:
            games = games[(games["home_name"].str.lower().str.contains(text, regex=False))
                          | (games["away_name"].str.lower().str.contains(text, regex=False))]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Spiele", len(games))
        m2.metric("Quoten", int(games["quotes"].sum()) if len(games) else 0)
        m3.metric("Ligen", games["league"].nunique())
        m4.metric("Letzter Abruf", fmt_age(games["last_seen"].max()) if len(games) else "–")

        if games.empty:
            st.info("Keine Spiele für diese Auswahl.")
        else:
            local = games["start_time"].dt.tz_convert("Europe/Vienna")

            def _odds(price_col: str, name_col: str) -> list[str]:
                """Quote als Text; in der Gesamtansicht mit dem Anbieter, der sie bietet."""
                return ["–" if pd.isna(v) else (f"{v:.2f}" if bid is not None else f"{v:.2f}  {n}")
                        for v, n in zip(games[price_col], games[name_col])]

            table = pd.DataFrame({
                "Anstoß": local.dt.weekday.map(dict(enumerate(["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]))) + local.dt.strftime(" %d.%m. %H:%M"),
                "Liga": games["league"],
                "Spiel": games["home_name"] + " – " + games["away_name"],
                "1": _odds("p1", "b1"), "X": _odds("px", "bx"), "2": _odds("p2", "b2"),
                "Auszahlung %": games["payout"],
                "Märkte": games["markets"], "Quoten": games["quotes"],
                "Abruf": games["last_seen"].map(fmt_age),
            })
            if bid is None:
                table["Anbieter"] = games["n_bookmakers"].astype(str) + ": " + games["bookmakers"]
            else:
                table["weitere Anbieter"] = (games["n_bookmakers"] - 1).clip(lower=0)
                table["Beim Anbieter"] = games["link"]
            table["Vergleich"] = "/quoten?event=" + games["id"].astype(str)
            st.dataframe(
                table, hide_index=True, use_container_width=True, height=min(38 * (len(table) + 1) + 4, 900),
                column_config={
                    "Auszahlung %": st.column_config.NumberColumn(
                        "Auszahlung %", format="%.2f",
                        help="Was die gezeigten 1X2-Quoten zusammen auszahlen. Über 100 = mögliche Surebet, darunter liegt die Marge."),
                    "Beim Anbieter": st.column_config.LinkColumn("Beim Anbieter", display_text="zum Spiel ↗"),
                    "Vergleich": st.column_config.LinkColumn("Vergleich", display_text="Quoten vergleichen"),
                    "Anbieter": st.column_config.TextColumn("Anbieter", width="large"),
                })
            if bid is None:
                over = games[games["payout"] > 100]
                if len(over):
                    st.success(f"{len(over)} Spiele mit Auszahlung über 100 % (mögliche Surebet): "
                               + ", ".join((over["home_name"] + " – " + over["away_name"]).head(5)))
            st.caption(("1 / X / 2 sind die Quoten dieses Anbieters, die Auszahlung zeigt seine Marge." if bid is not None
                        else "1 / X / 2 sind die jeweils besten Quoten über alle Anbieter, daneben steht, wer sie bietet. "
                             "Die Auszahlung vergleicht diese besten Quoten: über 100 % wäre eine mögliche Surebet.")
                       + " Zeiten in Wiener Zeit. „Quoten vergleichen“ öffnet das Spiel im Quotenvergleich.")

elif page == "Quoten je Event":
    st.title("Quotenvergleich")
    events = load(q.upcoming_events, 200)
    if events.empty:
        st.info("Keine kommenden Events.")
    else:
        events["label"] = events.apply(lambda r: f"{local_time(r['start_time']):%d.%m. %H:%M}  {r['home_name']} – {r['away_name']}  ({r['league']})", axis=1)
        labels = events["label"].tolist()
        wanted = st.query_params.get("event")   # von der Seite „Spiele“: /quoten?event=<id>
        start = 0
        if wanted and wanted.isdigit() and int(wanted) in set(events["id"]):
            start = int(events.index[events["id"] == int(wanted)][0])
        pick = st.selectbox("Event", labels, index=start)
        ev = events[events["label"] == pick].iloc[0]
        markets = load(q.event_markets, int(ev["id"]))
        ev_links = load(q.event_links, int(ev["id"]))
        bk_urls = load(q.bookmaker_urls)
        bk_names = load(q.bookmaker_names)
        present = set(load(q.event_bookmakers, int(ev["id"])))
        link_ids = sorted((set(ev_links) | set(bk_urls)) & present, key=lambda i: (i not in ev_links, bk_names.get(i, "")))
        if link_ids:
            st.markdown("Zum Buchmacher: " + " · ".join(
                bk_link(i, bk_names.get(i, str(i)), int(ev["id"]), bk_urls, ev_links) for i in link_ids if i in ev_links)
                + ("" if not ev_links else "  \n") + "<span class='meta'>Startseiten: " + " · ".join(
                bk_link(i, bk_names.get(i, str(i)), int(ev["id"]), bk_urls, {}) for i in link_ids if i not in ev_links) + "</span>",
                unsafe_allow_html=True)
        if markets.empty:
            st.info("Keine Märkte für dieses Event.")
        for _, m in markets.iterrows():
            title = MARKET_LABEL.get(m["type"], m["type"])
            if m["line"] is not None and not pd.isna(m["line"]):
                title += f" {m['line']}"
            st.subheader(title)
            table = load(q.market_latest_odds, int(m["id"]))
            if table.empty:
                st.caption("keine Quoten")
                continue
            piv = table.pivot_table(index="bookmaker", columns="outcome", values="price", aggfunc="first")
            order = [c for c in ["home", "draw", "away", "over", "under"] if c in piv.columns]
            piv = piv[order].rename(columns=OUTCOME_LABEL)
            best = piv.max()
            st.dataframe(piv.style.highlight_max(axis=0, color=_C["best"]).format("{:.2f}"), use_container_width=True)
            inv = sum(1 / v for v in best if pd.notna(v))
            st.caption(f"Beste Quoten: Auszahlung {100 / inv:.2f} %  ·  Marge {(1 / inv - 1) * 100:+.2f} %")
            hist = load(q.market_history, int(m["id"]), 72)
            if not hist.empty and hist["observed_at"].nunique() > 1:
                fig = px.line(hist, x="observed_at", y="price", color="bookmaker", line_dash="outcome",
                              labels={"observed_at": "", "price": "Quote", "bookmaker": "Buchmacher", "outcome": "Ausgang"})
                fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- Wetten (Phase 5)

elif page == "Wetten":
    st.title("Eigene Wetten & CLV")
    st.caption("Wetten hier erfassen. Schlussquoten und CLV berechnet `python scripts/closing.py` (oder der Collector mit `--scan`) nach Anpfiff.")
    stats = load(q.bet_stats)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Wetten", int(stats["n"] or 0))
    c2.metric("Gewinn (abgerechnet)", f"{float(stats['profit'] or 0):+.2f}")
    c3.metric("Ø CLV", f"{float(stats['clv']):+.2f} %" if stats["clv"] is not None else "–",
              help="Closing Line Value: eigene Quote gegenüber fairer Schlussquote der Referenz")
    n_clv = int(stats["n_clv"] or 0)
    c4.metric("CLV positiv", f"{int(stats['clv_pos'] or 0)}/{n_clv}" + (f" ({int(stats['clv_pos'] or 0) / n_clv * 100:.0f} %)" if n_clv else ""))

    names = load(q.bookmaker_names)
    with st.expander("Neue Wette erfassen", expanded=stats["n"] == 0):
        events = load(q.upcoming_events, 300)
        ev_opts = {"– ohne Event –": None}
        ev_opts.update({f"{local_time(r.start_time):%d.%m. %H:%M}  {r.home_name} – {r.away_name}": int(r.id) for r in events.itertuples()})
        f1, f2 = st.columns(2)
        ev_label = f1.selectbox("Event", list(ev_opts))
        event_id = ev_opts[ev_label]
        market_id = None
        if event_id is not None:
            mk = load(q.event_markets, event_id)
            mk_opts = {market_text(r): int(r["id"]) for _, r in mk.iterrows()} if not mk.empty else {}
            market_id = mk_opts[f2.selectbox("Markt", list(mk_opts))] if mk_opts else None
        else:
            f2.selectbox("Markt", ["– zuerst Event wählen –"], disabled=True)
        with st.form("bet_form"):
            g1, g2, g3, g4 = st.columns(4)
            bm_name = g1.selectbox("Buchmacher", sorted(names.values()))
            outcome = g2.selectbox("Ausgang", ["home", "draw", "away", "over", "under"])
            price = g3.number_input("Quote", min_value=1.01, value=2.00, step=0.01, format="%.3f")
            stake = g4.number_input("Einsatz", min_value=0.0, value=10.0, step=1.0)
            h1, h2 = st.columns([1, 3])
            fair = h1.number_input("Faire Quote beim Setzen (optional)", min_value=0.0, value=0.0, step=0.01, format="%.3f")
            note = h2.text_input("Notiz")
            if st.form_submit_button("Wette speichern", type="primary"):
                bm_id = next(k for k, v in names.items() if v == bm_name)
                with db.connect() as conn:
                    bet_id = q.add_bet(conn, bm_id, outcome, float(stake), float(price), market_id,
                                       float(fair) if fair > 0 else None, note)
                st.cache_data.clear()
                st.success(f"Wette #{bet_id} gespeichert.")
                st.rerun()

    bets_df = load(q.bets, 500)
    if bets_df.empty:
        st.info("Noch keine Wetten erfasst.")
    else:
        bets_df["event"] = bets_df.apply(lambda r: f"{r.home_name} – {r.away_name}" if isinstance(r.home_name, str) else "–", axis=1)
        bets_df["markt"] = bets_df.apply(lambda r: market_text(r) if isinstance(r.type, str) else "–", axis=1)
        bets_df["gewinn"] = bets_df.apply(lambda r: (float(r.payout or 0) - float(r.stake)) if r.result != "open" else None, axis=1)
        st.subheader("Wetten")
        st.dataframe(bets_df[["id", "placed_at", "event", "markt", "bookmaker", "outcome", "price", "stake",
                              "fair_price_at_bet", "result", "gewinn", "clv", "note"]]
                     .rename(columns={"placed_at": "gesetzt", "bookmaker": "Buchmacher", "outcome": "Ausgang",
                                      "price": "Quote", "stake": "Einsatz", "fair_price_at_bet": "fair", "result": "Ergebnis",
                                      "clv": "CLV %"}),
                     hide_index=True, use_container_width=True,
                     column_config={"CLV %": st.column_config.NumberColumn(format="%+.2f"),
                                    "gewinn": st.column_config.NumberColumn(format="%+.2f")})

        open_bets = bets_df[bets_df["result"] == "open"]
        if not open_bets.empty:
            st.subheader("Wette abrechnen")
            s1, s2, s3 = st.columns([3, 2, 1])
            opts = {f"#{r.id} {r.event} · {r.bookmaker} {r.outcome} @ {float(r.price):.3f}": int(r.id) for r in open_bets.itertuples()}
            sel = s1.selectbox("Offene Wette", list(opts))
            res = s2.selectbox("Ergebnis", ["won", "lost", "void", "half_won", "half_lost"])
            if s3.button("Abrechnen"):
                bet_id = opts[sel]
                row = open_bets[open_bets["id"] == bet_id].iloc[0]
                payout = clvmod.settle(float(row.stake), float(row.price), res)
                with db.connect() as conn:
                    q.settle_bet(conn, bet_id, res, round(payout, 2))
                st.cache_data.clear()
                st.rerun()

        by_bm = load(q.clv_by_bookmaker)
        if not by_bm.empty and by_bm["clv"].notna().any():
            st.subheader("CLV je Buchmacher")
            fig = px.bar(by_bm.dropna(subset=["clv"]), x="bookmaker", y="clv", text="n_clv",
                         labels={"bookmaker": "", "clv": "Ø CLV %", "n_clv": "Wetten"})
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        st.subheader("Konto-Risiko je Buchmacher")
        st.caption("Heuristik: wie auffällig das Wettverhalten für den Buchmacher wirkt (Limitgefahr). 0 = unauffällig, 100 = akut.")
        with db.connect() as conn:
            health = ahmod.evaluate(conn)
            mscores = memod.evaluate(conn)
        hcols = st.columns(min(len(health), 4) or 1)
        for i, h in enumerate(health):
            with hcols[i % len(hcols)]:
                st.metric(h.bookmaker, f"{h.score} ({h.level})", help=f"{h.bets} Wetten · Ø CLV {h.avg_clv:+.2f} %" if h.avg_clv is not None else f"{h.bets} Wetten")
                for r in h.reasons:
                    st.caption(f"• {r}")
                for t in h.tips:
                    st.caption(f"💡 {t}")
        if mscores:
            st.subheader("Devig-Methode je Markt (an abgerechneten Wetten)")
            st.caption("Brier und Log-Loss: je kleiner, desto besser trifft die Methode die Schlusslinie. Empfehlung erst ab 30 Wetten je Markt.")
            mdf = pd.DataFrame([{"Markt": m.market_type, "Methode": m.method, "Wetten": m.n, "Brier": round(m.brier, 4),
                                 "Log-Loss": round(m.logloss, 4), "Ø CLV %": round(m.avg_clv, 2), "Empfehlung": "✅" if m.recommended else ""}
                                for m in mscores])
            st.dataframe(mdf, hide_index=True, use_container_width=True)
        settled = bets_df.dropna(subset=["clv"]).sort_values("placed_at")
        if len(settled) >= 2:
            st.subheader("CLV-Verlauf (kumuliert)")
            settled["clv_kum"] = settled["clv"].astype(float).cumsum()
            fig = px.line(settled, x="placed_at", y="clv_kum", labels={"placed_at": "", "clv_kum": "Σ CLV %"})
            fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------- KI (Phase 6)

elif page == "KI":
    import json as _json

    from common.config import settings as _settings
    from engine import ai as _ai

    st.title("KI-Auswertung")
    st.caption(f"Modell {_settings.ai_model}, Denktiefe {_settings.ai_effort}. Die KI rechnet nichts neu, sie ordnet die Zahlen von Becher ein.")
    if not _settings.anthropic_api_key:
        st.warning("`ANTHROPIC_API_KEY` fehlt in `.env`. Kontext ansehen geht trotzdem, Auswertungen kosten API-Guthaben und brauchen den Schlüssel.")
    k1, k2, k3 = st.columns([1, 1, 2])
    hours = k3.slider("Zeitfenster (Stunden)", 6, 24 * 14, 24, step=6)
    do_assess = k1.button("Treffer einordnen", type="primary", disabled=not _settings.anthropic_api_key)
    do_weekly = k2.button("Wochenbericht", disabled=not _settings.anthropic_api_key)
    if do_assess or do_weekly:
        with st.spinner("Claude denkt nach …"):
            try:
                with db.connect() as conn:
                    ctx = _ai.build_context(conn, hours=hours)
                    if do_assess:
                        result, resp = _ai.assess_opportunities(ctx)
                        _ai.save_report(conn, "assessment", result.model_dump_json(), resp, hours)
                    else:
                        text, resp = _ai.weekly_report(ctx)
                        _ai.save_report(conn, "weekly", text, resp, hours)
                st.cache_data.clear()
                st.success(f"Fertig ({resp.usage.input_tokens} Eingabe-, {resp.usage.output_tokens} Ausgabe-Tokens).")
            except _ai.AIRefused as exc:
                st.error(f"Das Modell hat die Anfrage abgelehnt: {exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"KI-Aufruf fehlgeschlagen: {exc}")
    with st.expander("Kontext ansehen (das bekommt die KI)"):
        with db.connect() as conn:
            st.json(_ai.build_context(conn, hours=hours), expanded=False)

    reports = load(q.ai_reports, 50)
    if reports.empty:
        st.info("Noch keine Auswertungen.")
    else:
        st.subheader("Auswertungen")
        for _, r in reports.iterrows():
            label = f"{local_time(r['created_at']):%d.%m. %H:%M} · {'Treffer-Einordnung' if r['kind'] == 'assessment' else 'Wochenbericht'} · {r['context_hours']} h"
            with st.expander(label, expanded=bool(_ == 0)):
                if r["kind"] == "assessment":
                    try:
                        a = _json.loads(r["content"])
                    except ValueError:
                        st.text(r["content"])
                        continue
                    st.write(a.get("summary", ""))
                    for p in sorted(a.get("picks", []), key=lambda p: p.get("priority", 9)):
                        st.markdown(f"**[{p['priority']}] {p['event']}** · {p['bookmaker']} · {p['market']} {p['outcome']}  \n{p['reason']}"
                                    + "".join(f"  \n⚠ {x}" for x in p.get("risks", [])))
                    for w in a.get("warnings", []):
                        st.warning(w)
                    for sgg in a.get("suggested_settings", []):
                        st.info(sgg)
                else:
                    st.markdown(r["content"])
                st.caption(f"{r['model']} · {r['input_tokens']} / {r['output_tokens']} Tokens")

# ---------------------------------------------------------------- Administration

elif page == "Administration":
    with db.connect() as conn:
        adm = q.admin_bookmakers(conn)
        cols_df = q.admin_collectors(conn, _settings.active_collectors)

    STATE_ICON = {"frisch": "🟢 liefert", "alt": "🟡 älter als 6 h", "veraltet": "🔴 älter als 48 h", "keine": "⚪ keine Daten"}
    KIND = {"sharp": "Referenz", "exchange": "Börse", "soft": "Buchmacher"}
    _user_url = _settings.dashboard_url.rstrip("/")

    # ---------- Detailansicht eines Anbieters: /?id=<id> im Admin-Bereich
    _pick = st.query_params.get("id", "")
    if _pick.isdigit() and int(_pick) in set(adm["id"]):
        b = adm.set_index("id").loc[int(_pick)]
        bid = int(_pick)
        with db.connect() as conn:
            run_sources = q.bookmaker_run_sources(conn, bid)
            b_runs = q.source_runs(conn, run_sources, 30)
            b_leagues = q.bookmaker_leagues(conn, bid)
            b_markets = q.bookmaker_markets(conn, bid)
            b_keys = q.bookmaker_source_keys(conn, bid)
            b_hours = q.bookmaker_quotes_per_hour(conn, bid, 48)
        own_runs = b_runs[b_runs["source"] == b["key"]] if not b_runs.empty else b_runs
        icon, sentence = q.bookmaker_health(b, own_runs if not own_runs.empty else None)

        n1, n2 = st.columns([1.2, 6])
        if n1.button("← Alle Anbieter"):
            del st.query_params["id"]
            st.rerun()
        names = dict(zip(adm["id"], adm["name"]))
        other = n2.selectbox("Anbieter wechseln", list(names), index=list(names).index(bid), format_func=names.get, label_visibility="collapsed")
        if other != bid:
            st.query_params["id"] = str(other)
            st.rerun()

        st.title(f"{icon} {b['name']}")
        st.markdown(f"**{sentence}**" + ("" if b["is_active"] else "  \nDer Anbieter ist **inaktiv**: Er wird weiter gesammelt, aber vom Scan ignoriert."))
        if isinstance(b["scraper_note"], str) and b["scraper_note"]:
            st.caption(f"Notiz: {b['scraper_note']}")

        d1, d2, d3, d4, d5, d6 = st.columns(6)
        d1.metric("Scraper-Stand", q.SCRAPER_STATUS.get(b["scraper_status"], b["scraper_status"]).split(" (")[0])
        d2.metric("Letzte Quote", fmt_age(b["last_seen"]))
        d3.metric("Spiele (kommend)", int(b_leagues["events"].sum()) if not b_leagues.empty else 0)
        d4.metric("Quoten aktuell", int(b_leagues["quotes"].sum()) if not b_leagues.empty else 0)
        d5.metric("Quoten 24 h", int(b["quotes_24h"]))
        day = own_runs[own_runs["started_at"] > pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24)] if not own_runs.empty else own_runs
        d6.metric("Läufe 24 h (ok / alle)", f"{int(day['ok'].fillna(False).sum())} / {len(day)}" if len(day) else "–")

        if not own_runs.empty and own_runs.iloc[0]["ok"] is False:
            st.error(f"Letzter Lauf fehlgeschlagen ({fmt_age(own_runs.iloc[0]['started_at'])}): {str(own_runs.iloc[0]['error'])[:400]}")

        left, right = st.columns([2, 3])
        with left:
            st.subheader("Einstellungen")
            with st.form(f"bk_{bid}"):
                f_on = st.toggle("aktiv (im Scan berücksichtigen)", value=bool(b["is_active"]))
                f_stat = st.selectbox("Scraper-Stand", list(q.SCRAPER_STATUS), index=list(q.SCRAPER_STATUS).index(b["scraper_status"]),
                                      format_func=q.SCRAPER_STATUS.get)
                f_note = st.text_area("Notiz", value=b["scraper_note"] if isinstance(b["scraper_note"], str) else "", height=90)
                if st.form_submit_button("Speichern", type="primary"):
                    with db.connect() as conn:
                        q.set_bookmaker_active(conn, bid, f_on)
                        q.set_bookmaker_scraper(conn, bid, f_stat, f_note)
                    st.cache_data.clear()
                    st.toast(f"{b['name']} gespeichert")
                    st.rerun()
            own = cols_df[cols_df["source"] == b["key"]]
            if not own.empty:
                _ck = f"detail_col_{b['key']}"

                def _save_own(source=b["key"], key=_ck) -> None:
                    with db.connect() as conn:
                        q.set_collector_enabled(conn, source, bool(st.session_state[key]))

                st.session_state[_ck] = bool(own.iloc[0]["enabled"])
                st.toggle(f"Scraper „{b['key']}“ im Dauerbetrieb mitlaufen lassen", key=_ck, on_change=_save_own,
                          help="Aus = wird im Dauerbetrieb übersprungen. Gilt ab dem nächsten Durchlauf.")
            st.subheader("Stammdaten")
            facts = {
                "Typ": KIND.get(b["kind"], b["kind"]),
                "Land": b["country"] or "–",
                "Schlüssel": b["key"],
                "Steuer": f"{b['tax_rate'] * 100:.1f} %",
                "Daten kommen über": b["live_sources"] if isinstance(b["live_sources"], str) else "–",
                "Zugeordnete Quellen": ", ".join(f"{r.source}: {r.source_key}" for r in b_keys.itertuples()) or "–",
            }
            st.markdown("\n".join(f"- **{k}:** {v}" for k, v in facts.items()))
            links = []
            if isinstance(b["url"], str) and b["url"]:
                links.append(f"[Seite des Anbieters ↗]({b['url']})")
            links.append(f"[Alle Spiele dieses Anbieters ↗]({_user_url}/spiele?anbieter={bid})")
            st.markdown(" · ".join(links))

        with right:
            st.subheader("Was der Scraper holt")
            if b_leagues.empty:
                st.info("Für kommende Spiele liegen von diesem Anbieter keine Quoten vor.")
            else:
                st.dataframe(pd.DataFrame({
                    "Liga": b_leagues["league"], "Spiele": b_leagues["events"], "Quoten": b_leagues["quotes"],
                    "von": b_leagues["first_start"].map(lambda t: f"{local_time(t):%d.%m.}"),
                    "bis": b_leagues["last_start"].map(lambda t: f"{local_time(t):%d.%m.}"),
                    "Abruf": b_leagues["last_seen"].map(fmt_age),
                }), hide_index=True, use_container_width=True)
                st.dataframe(pd.DataFrame({
                    "Markt": b_markets["type"].map(lambda t: MARKET_LABEL.get(t, t)), "Linien": b_markets["lines"].fillna("–"),
                    "Spiele": b_markets["events"], "Quoten": b_markets["quotes"],
                }), hide_index=True, use_container_width=True)
            if not b_hours.empty:
                fig = px.bar(b_hours, x="hour", y="quotes", color="source", labels={"hour": "", "quotes": "Quoten je Stunde", "source": "Quelle"})
                fig.update_layout(height=230, margin=dict(l=10, r=10, t=10, b=10), template="plotly_dark" if DARK else "plotly_white")
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("Letzte Läufe")
        if b_runs.empty:
            st.info("Für diesen Anbieter gibt es noch keine Läufe." if b["scraper_status"] != "blockiert"
                    else "Keine Läufe, der Anbieter ist blockiert.")
        else:
            st.dataframe(pd.DataFrame({
                "Start": b_runs["started_at"].map(lambda t: f"{local_time(t):%d.%m. %H:%M:%S}"),
                "Quelle": b_runs["source"],
                "Ergebnis": b_runs["ok"].map(lambda v: "🟢 ok" if v is True else ("🔴 Fehler" if v is False else "⏳ läuft")),
                "Spiele": b_runs["events"], "Quoten": b_runs["snapshots"],
                "Dauer (s)": (b_runs["finished_at"] - b_runs["started_at"]).dt.total_seconds().round(1),
                "Fehler": b_runs["error"].fillna(""),
            }), hide_index=True, use_container_width=True)
            if any(src != b["key"] for src in b_runs["source"]):
                st.caption("Quellen, die nicht wie der Anbieter heißen, sind Sammelquellen, die mehrere Anbieter auf einmal liefern.")
        st.stop()

    st.title("Anbieter & Scraper")
    st.caption("Alle Anbieter mit Datenlage und Scraper-Stand. „Details“ öffnet die Ansicht eines Anbieters. Inaktive Anbieter werden weiter "
               "gesammelt, aber vom Scan ignoriert. Änderungen in der Tabelle werden sofort gespeichert.")
    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Anbieter", len(adm))
    a2.metric("aktiv", int(adm["is_active"].sum()) if not adm.empty else 0)
    a3.metric("liefern Daten", int((adm["data_state"] == "frisch").sum()) if not adm.empty else 0)
    a4.metric("eigener Scraper läuft", int((adm["scraper_status"] == "laeuft").sum()) if not adm.empty else 0)
    a5.metric("To-do (offen / in Arbeit)", int(adm["scraper_status"].isin(["offen", "in_arbeit"]).sum()) if not adm.empty else 0)

    st.subheader("Anbieter")
    _names = dict(zip(adm["id"], adm["name"]))
    _open = st.selectbox("Anbieter im Detail öffnen", [None] + list(_names), format_func=lambda i: "Anbieter wählen …" if i is None else _names[i])
    if _open is not None:
        st.query_params["id"] = str(_open)
        st.rerun()
    f1, f2, f3 = st.columns([2, 2, 2])
    f_status = f1.multiselect("Scraper-Stand", list(q.SCRAPER_STATUS), format_func=q.SCRAPER_STATUS.get)
    f_data = f2.multiselect("Datenlage", list(STATE_ICON), format_func=STATE_ICON.get)
    f_active = f3.radio("Anzeigen", ["alle", "nur aktive", "nur inaktive"], horizontal=True)
    view = adm.copy()
    if f_status:
        view = view[view["scraper_status"].isin(f_status)]
    if f_data:
        view = view[view["data_state"].isin(f_data)]
    if f_active != "alle":
        view = view[view["is_active"] == (f_active == "nur aktive")]

    if view.empty:
        st.info("Keine Anbieter für diese Auswahl.")
    else:
        show = pd.DataFrame({
            "id": view["id"],
            "aktiv": view["is_active"].astype(bool),
            "Anbieter": view["name"],
            "Details": ["/?id=" + str(i) for i in view["id"]],
            "Typ": view["kind"].map(KIND),
            "Daten": view["data_state"].map(STATE_ICON),
            "zuletzt": view["last_seen"].map(fmt_age),
            "Quoten 24 h": view["quotes_24h"].astype(int),
            "liefert über": view["live_sources"].fillna("–"),
            "zugeordnet": view["sources"].fillna("–"),
            "Scraper": view["scraper_status"],
            "Notiz": view["scraper_note"].fillna(""),
            "Seite": view["url"],
            "Spiele": [f"{_user_url}/spiele?anbieter={i}" for i in view["id"]],
        }).set_index("id")
        edited = st.data_editor(
            show, key="admin_bookmakers", use_container_width=True, hide_index=True, height=min(38 * (len(show) + 1) + 4, 900),
            disabled=["Anbieter", "Typ", "Daten", "zuletzt", "Quoten 24 h", "liefert über", "zugeordnet", "Seite", "Spiele", "Details"],
            column_config={
                "aktiv": st.column_config.CheckboxColumn("aktiv", help="aus = vom Scan ignoriert"),
                "Scraper": st.column_config.SelectboxColumn("Scraper", options=list(q.SCRAPER_STATUS), required=True,
                                                             help="offen · in_arbeit · laeuft · blockiert (Bot-Schutz) · nicht_moeglich · nicht_noetig (kommt über API)"),
                "Notiz": st.column_config.TextColumn("Notiz", width="large"),
                "Details": st.column_config.LinkColumn("Details", display_text="öffnen", help="Status, Läufe und Abdeckung dieses Anbieters"),
                "Seite": st.column_config.LinkColumn("Seite", display_text="öffnen ↗"),
                "Spiele": st.column_config.LinkColumn("Spiele", display_text="Liste", help="Alle Spiele dieses Anbieters"),
            })
        edited["Notiz"] = edited["Notiz"].fillna("").astype(str)
        changed = edited[(edited["aktiv"] != show["aktiv"]) | (edited["Scraper"] != show["Scraper"]) | (edited["Notiz"] != show["Notiz"])]
        if not changed.empty:
            with db.connect() as conn:
                for bid, row in changed.iterrows():
                    q.set_bookmaker_active(conn, int(bid), bool(row["aktiv"]))
                    q.set_bookmaker_scraper(conn, int(bid), row["Scraper"], row["Notiz"])
            st.cache_data.clear()
            st.session_state.pop("admin_bookmakers", None)
            st.toast(f"{len(changed)} Anbieter gespeichert")
            st.rerun()

    b1, b2 = st.columns([2, 5])
    if b1.button("Nur Anbieter mit Daten aktiv lassen", help="Aktiviert alle, die in den letzten 48 h Quoten geliefert haben, und deaktiviert den Rest"):
        with db.connect() as conn:
            n_on, n_off = q.activate_only_with_data(conn)
        st.cache_data.clear()
        st.toast(f"{n_on} aktiv, {n_off} inaktiv.")
        st.rerun()
    b2.caption("Legende Scraper: " + " · ".join(f"{k} = {v}" for k, v in q.SCRAPER_STATUS.items()))

    st.subheader("Collector (Quellen)")
    st.caption("Ein ausgeschalteter Collector wird im Dauerbetrieb übersprungen. Mit `--only <name>` läuft er trotzdem.")
    if cols_df.empty:
        st.info("Noch keine Collector bekannt.")
    for _, c in cols_df.iterrows():
        k1, k2, k3, k4 = st.columns([1.6, 1.4, 3, 3])
        state = "⚪ noch kein Lauf" if pd.isna(c["last_run"]) else ("🟢 ok" if c["last_ok"] else "🔴 Fehler")
        _key = f"col_{c['source']}"

        def _save_collector(source=c["source"], key=_key) -> None:
            with db.connect() as conn:
                q.set_collector_enabled(conn, source, bool(st.session_state[key]))

        st.session_state[_key] = bool(c["enabled"])   # die Datenbank gilt, auch bei Änderung von außen
        k1.toggle(c["source"], key=_key, on_change=_save_collector)
        k2.write(state)
        k3.caption(f"letzter Lauf {fmt_age(c['last_run'])} · {0 if pd.isna(c['last_snapshots']) else int(c['last_snapshots'])} Quoten · "
                   f"24 h: {int(c['ok_24h'])}/{int(c['runs_24h'])} ok")
        if isinstance(c["last_error"], str) and c["last_error"] and not c["last_ok"]:
            k4.caption(f"Fehler: {c['last_error'][:160]}")

# ---------------------------------------------------------------- Collector-Läufe

elif page == "Collector-Läufe":
    st.title("Collector-Läufe")
    runs = load(q.runs, 200)
    if runs.empty:
        st.info("Noch keine Läufe.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Läufe", len(runs))
        c2.metric("Erfolgsquote", f"{runs['ok'].mean() * 100:.0f} %")
        c3.metric("Ø Quoten je Lauf", f"{runs['snapshots'].mean():.0f}")
        fig = px.scatter(runs, x="started_at", y="snapshots", color="ok", symbol="source",
                         labels={"started_at": "", "snapshots": "Quoten", "ok": "ok"})
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
        runs["dauer_s"] = (runs["finished_at"] - runs["started_at"]).dt.total_seconds().round(1)
        st.dataframe(runs[["started_at", "source", "ok", "events", "snapshots", "dauer_s", "error"]],
                     hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- FAQ

elif page == "FAQ":
    from dashboard import faq as _faq

    st.title("FAQ und Glossar")
    st.caption("Begriffe, Abkürzungen und Rechenwege, die in Becher vorkommen.")
    term = st.text_input("Suchen", placeholder="z. B. Valuebet, AH1, CLV, Marge …")
    hits = _faq.search(term)
    if not hits:
        st.info("Kein Eintrag gefunden.")
    for cat in _faq.CATEGORIES:
        entries = [e for e in hits if e[0] == cat]
        if not entries:
            continue
        st.subheader(cat)
        for _, title, text in entries:
            with st.expander(title, expanded=bool(term)):
                st.markdown(text)
