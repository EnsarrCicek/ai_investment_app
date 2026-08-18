import os

from dotenv import load_dotenv

load_dotenv()

GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "ai-investment-app-2026")

# EventIntelligenceEngine (AŞAMA 16+) — model adları asla hard-code edilmez,
# .env üzerinden değiştirilebilir olmalı. Birincil model maliyet kontrolü
# için ucuz/hızlı katman (Luna); fallback (Terra) şimdilik yalnızca
# tanımlanıyor, çağrılmıyor (bkz. event_intelligence/engine.py).
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
EVENT_INTELLIGENCE_PRIMARY_MODEL = os.environ.get("EVENT_INTELLIGENCE_PRIMARY_MODEL", "gpt-5.6-luna")
EVENT_INTELLIGENCE_FALLBACK_MODEL = os.environ.get("EVENT_INTELLIGENCE_FALLBACK_MODEL", "gpt-5.6-terra")

# Toplam OpenAI bütçesi (kullanıcı kararı: tek seferlik $5 yükleme) — .env
# üzerinden değiştirilebilir, kod içinde hard-code edilmez.
EVENT_INTELLIGENCE_BUDGET_USD = float(os.environ.get("EVENT_INTELLIGENCE_BUDGET_USD", "5.0"))
