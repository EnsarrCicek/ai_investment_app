"""Seeded BIST test varlıkları (bölüm 68) için gerçek market data çeker ve Firestore'a yazar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repositories.asset_repository import AssetRepository
from app.repositories.market_data_repository import MarketDataRepository
from app.services.market_data.bist_provider import BistProvider

if __name__ == "__main__":
    assets = AssetRepository().list_active()
    provider = BistProvider()
    repo = MarketDataRepository()

    for asset in assets:
        try:
            data = provider.get_latest(asset.symbol)
            repo.add(data)
            print(f"{asset.symbol}: close={data.close} volume={data.volume} @ {data.timestamp} (source={data.source})")
        except Exception as exc:
            print(f"{asset.symbol}: HATA - {exc}")
