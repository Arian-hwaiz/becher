"""Becher Dashboard: Scanner-Ansicht wie bei Betburger plus Überblick.

    streamlit run dashboard/app.py

Liest direkt aus der Datenbank (DATABASE_URL aus .env). Seiten:
Scanner (Treffer-Feed mit Filtern und Einsatzrechner) · Überblick · Quoten je Event · Collector-Läufe.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

import pandas as pd
import plotly.express as px
import streamlit as st

from common import db
from dashboard import queries as q
from engine import surebet as sb
from engine import account_health as ahmod
from engine import clv as clvmod
from engine import method_eval as memod

st.set_page_config(page_title="Becher", page_icon="🍺", layout="wide")

st.markdown(
    """
    <style>
    .opp {border:1px solid #e3e6ea; border-radius:8px; padding:10px 14px; margin-bottom:8px; background:#fff;}
    .opp .pct {font-size:1.6rem; font-weight:700; color:#1a7f37;}
    .opp .pct.arb {color:#0b5ed7;}
    .opp .meta {color:#6c757d; font-size:0.85rem;}
    .opp .ev {font-size:1.05rem; font-weight:600;}
    .opp a.bk { text-decoration: none; } a.bk:hover { text-decoration: underline; }
.bk {font-weight:600;}
    .leg {display:flex; justify-content:space-between; padding:3px 0; border-top:1px dashed #eee;}
    .leg .odd {font-weight:700; font-size:1.05rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=15, show_spinner=False)
def _cached(name: str, *args):
    fn = getattr(q, name)
    with db.connect() as conn:
        return fn(conn, *args)


def load(fn, *args):
    return _cached(fn.__name__, *args)


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


# ---------------------------------------------------------------- Sidebar

st.sidebar.title("🍺 Becher")
page = st.sidebar.radio("Seite", ["Scanner", "Überblick", "Quoten je Event", "Wetten", "KI", "Collector-Läufe"], label_visibility="collapsed")

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
    head_l.title("Scanner")
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
                    start = pd.Timestamp(r["start_time"]).strftime("%d.%m. %H:%M")
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

elif page == "Quoten je Event":
    st.title("Quoten je Event")
    events = load(q.upcoming_events, 200)
    if events.empty:
        st.info("Keine kommenden Events.")
    else:
        events["label"] = events.apply(lambda r: f"{r['start_time']:%d.%m %H:%M}  {r['home_name']} – {r['away_name']}  ({r['league']})", axis=1)
        pick = st.selectbox("Event", events["label"].tolist())
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
            st.dataframe(piv.style.highlight_max(axis=0, color="#d4edda").format("{:.2f}"), use_container_width=True)
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
        ev_opts.update({f"{r.start_time:%d.%m. %H:%M}  {r.home_name} – {r.away_name}": int(r.id) for r in events.itertuples()})
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
            label = f"{r['created_at']:%d.%m. %H:%M} · {'Treffer-Einordnung' if r['kind'] == 'assessment' else 'Wochenbericht'} · {r['context_hours']} h"
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
