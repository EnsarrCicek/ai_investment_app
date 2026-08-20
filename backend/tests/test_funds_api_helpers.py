from app.api.funds import _tr_upper


def test_lowercase_dotted_i_matches_turkish_upper_i():
    # Python'un standart .upper()'ı "hisse" -> "HISSE" (ASCII I) verir, ama
    # TEFAS verisi "HİSSE" (Türkçe noktalı İ) kullanır — canlı testte "hisse"
    # araması hiç sonuç döndürmemişti, bu regresyonu kilitler.
    assert _tr_upper("hisse") == "HİSSE"
    assert "HİSSE" in _tr_upper("hisse senedi")


def test_dotless_i_maps_to_ascii_capital_i():
    assert _tr_upper("kısa") == "KISA"


def test_already_uppercase_turkish_text_is_unchanged():
    assert _tr_upper("HİSSE SENEDİ") == "HİSSE SENEDİ"


def test_other_turkish_characters_still_uppercase_correctly():
    assert _tr_upper("güneş özgür çiçek şeker") == "GÜNEŞ ÖZGÜR ÇİÇEK ŞEKER"
