from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user_id
from app.engines.event_intelligence.budget import BudgetExhaustedError, BudgetUnavailableError
from app.engines.event_intelligence.engine import EventIntelligenceEngine
from app.repositories.news_analysis_repository import NewsAnalysisRepository

router = APIRouter(prefix="/news", tags=["news"])


@router.post("/{symbol}/analyze")
def analyze_news(symbol: str, limit: int = 5, user_id: str = Depends(get_current_user_id)):
    """Auth zorunlu (AŞAMA 46): backend artık herkese açık bir URL'de çalışıyor —
    bu uç nokta gerçek OpenAI maliyeti oluşturduğundan, kimliği doğrulanmamış
    herkesin bütçeyi tüketebilmesini önlemek için oturum açmış kullanıcı şartı
    eklendi (bkz. app/core/auth.py, portföy uç noktalarıyla aynı desen)."""
    # Bütçe kontrolü motorun içinde, her model çağrısından önce yapılır; burada
    # yalnızca anlaşılır bir HTTP hatasına çevrilir (daha önce kaydedilmiş
    # analizler korunur, uydurma sonuç dönülmez).
    try:
        return EventIntelligenceEngine().analyze_recent_for_asset(symbol.upper(), limit=limit)
    except BudgetExhaustedError as exc:
        raise HTTPException(status_code=402, detail=f"Haber analizi bütçesi yetersiz: {exc}")
    except BudgetUnavailableError:
        raise HTTPException(status_code=503, detail="Haber analizi bütçe durumu doğrulanamadı; analiz yapılmadı")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{symbol}/analysis")
def get_news_analysis(symbol: str, limit: int = 20):
    """Daha önce üretilmiş NewsAnalysis kayıtlarını okur — YENİ bir OpenAI
    çağrısı yapmaz (maliyet kararı: analiz yalnızca POST /analyze ile
    istendiğinde tetiklenir, bkz. DecisionEngine ile aynı ilke)."""
    return NewsAnalysisRepository().list_for_asset(symbol.upper(), limit=limit)
