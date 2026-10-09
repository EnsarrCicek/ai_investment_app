"""Aktif varlık listesi — süreç içi kısa ömürlü önbellek + yalnız yerel LAN modunda açık işaretli yedek.

Liste pratikte değişmeyen referans verisidir (`scripts/seed_assets.py` ile yazılır), ama her ekran açılışında
~100 Firestore okuması yapıyordu. Kurallar:
* Önbellek süreç içidir, değişmez bir kopya (tuple) tutar ve açık bir son kullanma zamanı vardır.
* Süresi dolmamışsa Firestore'a gidilmez; dolmuşsa Firestore okunur ve başarılıysa önbellek yenilenir.
* Süresi dolmuş önbellek + Firestore hatası → hata yükselir (üretimde 503). Eski liste sessizce SUNULMAZ.
* Yalnız `local_lan_dev_enabled()` iken ve yalnız kota hatasında (`ResourceExhausted`) seed listesi döner; kaynak
  `LOCAL_SEED_FALLBACK` olarak işaretlenir. Bu yedek hiçbir zaman önbelleğe yazılmaz.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from google.api_core.exceptions import ResourceExhausted

from app.core.local_dev import local_lan_dev_enabled
from app.models.asset import Asset

ASSET_CACHE_TTL_SECONDS = 300
SOURCE_FIRESTORE = "FIRESTORE"
SOURCE_LOCAL_SEED_FALLBACK = "LOCAL_SEED_FALLBACK"


def seed_asset_catalog() -> tuple[Asset, ...]:
    """Yerel geliştirme yedeği: Firestore `assets` koleksiyonunu dolduran seed listesi (aynı alan değerleriyle).
    `scripts/` üretim imajına girmez (.dockerignore); bu yalnız yerel LAN sürecinde çağrılır."""
    from scripts.seed_assets import BIST100

    return tuple(Asset(symbol=s, name=n, market="BIST", asset_type="STOCK", currency="TRY")
                 for s, n in BIST100.items())


class AssetCatalog:
    def __init__(self, load: Callable[[], list[Asset]], ttl_seconds: float = ASSET_CACHE_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 fallback: Callable[[], tuple[Asset, ...]] = seed_asset_catalog):
        self._load, self._ttl, self._clock, self._fallback = load, ttl_seconds, clock, fallback
        self._lock = threading.Lock()
        self._cached: tuple[Asset, ...] | None = None
        self._expires_at = 0.0

    def list_active(self) -> tuple[list[Asset], str]:
        """(varlıklar, kaynak). Dönen liste çağırana ait bir kopyadır."""
        with self._lock:
            if self._cached is not None and self._clock() < self._expires_at:
                return [a.model_copy() for a in self._cached], SOURCE_FIRESTORE
            try:
                assets = tuple(self._load())
            except ResourceExhausted:
                if local_lan_dev_enabled():
                    return [a.model_copy() for a in self._fallback()], SOURCE_LOCAL_SEED_FALLBACK
                raise
            self._cached, self._expires_at = assets, self._clock() + self._ttl
            return [a.model_copy() for a in assets], SOURCE_FIRESTORE

    def clear(self) -> None:
        with self._lock:
            self._cached, self._expires_at = None, 0.0


def _load_from_firestore() -> list[Asset]:
    from app.repositories.asset_repository import AssetRepository

    return AssetRepository().list_active()


ASSET_CATALOG = AssetCatalog(_load_from_firestore)
