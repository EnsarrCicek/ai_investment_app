"""Yerel ağ (LAN) deneme backend'i — ücretli OpenAI çağrıları ve job'lar KAPALI.

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe scripts\\run_local_lan.py --host 192.168.1.109

- OPENAI_API_KEY süreç içinde boşaltılır: python-dotenv mevcut değişkeni ezmez,
  böylece backend/.env'deki anahtar YÜKLENMEZ. Haber analizi (POST
  /news/{symbol}/analyze) açık bir hata döner; sahte analiz üretilmez ve bütçe
  defterine dokunulmaz.
- DAILY_JOB_SECRET / TECHNICAL_V1_JOB_SECRET boşaltılır: günlük job ve
  internal Technical uç noktaları 403 döner.
- Anahtar yine de yüklenmişse başlatma reddedilir.
- Yalnızca verilen yerel IP'ye bağlanır (internete port açmaz). Firestore
  bağlantısı .env'deki FIREBASE_PROJECT_ID projesine gider.
"""

import argparse
import os
import sys
from pathlib import Path

for name in ("OPENAI_API_KEY", "DAILY_JOB_SECRET", "TECHNICAL_V1_JOB_SECRET"):
    os.environ[name] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.core.config as config  # noqa: E402

if config.OPENAI_API_KEY or config.DAILY_JOB_SECRET or config.TECHNICAL_V1_JOB_SECRET:
    raise SystemExit("Ücretli anahtar veya job secret yüklendi — yerel LAN backend'i başlatılmadı.")

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="bilgisayarın yerel ağ IPv4 adresi")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Yerel LAN backend: http://{args.host}:{args.port}  (OpenAI ve job'lar kapalı)")
    uvicorn.run("app.main:app", host=args.host, port=args.port)
