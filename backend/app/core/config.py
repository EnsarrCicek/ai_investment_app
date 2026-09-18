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

# AŞAMA 70: günlük toplu analiz job'ını (POST /jobs/daily-analysis) tetikleyen
# Google Cloud Scheduler'ın kimliğini kanıtlaması için paylaşılan gizli
# anahtar — backend herkese açık bir Cloud Run adresinde çalıştığından, bu
# olmadan herkes bu uç noktayı tetikleyip gerçek OpenAI maliyeti
# oluşturabilirdi. Ayarlanmamışsa (örn. yerel geliştirme) uç nokta devre dışı
# kalır (403 döner) — hiçbir zaman "kontrol yok" durumuna sessizce düşmez.
DAILY_JOB_SECRET = os.environ.get("DAILY_JOB_SECRET")

# PROD-2: Technical V1 immutable evidence nesnelerinin (asset/benchmark/
# technical-output anlık-görüntüleri) yazılacağı GCS bucket'ı — KASITLI
# OLARAK hiçbir varsayılan/hardcoded production bucket adı YOKTUR (bkz.
# `app/research/technical_v1_production.py`, section 3/5). Boş/eksikse
# ordinary app startup'ı BAŞARISIZ OLMAZ -- yalnızca GERÇEK bir Technical
# V1 production servisi inşa edilmeye çalışıldığında (bir internal
# endpoint çağrıldığında) açık bir yapılandırma hatasına dönüşür.
TECHNICAL_V1_EVIDENCE_BUCKET = os.environ.get("TECHNICAL_V1_EVIDENCE_BUCKET")

# PROD-2: Technical V1 internal job endpoint'lerini (attempt1/attempt2/
# finalize/manifest) tetikleyecek olan gelecekteki Cloud Scheduler'ın
# kimliğini kanıtlaması için paylaşılan gizli anahtar -- `DAILY_JOB_
# SECRET` İLE AYNI, ZATEN kilitlenmiş desen (bkz. app/api/jobs.py).
# Ayarlanmamışsa uç noktalar devre dışı kalır (403), hiçbir zaman
# "kontrol yok" durumuna sessizce düşmez. Bu ticket HİÇBİR scheduler
# OLUŞTURMAZ -- bu sadece uç noktaları GELECEKTEKİ bir scheduler için
# HAZIR (ama şimdilik dormant) hale getirir.
TECHNICAL_V1_JOB_SECRET = os.environ.get("TECHNICAL_V1_JOB_SECRET")
