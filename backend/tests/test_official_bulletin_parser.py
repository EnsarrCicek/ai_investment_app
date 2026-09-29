import io
import zipfile
from decimal import Decimal

import pytest

from app.research.official_bist.bulletin import (
    BulletinError, header_map, ohlc_issues, parse_bulletin_text, parse_number, read_bulletin_zip)

TR = "TARIH;ISLEM  KODU;BULTEN ADI;ONCEKI KAPANIS FIYATI;ACILIS FIYATI;EN DUSUK FIYAT;EN YUKSEK FIYAT;KAPANIS FIYATI;TOPLAM ISLEM HACMI;TOPLAM ISLEM ADEDI"
EN = ("TRADE DATE;INSTRUMENT SERIES CODE;INSTRUMENT NAME;PREVIOUS LAST PRICE;OPENING PRICE;LOWEST PRICE;HIGHEST PRICE;"
      "CLOSING PRICE;TOTAL TRADED VALUE;TOTAL TRADED VOLUME")


def bulletin(*rows):
    return "\n".join([TR, EN, *rows])


def test_selects_exact_code_not_prefix_and_parses_dot_decimal():
    text = bulletin("2024-11-29;BSOKE.E;BATISOKE CIMENTO;57.2;57;55;60.95;60;510000000.5;8682736",
                    "2024-11-29;BSOKE.AOF;BATISOKE AOF;1;1;1;1;1;1;1")
    r = parse_bulletin_text(text, "BSOKE.E", "2024-11-29")
    assert r.fields["close"] == Decimal("60") and r.fields["high"] == Decimal("60.95")
    assert r.raw["close"] == "60" and r.fields["total_traded_quantity_raw"] == Decimal("8682736")
    assert r.missing_fields == ()


def test_header_mapping_uses_names_not_positions():
    tr = TR.split(";")
    en = EN.split(";")
    order = [0, 1, 2, 7, 4, 5, 6, 3, 9, 8]  # kapanış ve önceki kapanış yer değiştirdi
    text = "\n".join([";".join(tr[i] for i in order), ";".join(en[i] for i in order),
                      "2024-11-29;BSOKE.E;X;60;57;55;61;57.2;8682736;510"])
    r = parse_bulletin_text(text, "BSOKE.E", "2024-11-29")
    assert r.fields["close"] == Decimal("60") and r.fields["previous_last_price"] == Decimal("57.2")


def test_header_requires_both_turkish_and_english():
    with pytest.raises(BulletinError):
        header_map(TR.split(";"), EN.replace("CLOSING PRICE", "LAST PRICE").split(";"))


@pytest.mark.parametrize("text,value", [("290.75", "290.75"), ("290,75", "290.75"), ("1.234,56", "1234.56"),
                                        ("1,234.56", "1234.56"), ("6095182799.25", "6095182799.25"), (" 12 ", "12")])
def test_number_formats(text, value):
    assert parse_number(text) == Decimal(value)


def test_empty_is_none_and_garbage_raises():
    assert parse_number("") is None and parse_number("  ") is None
    with pytest.raises(BulletinError):
        parse_number("abc")


def test_missing_field_is_reported_not_invented():
    r = parse_bulletin_text(bulletin("2024-11-29;BSOKE.E;BATISOKE;57.2;57;55;61;60;;8682736"), "BSOKE.E", "2024-11-29")
    assert r.fields["total_traded_value_raw"] is None and r.missing_fields == ("total_traded_value_raw",)


def test_wrong_date_and_duplicate_row_rejected_missing_symbol_none():
    with pytest.raises(BulletinError):
        parse_bulletin_text(bulletin("2024-11-28;BSOKE.E;B;1;1;1;1;1;1;1"), "BSOKE.E", "2024-11-29")
    with pytest.raises(BulletinError):
        parse_bulletin_text(bulletin("2024-11-29;BSOKE.E;B;1;1;1;1;1;1;1", "2024-11-29;BSOKE.E;B;1;1;1;1;1;1;1"), "BSOKE.E", "2024-11-29")
    assert parse_bulletin_text(bulletin("2024-11-29;FENER.E;F;1;1;1;1;1;1;1"), "BSOKE.E", "2024-11-29") is None


def test_ohlc_consistency_flags_without_correction():
    f = {"open": Decimal("10"), "high": Decimal("9"), "low": Decimal("8"), "close": Decimal("8.5")}
    assert ohlc_issues(f) == ["OPEN_OUTSIDE_LOW_HIGH"] and f["open"] == Decimal("10")
    assert ohlc_issues({"open": None, "high": 1, "low": 1, "close": 1}) == ["OHLC_MISSING"]


def test_zip_reader_single_file():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("thb202411291.csv", bulletin("2024-11-29;BSOKE.E;B;1;1;1;1;1;1;1"))
    name, text = read_bulletin_zip(buf.getvalue())
    assert name == "thb202411291.csv" and "BSOKE.E" in text
