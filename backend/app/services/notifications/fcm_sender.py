"""FCM bildirim gönderimi — AŞAMA 32, kapsam daraltması AŞAMA 45.

Bu projede bir zamanlayıcı (scheduler/cron) altyapısı yok; bildirimler gerçek
zamanlı/arka planda kendiliğinden gönderilmez. Bunun yerine, kullanıcı bir
kararı sorguladığında (GET /decisions/{symbol}) sonuç güçlü bir AL/SAT ise
ve bu, o kullanıcı için bu varlıkta daha önce bildirilmemiş yeni bir karar
ise bildirim gönderilir. Aynı kararın her sorguda tekrar tekrar
bildirilmemesi için NotificationLog ile basit bir "son bildirilen karar"
karşılaştırması yapılır.

AŞAMA 45 önemli değişiklik: çağıran taraf (app/api/decisions.py) artık bu
fonksiyonu YALNIZCA kullanıcının portföyünde o varlık varsa çağırıyor.
Sebep: Dashboard artık BIST100'ün tamamını sorguluyor (AŞAMA 43) — eskiden
"her sorgulanan varlık" bildirim tetikleyebiliyordu, bu da 100 hissenin
onlarcası için spam bildirime yol açardı. Bu fonksiyonun kendisi hâlâ
varlık-agnostik ve genel amaçlı — kapsam kararı çağıran tarafın
sorumluluğunda, test edilebilirliği bozmamak için.

AŞAMA 48/19 — yarı-otomatik alım-satım (kullanıcı: "sat veya şu kadar
miktar al gibisinden bildirim yeter, sonra otomatiğe geçeriz"): bildirimler
artık somut bir eylem öneriyor — SAT için elde tutulan adet ("X adet
SATMANIZ öneriliyor"), AL için önerilen adet ("~X adet ALMANIZ önerilir").
Elde TUTULMAYAN bir varlık için "AL" önerisi `notify_if_new_opportunity()`
ile ayrı bir fonksiyonda ele alınır — AŞAMA 45'te çözülen spam sorununun
AYNISINI yeniden yaratmamak için (100 sembolün "AL" diyen onlarcası değil)
yalnızca en yüksek güvenilirlikli sinyal sınıfında (STRONG_BULLISH_
INITIATION — market structure/breakout/hacim/çoklu-zaman-dilimi hepsi aynı
anda uyumlu) tetiklenir; eşik bilinçli olarak çok yüksek tutuldu.

AŞAMA 48/20 — bildirim geçmişi + test bildirimi (kullanıcı: "gerçek
telefonuma kuracağız, test edelim; bildirim sayfası oluştur, AL/SAT
bildirimi geldi mi görelim"): Her BAŞARIYLA gönderilen bildirim artık
NotificationRecordRepository ile değiştirilemez bir geçmişe de yazılıyor
(notification_log'dan FARKLI — o yalnızca dedup için "son karar" tutar, bu
gerçek bir gönderim kaydıdır). `send_test_notification()`, gerçek bir AL/SAT
kararına bağlı olmadan, yalnızca FCM kurulumunun gerçek bir cihazda çalışıp
çalışmadığını doğrulamak için Ayarlar ekranındaki butondan çağrılır — dedup
UYGULANMAZ, kullanıcı istediği kadar test edebilir.
"""

from datetime import datetime, timezone

from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from app.models.ai_decision import AIDecision
from app.models.notification_record import NotificationRecord
from app.repositories.fcm_token_repository import FcmTokenRepository
from app.repositories.notification_log_repository import NotificationLogRepository
from app.repositories.notification_record_repository import NotificationRecordRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider

STRONG_DECISIONS = {"BUY", "SELL"}
_DECISION_LABELS = {"BUY": "AL", "SELL": "SAT"}

STRONG_NEW_OPPORTUNITY_SIGNAL_CLASS = "STRONG_BULLISH_INITIATION"
DEFAULT_NOTIFICATION_SETTINGS = {"default_trade_budget_tl": 5000.0}


def notify_if_strong_decision(
    user_id: str,
    decision: AIDecision,
    token_repo: FcmTokenRepository | None = None,
    log_repo: NotificationLogRepository | None = None,
    quantity_held: float | None = None,
    suggested_buy_quantity: float | None = None,
    budget_tl: float | None = None,
    record_repo: NotificationRecordRepository | None = None,
) -> bool:
    """Koşullar sağlanıp bildirim gönderilirse True döner (testte doğrulamak için).

    `quantity_held` verilirse (çağıran taraf bu varlığın portföyde olduğunu
    zaten biliyorsa) SAT bildirimi "elinizdeki X adeti satın" şeklinde somut
    bir eylem önerir. `suggested_buy_quantity`/`budget_tl` verilirse AL
    bildirimi "yaklaşık X adet (~Y TL) alın" şeklinde somut bir eylem önerir
    — miktar hesaplaması bu fonksiyon içinde YAPILMAZ, çağıran taraf sağlar
    (bkz. notify_if_new_opportunity).
    """
    if decision.decision not in STRONG_DECISIONS:
        return False

    log_repo = log_repo or NotificationLogRepository()
    if log_repo.get_last_decision(user_id, decision.asset) == decision.decision:
        return False  # Bu karar zaten bildirildi, tekrar gönderme

    token_repo = token_repo or FcmTokenRepository()
    token = token_repo.get(user_id)
    if not token:
        return False

    label = _DECISION_LABELS[decision.decision]
    score_line = f"Final skor: {decision.final_score:+.1f}, Güven: %{decision.confidence:.0f}"

    if decision.decision == "SELL" and quantity_held is not None:
        action = f"Elinizdeki {quantity_held:.0f} adet {decision.asset} hissesini SATMANIZ öneriliyor."
        body = f"{action} {score_line}"
    elif decision.decision == "BUY" and suggested_buy_quantity is not None:
        budget_text = f" (~{budget_tl:.0f} TL)" if budget_tl is not None else ""
        action = f"Yaklaşık {suggested_buy_quantity:.0f} adet{budget_text} ALMANIZ önerilir."
        body = f"{action} {score_line}"
    elif quantity_held is not None:
        body = f"Elinizde {quantity_held:.0f} adet var. {score_line}"
    else:
        body = score_line

    message = messaging.Message(
        notification=messaging.Notification(
            title=f"{decision.asset}: {label} sinyali",
            body=body,
        ),
        fid=token,
    )
    try:
        messaging.send(message)
    except firebase_exceptions.FirebaseError:
        return False

    log_repo.set_last_decision(user_id, decision.asset, decision.decision)
    record_repo = record_repo or NotificationRecordRepository()
    record_repo.add(
        NotificationRecord(
            user_id=user_id,
            asset=decision.asset,
            kind=decision.decision,
            title=f"{decision.asset}: {label} sinyali",
            body=body,
            created_at=datetime.now(timezone.utc),
        )
    )
    return True


def notify_if_new_opportunity(
    user_id: str,
    decision: AIDecision,
    analysis_repo: TechnicalAnalysisRepository | None = None,
    provider: MarketDataProvider | None = None,
    config_repo: SystemConfigRepository | None = None,
    token_repo: FcmTokenRepository | None = None,
    log_repo: NotificationLogRepository | None = None,
    record_repo: NotificationRecordRepository | None = None,
) -> bool:
    """Elde TUTULMAYAN bir varlık için "yeni AL fırsatı" bildirimi — yalnızca
    DecisionEngine "BUY" derse VE o varlığın en son TechnicalAnalysis'i
    STRONG_BULLISH_INITIATION sinyal sınıfındaysa gönderilir (bkz. modül
    docstring'i — spam'i önlemek için bilinçli olarak yüksek bir eşik).

    Önerilen miktar, config'ten gelen sabit bir TL bütçesinin (varsayılan
    5000 TL, `system_config/notification_settings`) o anki fiyata
    bölünmesiyle hesaplanır — bu, kullanıcının risk toleransını/portföy
    büyüklüğünü BİLMEDEN yapılabilecek en basit, en şeffaf tahmindir; ileride
    otomatik alım-satıma geçilince (kullanıcının kendi ifadesiyle "sonra
    otomatiğe geçeriz") gerçek bir pozisyon büyüklüğü stratejisiyle
    değiştirilmesi gerekecek.
    """
    if decision.decision != "BUY":
        return False

    analysis_repo = analysis_repo or TechnicalAnalysisRepository()
    analysis = analysis_repo.get_latest(decision.asset)
    if analysis is None or analysis.signal_class != STRONG_NEW_OPPORTUNITY_SIGNAL_CLASS:
        return False

    provider = provider or BistProvider()
    try:
        quote = provider.get_quote(decision.asset)
    except ValueError:
        return False
    if quote.last_price <= 0:
        return False

    config_repo = config_repo or SystemConfigRepository()
    settings = config_repo.get("notification_settings", DEFAULT_NOTIFICATION_SETTINGS)
    budget_tl = settings.get("default_trade_budget_tl", DEFAULT_NOTIFICATION_SETTINGS["default_trade_budget_tl"])
    suggested_quantity = int(budget_tl // quote.last_price)
    if suggested_quantity <= 0:
        return False

    return notify_if_strong_decision(
        user_id,
        decision,
        token_repo=token_repo,
        log_repo=log_repo,
        suggested_buy_quantity=suggested_quantity,
        budget_tl=budget_tl,
        record_repo=record_repo,
    )


def send_test_notification(
    user_id: str,
    token_repo: FcmTokenRepository | None = None,
    record_repo: NotificationRecordRepository | None = None,
) -> bool:
    """Ayarlar > Bildirimler ekranındaki "Test Bildirimi Gönder" butonu için
    — gerçek bir AL/SAT kararına bağlı değildir, yalnızca FCM kurulumunun
    gerçek bir cihazda çalışıp çalışmadığını doğrulamak içindir. Dedup
    (notification_log) UYGULANMAZ — kullanıcı istediği kadar test edebilir.
    """
    token_repo = token_repo or FcmTokenRepository()
    token = token_repo.get(user_id)
    if not token:
        return False

    title = "Test Bildirimi"
    body = "Bildirimler çalışıyor! Bu bir test mesajıdır."
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        fid=token,
    )
    try:
        messaging.send(message)
    except firebase_exceptions.FirebaseError:
        return False

    record_repo = record_repo or NotificationRecordRepository()
    record_repo.add(
        NotificationRecord(
            user_id=user_id,
            asset=None,
            kind="TEST",
            title=title,
            body=body,
            created_at=datetime.now(timezone.utc),
        )
    )
    return True
