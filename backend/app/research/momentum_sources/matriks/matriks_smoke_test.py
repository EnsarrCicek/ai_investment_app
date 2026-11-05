"""Matriks kısa, sınırlı canlı smoke testi — HAZIRLIK. Resmi doküman + kimlik bilgisi olmadan ÇALIŞMAZ.

    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_sources.matriks.matriks_smoke_test

Beklenen gelecek akış (en fazla MAX_TRADES işlem / MAX_SECONDS saniye):
    1. bağlan  2. AKBNK'ya abone ol  3. sınırlı işlem al  4. ham şemayı kaydet  5. zaman damgalarını doğrula
    6. kimliği doğrula  7. tekrar davranışını doğrula  8. bağlantıyı kes
Yapılandırma eksikse çıkış kodu 2 ve "NOT ACTIVE" mesajı; hiçbir ağ çağrısı yapılmaz.
"""

from __future__ import annotations

import json
import sys

from app.research.momentum_sources.matriks.adapter import MatriksAdapter
from app.research.momentum_sources.matriks.config import MatriksConfigurationRequired

SYMBOL = "AKBNK"
MAX_TRADES = 50
MAX_SECONDS = 60
STEPS = ("connect", "subscribe", "receive_limited_trades", "record_raw_schema", "verify_timestamps",
         "verify_identity", "verify_duplicates", "disconnect")


def main() -> int:
    adapter = MatriksAdapter()
    try:
        adapter.config.require()
    except MatriksConfigurationRequired as e:
        print(json.dumps({"status": "NOT ACTIVE", "reason": str(e), "steps": STEPS, "network_calls": 0},
                         ensure_ascii=False))
        return 2
    try:
        adapter.connect()
        adapter.subscribe_trades([SYMBOL])
        raise NotImplementedError("bounded receive / schema record / verification steps pending official docs")
    finally:
        adapter.disconnect()


if __name__ == "__main__":
    sys.exit(main())
