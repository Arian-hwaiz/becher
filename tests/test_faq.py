from dashboard import faq


def test_faq_entries_are_complete_and_unique():
    titles = [t for _, t, _ in faq.FAQ]
    assert len(titles) == len(set(titles)) and len(titles) >= 30
    assert all(c and t and len(a) > 40 for c, t, a in faq.FAQ)
    assert set(faq.CATEGORIES) == {c for c, _, _ in faq.FAQ}


def test_core_terms_are_covered_and_search_works():
    text = " ".join(t + " " + a for _, t, a in faq.FAQ)
    for term in ("Valuebet", "Surebet", "Middle", "EV", "CLV", "Kelly", "Devig", "Marge", "1X2", "TO(2.5)", "TU(2.5)",
                 "AH1", "AH2", "Back", "Lay", "Liquidität", "Sharp", "Soft", "DNB", "BTTS", "Push", "ROI", "Brier"):
        assert term in text, term
    assert any("Closing Line Value" in t for _, t, _ in faq.search("clv"))
    assert faq.search("") == faq.FAQ and faq.search("gibtesnichtxyz") == []
