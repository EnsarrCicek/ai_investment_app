import pandas as pd

PERIOD_LOOKBACK_DAYS = {
    "1d": 1,
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 182,
    "1y": 365,
}


def compute_period_changes(history: pd.DataFrame) -> dict[str, float | None]:
    """Günlük kapanış fiyatlarından dönemsel yüzde değişimleri hesaplar.

    `history`, en az ~1 yıllık günlük kapanış içermelidir (BistProvider.get_history
    ile period="2y", interval="1d"). Bir dönem için yeterli geçmiş yoksa (ör.
    hisse 1 yıldan kısa süredir işlem görüyorsa) o dönem için None döner —
    sahte/enterpole bir değer ASLA üretilmez (Missing Data Davranışı).
    """
    if history.empty:
        return {key: None for key in PERIOD_LOOKBACK_DAYS}

    closes = history["Close"]
    last_price = closes.iloc[-1]
    last_date = closes.index[-1]

    result: dict[str, float | None] = {}
    for label, days in PERIOD_LOOKBACK_DAYS.items():
        target_date = last_date - pd.Timedelta(days=days)
        past = closes[closes.index <= target_date]
        if past.empty or past.iloc[-1] == 0:
            result[label] = None
            continue
        past_price = past.iloc[-1]
        result[label] = round(((last_price - past_price) / past_price) * 100, 2)
    return result
