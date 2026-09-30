import pytest

from app.research.official_bist.bulletin import BulletinError, parse_bulletin_text
from app.research.official_bist.run_universe_quality import index_bulletin
from app.research.official_bist.universe_quality import classify_symbol, compare_session

TR = "TARIH;ISLEM  KODU;BULTEN ADI;ONCEKI KAPANIS FIYATI;ACILIS FIYATI;EN DUSUK FIYAT;EN YUKSEK FIYAT;KAPANIS FIYATI;TOPLAM ISLEM HACMI;TOPLAM ISLEM ADEDI"
EN = ("TRADE DATE;INSTRUMENT SERIES CODE;INSTRUMENT NAME;PREVIOUS LAST PRICE;OPENING PRICE;LOWEST PRICE;HIGHEST PRICE;"
      "CLOSING PRICE;TOTAL TRADED VALUE;TOTAL TRADED VOLUME")


def off(o, h, l, c, v="1000"):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def test_constant_adjustment_ratio_is_not_error():
    official = off("100", "110", "95", "105")
    yahoo = {k: str(float(v) * 0.95) for k, v in official.items() if k != "volume"} | {"volume": "1000"}
    r = compare_session(yahoo, official)
    assert r["fields_consistent"] and not r["scale_is_one"]
    cls = classify_symbol([("2024-06-03", r), ("2024-06-04", compare_session(official, official))])
    assert cls["findings"] == ["SCALE_DIFF_UNEXPLAINED"] and cls["field_inconsistency_dates"] == []


def test_cross_field_inconsistency_is_caught():
    official = off("100", "110", "95", "105")
    yahoo = off("100", "110", "95", "102")  # yalnız kapanış farklı
    r = compare_session(yahoo, official)
    assert not r["fields_consistent"]
    assert classify_symbol([("2024-09-06", r)])["findings"] == ["FIELD_INCONSISTENCY_CANDIDATE"]


def test_float32_precision_within_tolerance():
    r = compare_session(off("52.349998", "52.45", "52.099998", "52.349998"), off("52.35", "52.45", "52.1", "52.35"))
    assert r["fields_consistent"] and r["scale_is_one"]


def test_missing_row_not_filled():
    r = compare_session(off("1", "1", "1", "1"), None)
    assert r == {"status": "OFFICIAL_MISSING"}
    cls = classify_symbol([("2024-06-03", r)])
    assert cls["findings"] == ["MISSING_OR_NOT_COMPARABLE"] and cls["compared"] == 0


def test_zero_official_row_not_comparable():
    r = compare_session(off("5", "5", "5", "5"), off("0", "0", "0", "0", "0"))
    assert r["status"] == "NOT_COMPARABLE" and "OFFICIAL_OHLC_INVALID" in r["problems"]


def test_wrong_share_class_not_matched_and_duplicates_rejected():
    text = "\n".join([TR, EN, "2024-06-03;ABC.AOF;X;1;1;1;1;1;1;1", "2024-06-03;ABCD.E;Y;2;2;2;2;2;2;2"])
    header, by_code = index_bulletin(text, "2024-06-03")
    assert "ABC.E" not in by_code  # başka pay sınıfı / önek eşleşmesi yok
    dup = "\n".join([TR, EN, "2024-06-03;ABC.E;X;1;1;1;1;1;1;1", "2024-06-03;ABC.E;X;1;1;1;1;1;1;1"])
    header, by_code = index_bulletin(dup, "2024-06-03")
    with pytest.raises(BulletinError):
        parse_bulletin_text("\n".join(header + by_code["ABC.E"]), "ABC.E", "2024-06-03")


def test_bulletin_date_mismatch_rejected():
    with pytest.raises(BulletinError):
        index_bulletin("\n".join([TR, EN, "2024-06-04;ABC.E;X;1;1;1;1;1;1;1"]), "2024-06-03")
