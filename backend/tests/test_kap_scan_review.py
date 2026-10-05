from datetime import date

from app.research.official_bist.kap_scan import classify, extract_fields
from app.research.official_bist.kap_scan_review import event_effect, review_symbol, usable_sessions
from app.services.market_data.trading_calendar import expected_trading_sessions

DAYS = [d.isoformat() for d in expected_trading_sessions(date(2024, 5, 7), date(2025, 7, 11))]


def ev(**kw):
    base = {"category": "DIVIDEND", "publish": "10.04.2025 18:00:00", "index": 1, "kap_title": "ORNEK A.Ş.", "subject": "", "summary": ""}
    return base | kw


def test_classify_subjects():
    assert classify("Kar Payı Dağıtım İşlemlerine İlişkin Bildirim", "") == "DIVIDEND"
    assert classify("Sermaye Artırımı - Azaltımı İşlemlerine İlişkin Bildirim", "Bedelsiz") == "CAPITAL"
    assert classify("BISTECH Pay Piyasası Alım Satım Sistemi Duyurusu", "Hak Kullanımı") == "RIGHTS_EXERCISE_NOTICE"
    assert classify("Özel Durum Açıklaması (Genel)", "Trafik") is None


def test_extract_dividend_fields_and_dates():
    t = ("Özet Bilgi Nakit Kar Payı Ödeme Şekli Peşin Pay Biçiminde Ödeme Ödenmeyecek Hak Kullanım Tarihi 02.06.2025 "
         "Kar Payı Ödeme Tarihi 04.06.2025 B Grubu, ABC, TRAABCXX0011 1,5000000")
    f = extract_fields(t)
    assert f["cash_dividend_payment"].startswith("Peşin") and f["rights_dates"][:2] == ["02.06.2025", "04.06.2025"]
    assert f["date_labels"][0] == "Hak Kullanım Tarihi"


def test_unpaid_dividend_not_price_affecting_paid_uses_ex_date_not_publish():
    no = event_effect(ev(cash_dividend_payment="Ödenmeyecek Para", share_dividend_payment="Ödenmeyecek"))
    assert no["price_affecting"] is False
    paid = event_effect(ev(cash_dividend_payment="Peşin", share_dividend_payment="Ödenmeyecek",
                           date_labels=["Hak Kullanım Tarihi"], rights_dates=["02.06.2025"]))
    assert paid["price_affecting"] and paid["effective_date"] == "2025-06-02"  # yayın günü 10.04 değil


def test_paid_dividend_without_date_is_undetermined_and_blocks():
    e = ev(cash_dividend_payment="Peşin", share_dividend_payment="")
    assert event_effect(e)["effective_date"] is None
    scan = {"symbol": "ABC", "identity": {"status": "MATCH"}, "queries": [{"result": 3}], "events": [e]}
    rows = [{"trade_date": d, "status": "OK"} for d in DAYS]
    r = review_symbol(scan, rows, "sha")
    assert r["status"] == "NOT_READY" and "UNDETERMINED_CORPORATE_EVENT" in r["blockers"] and r["usable_sessions"] == []


def test_usable_sessions_exclude_windows_containing_event():
    evaluable = [d for d in DAYS if d >= "2024-11-22"]
    usable = usable_sessions(evaluable, ["2025-06-02"])
    assert "2025-05-30" in usable and "2025-06-02" not in usable and "2025-07-11" not in usable


def test_bist_rights_notice_dates_effect_on_publish_day():
    e = event_effect(ev(category="RIGHTS_EXERCISE_NOTICE", kap_title="BORSA İSTANBUL A.Ş.", subject="BISTECH Duyurusu",
                        summary="Hak Kullanımı", publish="02.06.2025 09:05:00"))
    assert e["price_affecting"] and e["effective_date"] == "2025-06-02"


def test_identity_not_match_or_failed_query_not_ready():
    rows = [{"trade_date": d, "status": "OK"} for d in DAYS]
    r = review_symbol({"symbol": "ABC", "identity": {"status": "AMBIGUOUS"}, "queries": [{"result": None}], "events": []}, rows, "sha")
    assert r["status"] == "NOT_READY" and {"IDENTITY_AMBIGUOUS", "KAP_QUERY_INCOMPLETE"} <= set(r["blockers"])
    ok = review_symbol({"symbol": "ABC", "identity": {"status": "MATCH"}, "queries": [{"result": 2}], "events": []}, rows, "sha")
    assert ok["status"] == "READY_FOR_RESEARCH_WITH_LIMITS" and ok["bound_to"]["raw_csv_sha256"] == "sha"


def test_subject_based_classification_ignores_unrelated_mentions():
    assert classify("Özel Durum Açıklaması (Genel)", "Bağlı Ortağımızdan Temettü Alınması") is None
    assert classify("BIST Pay Endeksleri", "BIST Temettü 25 Endeks Dönemsel Değişiklik") is None
    assert classify("Ortaklık Aleyhine Dava Açılması veya Davaya İlişkin", "Genel Kurul tarafından bedelsiz sermaye") is None
    assert classify("Hak Kullanımı", "") == "RIGHTS_EXERCISE_NOTICE"


def test_dividend_table_ex_date_prefers_final_over_proposed():
    t = ("Kar Payı Ödeme Tarihleri Ödeme Teklif Edilen Nakit Kar Payı Hak Kullanım Tarihi (1) Kesinleşen Nakit Kar Payı "
         "Hak Kullanım Tarihi (2) Ödeme Tarihi (3) Kayıt Tarihi (4) Peşin 01.04.2024 03.04.2024 05.04.2024 04.04.2024")
    assert extract_fields(t)["dividend_table_rows"] == [{"label": "Peşin", "proposed": "01.04.2024", "final": "03.04.2024",
                                                         "payment": "05.04.2024", "record": "04.04.2024"}]
    e = event_effect(ev(cash_dividend_payment="Peşin", share_dividend_payment="Ödenmeyecek", dividend_ex_dates=["03.04.2024"]))
    assert e["effective_date"] == "2024-04-03"


def test_afternoon_bist_rights_notice_applies_to_next_session():
    e = event_effect(ev(category="RIGHTS_EXERCISE_NOTICE", kap_title="BORSA İSTANBUL A.Ş.", subject="Hak Kullanımı",
                        summary="", publish="02.04.2024 17:05:07"))
    assert e["effective_date"] == "2024-04-03"


def test_in_range_dividend_needs_bist_corroboration():
    rows = [{"trade_date": d, "status": "OK"} for d in DAYS]
    div = ev(cash_dividend_payment="Peşin", share_dividend_payment="Ödenmeyecek", dividend_ex_dates=["02.06.2025"], index=7)
    base = {"symbol": "ABC", "identity": {"status": "MATCH"}, "queries": [{"result": 3}]}
    alone = review_symbol(base | {"events": [div]}, rows, "sha")
    assert alone["status"] == "NOT_READY" and "UNDETERMINED_CORPORATE_EVENT" in alone["blockers"]
    bist = ev(category="RIGHTS_EXERCISE_NOTICE", kap_title="BORSA İSTANBUL A.Ş.", subject="Hak Kullanımı", summary="",
              publish="30.05.2025 17:00:00", index=8)  # sonraki seans 02.06.2025
    both = review_symbol(base | {"events": [div, bist]}, rows, "sha")
    assert both["price_affecting_effective_dates"] == ["2025-06-02"] and both["status"] == "READY_FOR_RESEARCH_WITH_LIMITS"
    assert "2025-06-02" not in both["usable_sessions"] and "2025-05-30" in both["usable_sessions"]


class FakeFetcher:
    def __init__(self, members, disc_by_oid):
        self.members, self.disc_by_oid = members, disc_by_oid

    def member(self, sym):
        return self.members

    def disclosures(self, sym, oid, a, b, oid_in_name=False):
        return [d for d in self.disc_by_oid.get(oid, []) if a <= dmy_(d["publishDate"]) <= b]

    def notice(self, idx):
        return "Özet Bilgi"


def dmy_(s):
    d, m, y = s[:10].split(".")
    return f"{y}-{m}-{d}"


def disc(title, codes, publish, subject="Özel Durum Açıklaması (Genel)", summary="x", idx=1):
    return {"kapTitle": title, "stockCodes": codes, "publishDate": publish, "subject": subject, "summary": summary,
            "disclosureIndex": idx, "relatedStocks": None}


def test_ambiguous_member_resolved_by_own_code_and_title_and_title_change_dating():
    from app.research.official_bist.kap_scan import scan_symbol
    members = [{"companyCode": "1", "mkkMemberOid": "G", "title": "ABC GYO"}, {"companyCode": "2", "mkkMemberOid": "B", "title": "ABC BANKASI"}]
    both = {"G": [disc("ABC GYO", "ABC, ABCGY", "02.06.2024 10:00:00")], "B": [disc("ABC BANKASI", "ABC", "03.06.2024 10:00:00")]}
    assert scan_symbol(FakeFetcher(members, both), "ABC", None)["identity"]["status"] == "AMBIGUOUS"  # tahminle seçilmez
    data = {"G": [disc("ABC GYO", "ABCGY", "01.06.2024 10:00:00"), disc("ABC BANKASI", "ABC, ABCGY", "02.06.2024 10:00:00")],
            "B": [disc("ABC BANKASI", "ABC", "03.06.2024 10:00:00"),
                  disc("ABC BANKASI", "ABC", "30.07.2025 10:00:00", summary="Unvan Değişikliği hk.", idx=9)]}
    r = scan_symbol(FakeFetcher(members, data), "ABC", None)
    assert r["identity"]["kap_member_code"] == "2" and r["identity"]["status"] == "MATCH"  # unvan değişikliği dönem dışı
    data["B"].append(disc("ABC BANKASI", "ABC", "01.10.2024 10:00:00", summary="Unvan değişikliği", idx=10))
    r2 = scan_symbol(FakeFetcher(members, data), "ABC", None)
    assert r2["identity"]["status"] == "MATCH_WITH_TITLE_CHANGE"
