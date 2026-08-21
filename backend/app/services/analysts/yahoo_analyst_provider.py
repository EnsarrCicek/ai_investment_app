import yfinance as yf

RECOMMENDATION_COLUMNS = ["strongBuy", "buy", "hold", "sell", "strongSell"]


class YahooAnalystProvider:
    """Yahoo Finance'in (yfinance üzerinden) gerçek analist konsensüs verisi:
    banka/aracı kurum analistlerinin AL/SAT/TUT dağılımı ve ortalama/medyan
    hedef fiyat. BIST hisseleri için TÜM sembollerde veri yok (küçük/orta
    ölçekli şirketlerde analist takibi az/hiç olmayabilir — örn. SASA'da
    recommendations boş, sadece current fiyat dönüyor) — bu durum çağırana
    (engines/analysts/consensus.py) boş liste/None olarak yansıtılır, hata
    fırlatılmaz.
    """

    SOURCE = "yahoo_finance"

    def get_raw(self, symbol: str) -> dict:
        ticker = yf.Ticker(f"{symbol}.IS")

        price_targets: dict = {}
        try:
            raw_targets = ticker.analyst_price_targets
            if raw_targets:
                price_targets = dict(raw_targets)
        except Exception:
            price_targets = {}

        recommendations: list[dict] = []
        try:
            df = ticker.recommendations
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    recommendations.append(
                        {
                            "period": row.get("period"),
                            "strong_buy": int(row.get("strongBuy", 0) or 0),
                            "buy": int(row.get("buy", 0) or 0),
                            "hold": int(row.get("hold", 0) or 0),
                            "sell": int(row.get("sell", 0) or 0),
                            "strong_sell": int(row.get("strongSell", 0) or 0),
                        }
                    )
        except Exception:
            recommendations = []

        return {"price_targets": price_targets, "recommendations": recommendations}
