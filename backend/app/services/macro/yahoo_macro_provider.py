from datetime import datetime, timezone

import pandas as pd
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


def _extract_observed_at(index) -> datetime | None:
    """`history.index`'in son elemanından UTC-aware bir `observed_at` çıkarır
    (HATA 16C). yfinance günlük bar'ları için index genelde bir `DatetimeIndex`
    (borsanın yerel saat dilimine göre tz-aware) olur, ama garanti değildir --
    tz-naive veya beklenmedik bir tip gelirse (test fixture, API değişikliği vb.)
    burada SESSİZCE bir tarih UYDURULMAZ: tz-naive değerler UTC olarak kabul
    edilir (muhafazakâr davranış -- freshness kontrolü zaten geniş bir pay
    bırakıyor), tanınmayan tipler için `None` döner ve gösterge yukarıda
    `MacroAnalysisEngine` tarafından stale/geçersiz olarak elenir."""
    if index is None or len(index) == 0:
        return None
    ts = index[-1]
    if not isinstance(ts, pd.Timestamp):
        return None
    py_dt = ts.to_pydatetime()
    if py_dt.tzinfo is None:
        return py_dt.replace(tzinfo=timezone.utc)
    return py_dt.astimezone(timezone.utc)


class YahooMacroProvider(MacroDataProvider):
    SOURCE = "yahoo_finance"
    # HATA 16D: `SOURCE`'tan KASITLI OLARAK ayrı, stabil/makine-okunabilir bir
    # kimlik -- provenance/hash için (`SOURCE` insan-okunabilir bir veri
    # kaynağı adı, `PROVIDER_ID` ise sürümlenebilir bir sözleşme kimliğidir).
    PROVIDER_ID = "yahoo_macro_v1"
    # `get_indicator_changes()`'in varsayılan `window` değeriyle AYNI --
    # `MacroAnalysisEngine` bu değeri (call argümanı olarak GEÇİRMEDEN, mevcut
    # `_FakeProvider`-tabanlı testlerin imzasını bozmamak için) `getattr` ile
    # okuyup snapshot provenance'ına gömer; böylece hangi window'un GERÇEKTEN
    # kullanıldığı gelecekte bu sabit değişse bile geçmiş bir kayıtta sabit
    # kalır (HATA 16A madde 12).
    WINDOW = 20

    def get_indicator_changes(self, window: int = WINDOW) -> dict[str, dict]:
        result = {}
        for key, symbol in TICKERS.items():
            history = yf.Ticker(symbol).history(period="2mo")
            if history.empty or len(history) < window + 1:
                continue
            close = history["Close"]
            current = float(close.iloc[-1])
            past = float(close.iloc[-window - 1])
            pct_change = ((current - past) / past) * 100 if past else 0.0
            observed_at = _extract_observed_at(history.index)
            result[key] = {
                "value": round(current, 4),
                "pct_change": round(pct_change, 4),
                "observed_at": observed_at,
            }
        return result
