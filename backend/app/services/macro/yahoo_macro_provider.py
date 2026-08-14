import yfinance as yf

from app.services.macro.base import MacroDataProvider

# Ana doküman bölüm 15'te listelenen makro veriler çok geniş (Fed/TCMB/ECB faiz kararları,
# CPI, NFP, GDP, likidite koşulları — bunların çoğu özel ekonomik veri API'leri ve API
# anahtarı gerektirir, ör. FRED, TCMB EVDS). Bu ilk sürümde, zaten kullandığımız Yahoo
# Finance üzerinden anahtarsız ve gerçek olarak elde edilebilen alt küme kullanılıyor:
# DXY, ABD 10 yıllık tahvil faizi, VIX, petrol, altın, USD/TRY. Diğerleri (Fed/TCMB
# açıklamaları, enflasyon verileri vb.) ileride ayrı bir provider ile eklenebilir.
TICKERS = {
    "dxy": "DX-Y.NYB",
    "us_10y_yield": "^TNX",
    "vix": "^VIX",
    "oil": "CL=F",
    "gold": "GC=F",
    "usdtry": "TRY=X",
}


class YahooMacroProvider(MacroDataProvider):
    SOURCE = "yahoo_finance"

    def get_indicator_changes(self, window: int = 20) -> dict[str, dict]:
        result = {}
        for key, symbol in TICKERS.items():
            history = yf.Ticker(symbol).history(period="2mo")
            if history.empty or len(history) < window + 1:
                continue
            close = history["Close"]
            current = float(close.iloc[-1])
            past = float(close.iloc[-window - 1])
            pct_change = ((current - past) / past) * 100 if past else 0.0
            result[key] = {"value": round(current, 4), "pct_change": round(pct_change, 4)}
        return result
