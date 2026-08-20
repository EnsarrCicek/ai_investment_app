"""Adlandırılmış teknik ağırlık ön ayarları — "hangi strateji daha iyi sonuç
veriyor" karşılaştırması için (kullanıcı isteği: "her yolu deneyip hangisi
daha iyi sonuç veriyor diye eğitim yapıcaz").

Serbest bir ağırlık grid taraması yerine, her biri yorumlanabilir/isimlendirilmiş
5 aday sunulur — sonuçlar bir kullanıcıya "MACD_FOCUSED kazandı" gibi anlamlı
bir şekilde gösterilebilir. Mutlak toplamları 1.0 olmak zorunda değil;
technical_score_series() zaten weight_sum'a bölerek normalize ediyor.
"""

STRATEGY_PRESETS: dict[str, dict[str, float]] = {
    "BALANCED": {
        "rsi": 0.10,
        "macd": 0.10,
        "trend": 0.15,
        "ema_slope": 0.20,
        "bollinger": 0.10,
        "momentum": 0.15,
        "roc": 0.20,
    },
    "TREND_FOLLOWING": {
        "rsi": 0.05,
        "macd": 0.10,
        "trend": 0.30,
        "ema_slope": 0.30,
        "bollinger": 0.05,
        "momentum": 0.10,
        "roc": 0.10,
    },
    "MOMENTUM": {
        "rsi": 0.05,
        "macd": 0.20,
        "trend": 0.10,
        "ema_slope": 0.15,
        "bollinger": 0.05,
        "momentum": 0.25,
        "roc": 0.20,
    },
    "MEAN_REVERSION": {
        "rsi": 0.30,
        "macd": 0.05,
        "trend": 0.05,
        "ema_slope": 0.05,
        "bollinger": 0.35,
        "momentum": 0.10,
        "roc": 0.10,
    },
    "MACD_FOCUSED": {
        "rsi": 0.05,
        "macd": 0.35,
        "trend": 0.20,
        "ema_slope": 0.15,
        "bollinger": 0.05,
        "momentum": 0.10,
        "roc": 0.10,
    },
}

STRATEGY_LABELS_TR: dict[str, str] = {
    "BALANCED": "Dengeli (Varsayılan)",
    "TREND_FOLLOWING": "Trend Takibi",
    "MOMENTUM": "Momentum Odaklı",
    "MEAN_REVERSION": "Ortalamaya Dönüş",
    "MACD_FOCUSED": "MACD Odaklı",
}
