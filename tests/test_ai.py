import json
import os
from types import SimpleNamespace

import pytest

from engine import ai

URL = os.environ.get("BECHER_TEST_DATABASE_URL")


class FakeMessages:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, model=kwargs["model"],
                               content=[SimpleNamespace(type="text", text=self.text)],
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
                               stop_details=SimpleNamespace(explanation="nein") if self.stop_reason == "refusal" else None)


def fake_client(text, stop_reason="end_turn"):
    m = FakeMessages(text, stop_reason)
    return SimpleNamespace(beta=SimpleNamespace(messages=m)), m


def test_schema_is_strict_and_complete():
    s = ai._schema(ai.Assessment)
    assert s["additionalProperties"] is False
    assert set(s["required"]) == set(s["properties"])
    pick = s["$defs"]["Pick"]
    assert pick["additionalProperties"] is False and "risks" in pick["required"]


def test_assess_parses_structured_answer_and_sends_schema():
    answer = {"summary": "Ruhiger Tag.", "warnings": ["Betfair-Collector seit 3 h ohne Lauf"],
              "suggested_settings": [],
              "picks": [{"event": "A – B", "bookmaker": "Tipico", "market": "h2h", "outcome": "home",
                         "priority": 1, "reason": "3 % konservativ, zwei frische Referenzen.", "risks": []}]}
    client, m = fake_client(json.dumps(answer))
    result, resp = ai.assess_opportunities({"opportunities": []}, client)
    assert result.picks[0].priority == 1 and result.warnings
    call = m.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in call["betas"]
    assert call["system"] == ai.SYSTEM and "Kontext" in call["messages"][0]["content"]


def test_weekly_returns_text_and_refusal_raises():
    client, _ = fake_client("# Wochenbericht\n\nAlles gut.")
    text, _ = ai.weekly_report({}, client)
    assert text.startswith("# Wochenbericht")
    client, _ = fake_client("", stop_reason="refusal")
    with pytest.raises(ai.AIRefused):
        ai.weekly_report({}, client)


@pytest.mark.skipif(not URL, reason="BECHER_TEST_DATABASE_URL nicht gesetzt")
def test_build_context_and_save_report_roundtrip():
    from common import db

    with db.connect(URL) as conn:
        db.apply_schema(conn)
        ctx = ai.build_context(conn, hours=24 * 30)
        assert {"opportunities", "bets", "clv_by_bookmaker", "clv_by_market", "collectors", "coverage"} <= set(ctx)
        json.dumps(ctx)  # muss serialisierbar sein
        resp = SimpleNamespace(model="test", usage=SimpleNamespace(input_tokens=1, output_tokens=2))
        rid = ai.save_report(conn, "weekly", "# Test", resp, 168)
        row = conn.execute("SELECT kind, content, input_tokens FROM ai_reports WHERE id=%s", (rid,)).fetchone()
        assert row["kind"] == "weekly" and row["content"] == "# Test" and row["input_tokens"] == 1
        conn.execute("DELETE FROM ai_reports WHERE id=%s", (rid,))
