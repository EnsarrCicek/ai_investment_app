import pandas as pd
import pytest

from app.engines.technical.market_structure import (
    SwingType,
    analyze_market_structure,
    classify_trend,
    find_swing_points,
    label_structure,
)

# Bilinçli olarak inşa edilmiş zigzag: peak(110) -> trough(95) -> peak(115, HH)
# -> trough(100, HL) -> peak(120, HH). Dönüş noktaları left/right_bars=2
# penceresi kapsayacak kadar birbirinden uzak, aradaki barlar monotonik —
# böylece beklenen swing point'ler belirsizliğe yer bırakmadan hesaplanabilir.
_VALUES = [
    100, 102, 104, 106, 108, 110, 108, 106, 102, 98,
    95, 97, 100, 105, 110, 115, 112, 108, 104, 102,
    100, 103, 107, 112, 116, 120, 117, 113, 109, 105,
]


def _df(values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(values), freq="D")
    series = pd.Series(values, index=idx, dtype=float)
    return pd.DataFrame({"Open": series, "High": series, "Low": series, "Close": series, "Volume": 1000.0})


def test_find_swing_points_detects_expected_peaks_and_troughs():
    points = find_swing_points(_df(_VALUES), left_bars=2, right_bars=2)

    highs = [(p.index, p.price) for p in points if p.type == SwingType.HIGH]
    lows = [(p.index, p.price) for p in points if p.type == SwingType.LOW]

    assert highs == [(5, 110.0), (15, 115.0), (25, 120.0)]
    assert lows == [(10, 95.0), (20, 100.0)]


def test_label_structure_marks_hh_hl_pattern():
    points = label_structure(find_swing_points(_df(_VALUES), left_bars=2, right_bars=2))
    labels = {p.index: p.label for p in points}

    assert labels[5] is None  # ilk swing high — karşılaştıracak öncül yok
    assert labels[10] is None  # ilk swing low
    assert labels[15] == "HH"
    assert labels[20] == "HL"
    assert labels[25] == "HH"


def test_classify_trend_reports_uptrend_for_hh_hl_sequence():
    points = label_structure(find_swing_points(_df(_VALUES), left_bars=2, right_bars=2))
    assert classify_trend(points) == "UPTREND"


def test_classify_trend_reports_downtrend_for_lh_ll_sequence():
    reversed_values = list(reversed(_VALUES))  # UPTREND fikstürünün ters çevrilmişi -> LH/LL
    points = label_structure(find_swing_points(_df(reversed_values), left_bars=2, right_bars=2))
    assert classify_trend(points) == "DOWNTREND"


def test_classify_trend_returns_unknown_without_labeled_points():
    assert classify_trend([]) == "UNKNOWN"


def test_analyze_market_structure_combines_detection_and_labeling():
    result = analyze_market_structure(_df(_VALUES), left_bars=2, right_bars=2)
    assert result["structure"] == "UPTREND"
    assert len(result["swing_points"]) == 5


def test_last_right_bars_window_has_no_confirmed_swing_point():
    # Serinin son right_bars barı için henüz onay verilemez (look-ahead-bias
    # güvenlik sınırı) — bu yüzden son bar bir swing point olarak görünmemeli.
    points = find_swing_points(_df(_VALUES), left_bars=2, right_bars=2)
    last_confirmable_index = len(_VALUES) - 2 - 1  # n - right_bars - 1
    assert all(p.index <= last_confirmable_index for p in points)


def test_confirmed_swing_points_are_causal():
    # Bir swing point'in onaylanması için gereken barlardan SONRA daha fazla
    # bar eklemek, o noktanın zaten verilmiş etiketini/tipini DEĞİŞTİRMEMELİ —
    # aksi halde gösterge gelecekteki veriyi kullanıyor demektir.
    full_df = _df(_VALUES)
    truncated_df = full_df.iloc[:28]  # idx25'teki peak'i onaylamak için yeterli (25 + right_bars=2)

    full_points = label_structure(find_swing_points(full_df, left_bars=2, right_bars=2))
    truncated_points = label_structure(find_swing_points(truncated_df, left_bars=2, right_bars=2))

    full_up_to_25 = [(p.index, p.type, p.price, p.label) for p in full_points if p.index <= 25]
    truncated_up_to_25 = [(p.index, p.type, p.price, p.label) for p in truncated_points if p.index <= 25]

    assert full_up_to_25 == truncated_up_to_25
