"""Seeded BIST varlıkları için son 1 günlük 5 dakikalık barları çekip
Firestore'a biriktirir (AŞAMA 48/14b).

yfinance intraday veriyi yalnızca ~60 gün geriye saklıyor — bu script
periyodik olarak (ör. seans saatleri içinde günde birkaç kez) çalıştırılarak
kendi uzun vadeli intraday geçmişimiz inşa edilir; VWAP ve BIST seans-
zamanlaması rejimi (bkz. vwap.py, session_timing.py) bu geçmişe ihtiyaç
duyar. IntradayBarRepository.add_batch() zaten aynı bar'ı iki kez yazmayı
engelliyor, bu yüzden script'i aynı gün içinde birden fazla kez çalıştırmak
güvenlidir.

Zamanlama (cron/Cloud Scheduler) bu script'in kapsamı DIŞINDA — mevcut
fetch_market_data.py ile aynı "elle/harici olarak tetiklenen script" deseni
izlenir; otomatik zamanlama ayrı bir altyapı/maliyet kararı gerektirir.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.intraday_bar import IntradayBar
from app.repositories.asset_repository import AssetRepository
from app.repositories.intraday_bar_repository import IntradayBarRepository
from app.services.market_data.bist_provider import BistProvider

if __name__ == "__main__":
    assets = AssetRepository().list_active()
    provider = BistProvider()
    repo = IntradayBarRepository()

    for asset in assets:
        try:
            df = provider.get_history(asset.symbol, period="1d", interval="5m")
            bars = [
                IntradayBar(
                    asset_id=asset.symbol,
                    session_date=str(ts.date()),
                    timestamp=ts.to_pydatetime(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                    source="yahoo_finance",
                )
                for ts, row in df.iterrows()
            ]
            written = repo.add_batch(bars)
            print(f"{asset.symbol}: {len(bars)} bar çekildi, {written} yeni bar yazıldı")
        except Exception as exc:
            print(f"{asset.symbol}: HATA - {exc}")
