"""Günlük toplu analiz job'ı — AŞAMA 70.

Kullanıcı isteği: "tüm hisseler için günde 1 kez analiz yapmanı istiyorum ki
günlük olarak takip edelim." Projede o ana kadar hiç scheduler YOKTU (bkz.
`app/services/notifications/fcm_sender.py` modül docstring'i, KURULUM_GUNLUGU
AŞAMA 32) — bu, BİLİNÇLİ bir mimari genişleme: Google Cloud Scheduler günde
bir kez `POST /jobs/daily-analysis`'i çağırıyor (bkz. `app/api/jobs.py`,
paylaşılan bir gizli anahtarla korunuyor — herkese açık bir Cloud Run
adresinde gerçek OpenAI maliyeti oluşturduğundan).

Her aktif varlık için: (1) haberleri çeker/saklar (Yahoo+Google+Foreks —
`fetch_and_store_news`, AŞAMA 69'da bu amaçla çıkarılmıştı), (2) henüz
analiz edilmemiş haberleri EventIntelligenceEngine ile analiz eder — bütçe
kontrolü her model çağrısından önce motorun merkezi kapısında yapılır
(`event_intelligence/budget.py`); bütçe yetmezse ya da bütçe durumu
okunamazsa haber analizi o noktada DURUR (neden sonuçta açıkça yazılır),
kararlar mevcut analizlerle devam eder, (3) DecisionEngine ile teknik+haber+makroyu birleştirip
kararı kaydeder (haber tek başına karar vermiyor — DecisionEngine mimarisi
DEĞİŞMEDİ), (4) kayıtlı TÜM kullanıcılara, `GET /decisions/{symbol}` ile
AYNI bildirim mantığıyla (portföyde varsa güçlü AL/SAT, yoksa yalnızca en
güçlü yeni fırsat sinyalinde) bildirim gönderir — dedup zaten
`notify_if_strong_decision` içinde var, aynı gün/karar için spam olmaz.

Bir varlıkta hata olursa (yfinance geçici arıza vb.) o varlık atlanır, job
DURMAZ — 100 varlığın 1-2'sinde geçici hata, günün geri kalanını iptal
etmemeli.
"""

from app.engines.decision.engine import DecisionEngine
from app.engines.event_intelligence.budget import BudgetExhaustedError, BudgetUnavailableError
from app.engines.event_intelligence.engine import EventIntelligenceEngine
from app.repositories.asset_repository import AssetRepository
from app.repositories.fcm_token_repository import FcmTokenRepository
from app.repositories.news_raw_repository import NewsRawRepository
from app.repositories.portfolio_repository import PortfolioRepository
from app.services.news.foreks_news_provider import ForeksNewsProvider
from app.services.news.news_aggregator import fetch_and_store_news
from app.services.notifications.fcm_sender import notify_if_new_opportunity, notify_if_strong_decision

NEWS_FETCH_LIMIT = 10


def _make_event_engine() -> EventIntelligenceEngine | None:
    try:
        return EventIntelligenceEngine()
    except ValueError:
        # OPENAI_API_KEY ayarlı değil — haber analizi bu çalıştırmada atlanır,
        # job yine de teknik+makro ile devam eder (Missing Data Davranışı).
        return None


def run_daily_analysis(
    asset_repo: AssetRepository | None = None,
    decision_engine: DecisionEngine | None = None,
    event_engine: EventIntelligenceEngine | None = None,
    token_repo: FcmTokenRepository | None = None,
    portfolio_repo: PortfolioRepository | None = None,
    news_raw_repo: NewsRawRepository | None = None,
    foreks_provider: ForeksNewsProvider | None = None,
    fetch_news=fetch_and_store_news,
) -> dict:
    asset_repo = asset_repo or AssetRepository()
    decision_engine = decision_engine or DecisionEngine()
    token_repo = token_repo or FcmTokenRepository()
    portfolio_repo = portfolio_repo or PortfolioRepository()
    news_raw_repo = news_raw_repo or NewsRawRepository()
    foreks_provider = foreks_provider or ForeksNewsProvider()

    if event_engine is None:
        event_engine = _make_event_engine()
    analyze_news = event_engine is not None
    news_analysis_stop_reason = None if analyze_news else "EVENT_ENGINE_UNAVAILABLE"

    # Genel piyasa haberlerini (Foreks) TEK seferde çek — sembol başına DEĞİL
    # (bkz. ForeksNewsProvider modül docstring'i, tüm piyasayı tek istekte tarar).
    try:
        for item in foreks_provider.get_market_news(limit=100):
            news_raw_repo.upsert(item)
    except Exception:
        pass  # Foreks geçici olarak erişilemezse günlük iş yine de devam etmeli.

    user_ids = token_repo.list_all_user_ids()
    assets = asset_repo.list_active()

    processed: list[str] = []
    skipped_budget: list[str] = []
    errors: list[dict] = []

    for asset in assets:
        symbol = asset.symbol
        try:
            fetch_news(symbol, limit=NEWS_FETCH_LIMIT)

            if analyze_news:
                try:
                    event_engine.analyze_recent_for_asset(symbol)
                except BudgetExhaustedError:
                    analyze_news, news_analysis_stop_reason = False, "BUDGET_EXHAUSTED"
                except BudgetUnavailableError:
                    analyze_news, news_analysis_stop_reason = False, "BUDGET_STATE_UNAVAILABLE"
            if not analyze_news:
                skipped_budget.append(symbol)

            decision = decision_engine.decide_for_asset(symbol)
            processed.append(symbol)

            for user_id in user_ids:
                holding = portfolio_repo.get_position_for_asset(user_id, symbol)
                if holding is not None:
                    notify_if_strong_decision(user_id, decision, quantity_held=holding.quantity)
                else:
                    notify_if_new_opportunity(user_id, decision)
        except Exception as exc:
            errors.append({"asset": symbol, "error": str(exc)})

    return {
        "total_assets": len(assets),
        "processed": len(processed),
        "news_analysis_skipped_budget": skipped_budget,
        "news_analysis_stop_reason": news_analysis_stop_reason,
        "errors": errors,
    }
