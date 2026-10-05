import json

from app.research.official_bist.kap_scan_review_v2 import event_effect, list_section, query_files, resolve


def ev(cat, publish, fields, idx=1, kap_title="ORNEK A.Ş.", subject="", summary="", section=None):
    e = {"index": idx, "publish": publish, "kap_title": kap_title, "subject": subject, "summary": summary,
         "category": cat, "fields": fields, "list_section": section}
    e["effect"] = event_effect("ABC", e)
    return e


PAID_NO_FINAL = {"cash_dividend_payment": "Peşin", "share_dividend_payment": "Ödenmeyecek",
                 "dividend_table_rows": [{"label": "Peşin", "proposed": "02.06.2025", "final": None, "payment": "04.06.2025", "record": "03.06.2025"}]}


def test_dividend_uses_only_final_date_never_proposed_or_payment():
    e = ev("DIVIDEND", "10.04.2025 18:00:00", PAID_NO_FINAL)
    assert e["effect"]["state"] == "UNDETERMINED" and e["effect"]["dates"] == []
    final = dict(PAID_NO_FINAL, dividend_table_rows=[{"label": "Peşin", "proposed": "01.06.2025", "final": "02.06.2025",
                                                      "payment": "04.06.2025", "record": "03.06.2025"}])
    assert ev("DIVIDEND", "10.04.2025 18:00:00", final)["effect"]["dates"] == ["2025-06-02"]
    unparsed = dict(PAID_NO_FINAL, dividend_table_rows=[{"label": "Peşin", "unparsed": ["02.06.2025"]}])
    assert ev("DIVIDEND", "10.04.2025 18:00:00", unparsed)["effect"]["state"] == "UNDETERMINED"


def test_undetermined_before_range_is_not_filtered_by_publish_date():
    events = [ev("DIVIDEND", "10.04.2023 18:00:00", PAID_NO_FINAL)]
    resolve("ABC", events)
    assert events[0]["effect"]["state"] == "UNDETERMINED"


def test_superseded_dividend_and_out_of_scope_publication_are_resolved_with_reason():
    later = ev("DIVIDEND", "20.04.2023 18:00:00", {"cash_dividend_payment": "Ödenmeyecek", "share_dividend_payment": "Ödenmeyecek"}, idx=2)
    events = [ev("DIVIDEND", "10.04.2023 18:00:00", PAID_NO_FINAL), later, ev("DIVIDEND", "20.07.2025 18:00:00", PAID_NO_FINAL, idx=3)]
    resolve("ABC", events)
    assert events[0]["effect"]["resolution"].startswith("SUPERSEDED_DIVIDEND")
    assert events[2]["effect"]["resolution"] == "OUT_OF_SCOPE_PUBLISHED_AFTER_RANGE"


def test_bist_date_only_from_explicit_text_not_publish_time():
    no_date = ev("RIGHTS_EXERCISE_NOTICE", "02.04.2024 17:05:07", {"rights_list_effective_date": None, "theoretical_price_codes": []},
                 kap_title="BORSA İSTANBUL A.Ş.")
    assert no_date["effect"]["state"] == "UNDETERMINED"
    explicit = ev("RIGHTS_EXERCISE_NOTICE", "02.04.2024 17:05:07", {"rights_list_effective_date": "03.04.2024", "theoretical_price_codes": []},
                  kap_title="BORSA İSTANBUL A.Ş.", idx=2, section="DIVIDEND")
    assert explicit["effect"]["dates"] == ["2024-04-03"]
    morning = ev("RIGHTS_EXERCISE_NOTICE", "03.04.2024 09:07:48", {"rights_list_effective_date": None, "theoretical_price_codes": ["ABC"]},
                 kap_title="BORSA İSTANBUL A.Ş.", idx=3)
    events = [explicit, morning]
    resolve("ABC", events)
    assert morning["effect"]["resolution"].startswith("CORROBORATED_BY_EXPLICIT_LIST")


def test_capital_pending_needs_capital_section_list():
    pending = ev("CAPITAL", "14.02.2024 19:00:00", {"date_labels": [], "rights_dates": []}, summary="Bedelsiz Sermaye Artırımı Hk.")
    div_list = ev("RIGHTS_EXERCISE_NOTICE", "02.04.2024 17:05:07", {"rights_list_effective_date": "03.04.2024", "theoretical_price_codes": []},
                  kap_title="BORSA İSTANBUL A.Ş.", idx=2, section="DIVIDEND")
    events = [pending, div_list]
    resolve("ABC", events)
    assert pending["effect"]["state"] == "UNDETERMINED"
    cap_list = ev("RIGHTS_EXERCISE_NOTICE", "15.05.2024 17:05:07", {"rights_list_effective_date": "16.05.2024", "theoretical_price_codes": []},
                  kap_title="BORSA İSTANBUL A.Ş.", idx=3, section="CAPITAL")
    pending2 = ev("CAPITAL", "14.02.2024 19:00:00", {"date_labels": [], "rights_dates": []}, summary="Bedelsiz Sermaye Artırımı Hk.", idx=4)
    events = [pending2, cap_list]
    resolve("ABC", events)
    assert pending2["effect"]["resolution"].startswith("EXECUTION_FOUND")


def test_list_section_parsing():
    t = ("16.05.2023 tarihinden itibaren hak kullanımı ... listesi aşağıdadır. Kar Payı Ödemesi Pay Adı Pay Kodu KUSTUR KSTUR 8,7 "
         "Sermaye Artırımı/Azaltımı Pay Adı Pay Kodu OTOKAR OTKAR 0 100")
    assert list_section(t, "OTKAR") == "CAPITAL" and list_section(t, "KSTUR") == "DIVIDEND" and list_section(t, "XYZ") is None


def test_ambiguous_member_legacy_cache_not_used(tmp_path):
    (tmp_path / "kap").mkdir()
    q = {"from": "2024-01-01", "to": "2024-12-31", "oid": "BANK"}
    (tmp_path / "kap" / "disc_ABC_BANK_2024-01-01_2024-12-31.json").write_text(json.dumps([]), encoding="utf-8")
    (tmp_path / "kap" / "disc_ABC_2024-01-01_2024-12-31.json").write_text(json.dumps([{"x": 1}]), encoding="utf-8")
    scan = {"identity": {"kap_oid": "BANK"}, "identity_resolution": {}, "queries": [q]}
    used, invalid = query_files(tmp_path, "ABC", scan, {})
    assert [u["file"] for u in used] == ["disc_ABC_BANK_2024-01-01_2024-12-31.json"]
    assert invalid[0]["problem"].startswith("LEGACY_NAME_WITHOUT_OID")
