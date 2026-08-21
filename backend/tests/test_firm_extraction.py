from app.services.news.firm_extraction import extract_analyst_firm


def test_extracts_known_domestic_brokerage_from_headline():
    text = "İş Yatırım THYAO için hedef fiyatını yükseltti"
    assert extract_analyst_firm(text) == "İş Yatırım"


def test_extracts_known_international_bank_case_insensitively():
    text = "hsbc: favori hissem THYAO, hedef fiyat yükseldi"
    assert extract_analyst_firm(text) == "HSBC"


def test_extracts_firm_with_turkish_dotted_i_case_insensitively():
    # Türkçe küçük "i" -> büyük "İ" dönüşümü doğru çalışmalı (bkz. tr_upper).
    text = "iş yatırım'dan yeni hedef fiyat açıklaması geldi"
    assert extract_analyst_firm(text) == "İş Yatırım"


def test_returns_none_when_no_known_firm_mentioned():
    text = "THYAO için hedef fiyat 474 TL'ye indirilirken 'al' korundu"
    assert extract_analyst_firm(text) is None


def test_returns_none_for_empty_text():
    assert extract_analyst_firm("") is None
