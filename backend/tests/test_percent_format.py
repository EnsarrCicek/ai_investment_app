from app.utils.percent_format import format_percent_fraction, format_percent_value


class TestFormatPercentValue:
    """HATA 5C-UI4 (31.08.2026): zaten 0..100 skalasındaki değerler (ör.
    `AIDecision.confidence`) -- Flutter `toStringAsFixed(0)` ile presentation-
    eşdeğer half-up rounding."""

    def test_zero(self):
        assert format_percent_value(0) == "%0"

    def test_0_4_rounds_down(self):
        assert format_percent_value(0.4) == "%0"

    def test_0_5_rounds_up_half_up_not_banker(self):
        assert format_percent_value(0.5) == "%1"

    def test_1_5_rounds_up(self):
        assert format_percent_value(1.5) == "%2"

    def test_62_4_rounds_down(self):
        assert format_percent_value(62.4) == "%62"

    def test_62_5_rounds_up_half_up_not_banker(self):
        # HATA 5C-UI3'te bulunan discrepancy: Python'un `f"{62.5:.0f}"`'ı
        # banker's rounding ile "%62" üretiyordu -- bu formatter "%63"
        # üretmeli (Flutter/Dart ile hizalı).
        assert format_percent_value(62.5) == "%63"

    def test_62_6_rounds_up(self):
        assert format_percent_value(62.6) == "%63"

    def test_99_5_rounds_up_to_100(self):
        assert format_percent_value(99.5) == "%100"

    def test_100_stays_100(self):
        assert format_percent_value(100) == "%100"


class TestFormatPercentFraction:
    """0..1 skalasındaki değerler (ör. `channel_completeness`,
    `evidence_coverage`) -- ×100 uygulanır."""

    def test_zero(self):
        assert format_percent_fraction(0) == "%0"

    def test_0_005_rounds_up_to_1(self):
        assert format_percent_fraction(0.005) == "%1"

    def test_0_2_is_20(self):
        assert format_percent_fraction(0.2) == "%20"

    def test_0_625_rounds_up_to_63(self):
        assert format_percent_fraction(0.625) == "%63"

    def test_0_8_is_80(self):
        assert format_percent_fraction(0.8) == "%80"

    def test_1_is_100(self):
        assert format_percent_fraction(1) == "%100"
