"""Yerel LAN geliştirme modu bayrağı.

Yalnız `scripts/run_local_lan.py` kendi sürecinde `LOCAL_LAN_DEV=1` ayarlar; varsayılan KAPALI. Cloud Run her
container'a `K_SERVICE` ortam değişkenini otomatik verir: o varsa bayrak ne olursa olsun mod ASLA açık değildir.
Bu mod yalnız statik referans verisi (varlık listesi) ve açıkça "eksik" işaretlenen dashboard için kullanılır;
portföy/işlem/kullanıcı verisi için hiçbir yedek yol yoktur.
"""

import os


def local_lan_dev_enabled() -> bool:
    return os.environ.get("LOCAL_LAN_DEV") == "1" and not os.environ.get("K_SERVICE")
