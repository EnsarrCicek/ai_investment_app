"""Seeds the initial BIST test assets (main doc section 68) into Firestore."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.asset import Asset
from app.repositories.asset_repository import AssetRepository

TEST_ASSETS = [
    Asset(symbol="THYAO", name="Türk Hava Yolları", market="BIST", asset_type="STOCK", currency="TRY"),
    Asset(symbol="ASELS", name="Aselsan", market="BIST", asset_type="STOCK", currency="TRY"),
    Asset(symbol="GARAN", name="Garanti BBVA", market="BIST", asset_type="STOCK", currency="TRY"),
    Asset(symbol="AKBNK", name="Akbank", market="BIST", asset_type="STOCK", currency="TRY"),
    Asset(symbol="EREGL", name="Ereğli Demir ve Çelik", market="BIST", asset_type="STOCK", currency="TRY"),
    Asset(symbol="TUPRS", name="Tüpraş", market="BIST", asset_type="STOCK", currency="TRY"),
]

if __name__ == "__main__":
    repo = AssetRepository()
    for asset in TEST_ASSETS:
        repo.upsert(asset)
        print(f"Seeded {asset.symbol} - {asset.name}")
