from app.research.official_bist.kap_scan_review_v3 import list_rows, process_evidence, resolve_v3


def div(idx, publish, kind, decision="01.03.2024", gm="20.03.2024", rows=(("TRAABC", "Peşin", 1.5),), update=False):
    return {"index": idx, "publish": publish, "category": "DIVIDEND",
            "effect": {"state": "UNDETERMINED" if kind == "DIVIDEND_NO_FINAL_DATE" else "DATED", "kind": kind, "dates": []},
            "evidence": {"decision_date": decision, "general_meeting_date": gm, "is_update": update, "is_correction": False,
                         "previous_notice_date": None, "dividend_rows": [{"isin": i, "label": l, "gross": g} for i, l, g in rows],
                         "capital_rows": [], "bonus_start_date": None}}


def test_published_after_range_is_not_out_of_scope_without_documented_date():
    e = div(1, "20.08.2025 18:00:00", "DIVIDEND_NO_FINAL_DATE")
    resolve_v3("ABC", [e])
    assert e["effect"]["state"] == "UNDETERMINED" and "resolution" not in e["effect"]


def test_dividend_supersede_needs_explicit_link_not_proximity():
    early = div(1, "01.03.2024 18:00:00", "DIVIDEND_NO_FINAL_DATE")
    near_unflagged = div(2, "02.03.2024 18:00:00", "DIVIDEND_FINAL")  # ertesi gün, aynı karar; güncelleme işareti yok
    resolve_v3("ABC", [early, near_unflagged])
    assert early["effect"]["state"] == "UNDETERMINED"
    assert "LATER_NOT_FLAGGED_UPDATE_OR_CORRECTION" in early["effect"]["link_check"][2]
    early = div(1, "01.03.2024 18:00:00", "DIVIDEND_NO_FINAL_DATE", rows=(("TRAABC", "1. Taksit", 1.0), ("TRAABC", "2. Taksit", 0.5)))
    single = div(3, "20.03.2024 18:00:00", "DIVIDEND_FINAL", update=True)  # taksit yapısı değişti
    resolve_v3("ABC", [early, single])
    assert early["effect"]["state"] == "UNDETERMINED" and early["effect"]["link_check"][3] == ["INSTALLMENT_MISMATCH"]
    early = div(1, "01.03.2024 18:00:00", "DIVIDEND_NO_FINAL_DATE")
    other_decision = div(4, "20.03.2024 18:00:00", "DIVIDEND_FINAL", decision="05.03.2024", update=True)
    linked = div(5, "20.09.2024 18:00:00", "DIVIDEND_FINAL", update=True)  # 6 ay sonra ama açık bağ var
    resolve_v3("ABC", [early, other_decision, linked])
    assert early["effect"]["resolution"] == "SUPERSEDED_DIVIDEND_LINKED [5]"


def bist_list(idx, day, section, rows):
    return {"index": idx, "publish": "x", "category": "RIGHTS_EXERCISE_NOTICE", "list_section": section, "rows": rows,
            "effect": {"state": "DATED", "kind": "BIST_LIST_EXPLICIT_DATE", "dates": [day]}}


def morning(idx, publish, gross=None, bonus=None):
    return {"index": idx, "publish": publish, "category": "RIGHTS_EXERCISE_NOTICE", "morning": {"gross_dividend": gross, "bonus_ratio": bonus},
            "effect": {"state": "UNDETERMINED", "kind": "BIST_MORNING_THEORETICAL_PRICE", "dates": []}}


def test_morning_notice_needs_content_match_not_same_day():
    lst = bist_list(1, "2024-04-03", "DIVIDEND", [{"Pay Kodu": "ABC", "1 TL Nominal değerli paya BRÜT (TL)": "6"}])
    other = morning(2, "03.04.2024 09:07:48", gross=5.0)
    resolve_v3("ABC", [lst, other])
    assert other["effect"]["state"] == "UNDETERMINED"
    same = morning(3, "03.04.2024 09:07:48", gross=6.0)
    later_day = morning(4, "04.04.2024 09:07:48", gross=6.0)
    resolve_v3("ABC", [lst, same, later_day])
    assert same["effect"]["resolution"] == "CORROBORATED_CONTENT_MATCH [1]" and later_day["effect"]["state"] == "UNDETERMINED"


def cap(idx, ratio=150.0, start=None):
    return {"index": idx, "publish": "01.04.2023 18:00:00", "category": "CAPITAL",
            "effect": {"state": "UNDETERMINED", "kind": "CAPITAL_PENDING_EXECUTION", "dates": []},
            "evidence": {"decision_date": "17.04.2023", "general_meeting_date": None, "is_update": True, "is_correction": False,
                         "previous_notice_date": None, "dividend_rows": [], "bonus_start_date": start,
                         "capital_rows": [{"group": "D", "isin": "TRABC", "existing": 1.0, "bonus_amount": 1.5, "bonus_ratio": ratio}]}}


def test_capital_execution_needs_process_start_date_and_list_ratio():
    lst = bist_list(9, "2023-06-06", "CAPITAL", [{"Pay Kodu": "ABC", "Bedelsiz Pay Alma Oranı (%)": "150,00000"}])
    no_date = cap(1)
    resolve_v3("ABC", [no_date, lst])  # liste pencere içinde olsa da süreçte açık başlangıç tarihi yok
    assert no_date["effect"]["state"] == "UNDETERMINED"
    a, b = cap(1), cap(2, start="06.06.2023")
    resolve_v3("ABC", [a, b, lst])
    assert a["effect"]["state"] == "DATED" and a["effect"]["dates"] == ["2023-06-06"] and a["effect"]["resolution"] == "EXECUTION_LINKED [9]"
    c, d = cap(1, ratio=100.0), cap(2, ratio=100.0, start="06.06.2023")
    resolve_v3("ABC", [c, d, lst])  # oran listeyle uyuşmuyor
    assert c["effect"]["state"] == "UNDETERMINED"


def test_list_rows_parse_innermost_table_with_empty_cells_and_capital_evidence():
    td = lambda x: f"<td><div>{x}</div></td>"
    inner = ("<table><tr>" + "".join(td(h) for h in ["Pay Adı", "Pay Kodu", "Sermaye Azaltım Oranı (%)", "Bedelsiz Pay Alma Oranı (%)"])
             + "</tr><tr>" + "".join(td(v) for v in ["ABC HOLDING", "ABC", "", "150,00000"]) + "</tr></table>")
    page = f"<table><tr><td>düzen</td></tr><tr><td>{inner}</td></tr></table>"
    assert list_rows(page, "ABC") == [{"Pay Adı": "ABC HOLDING", "Pay Kodu": "ABC", "Sermaye Azaltım Oranı (%)": "",
                                       "Bedelsiz Pay Alma Oranı (%)": "150,00000"}]
    t = ("Özet Bilgi Yapılan Açıklama Güncelleme mi ? Evet Yönetim Kurulu Karar Tarihi 17.04.2023 D Grubu, ABC, TREABC000038 "
         "455.000.000 682.500.000,000 150,00000 D Grubu Bedelsiz Pay Alma Hakkı Kullanım Başlangıç Tarihi 06.06.2023")
    e = process_evidence(t, "ABC")
    assert e["decision_date"] == "17.04.2023" and e["is_update"] and e["bonus_start_date"] == "06.06.2023"
    assert e["capital_rows"] == [{"group": "D", "isin": "TREABC000038", "existing": 455000000.0, "bonus_amount": 682500000.0, "bonus_ratio": 150.0}]
