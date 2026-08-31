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
from app.repositories.new_opportunity_notification_repository import NewOpportunityNotificationRepository
from app.repositories.notification_log_repository import NotificationLogRepository
from app.repositories.notification_record_repository import NotificationRecordRepository
from app.repositories.system_config_repository import SystemConfigRepository
from app.repositories.technical_analysis_repository import TechnicalAnalysisRepository
from app.services.market_data.base import MarketDataProvider
from app.services.market_data.bist_provider import BistProvider
from app.utils.percent_format import format_percent_fraction, format_percent_value

STRONG_DECISIONS = {"BUY", "SELL"}
_DECISION_LABELS = {"BUY": "AL", "SELL": "SAT"}

STRONG_NEW_OPPORTUNITY_SIGNAL_CLASS = "STRONG_BULLISH_INITIATION"
DEFAULT_NOTIFICATION_SETTINGS = {"default_trade_budget_tl": 5000.0}


def _compose_and_send(
    user_id: str,
    decision: AIDecision,
    token_repo: FcmTokenRepository,
    record_repo: NotificationRecordRepository | None,
    quantity_held: float | None,
    suggested_buy_quantity: float | None,
    budget_tl: float | None,
) -> bool:
    """Mesajı oluşturup gönderir ve gönderim geçmişine yazar — HİÇBİR dedupe
    KONTROLÜ YAPMAZ (bkz. HATA 4B: `notify_if_strong_decision()` ve
    `notify_if_new_opportunity()` artık BİLİNÇLİ OLARAK AYRI dedupe
    mekanizmaları kullanıyor; bu yüzden dedupe kararı ÇAĞIRANA bırakıldı, tek
    bir yerde kopyalanmasın diye yalnızca mesaj oluşturma/gönderme/kayıt
    ortak bir yardımcıya taşındı — davranış AŞAMA 48/19'daki orijinal
    `notify_if_strong_decision()` gövdesiyle BİREBİR AYNI).
    """
    token = token_repo.get(user_id)
    if not token:
        return False

    label = _DECISION_LABELS[decision.decision]
    # HATA 5C-UI4 (31.08.2026): eski "Güven: %XX" ifadesi generic/eski
    # semantik taşıyordu -- bu fonksiyona geçirilen `decision` HER ZAMAN
    # `decide_for_asset()`'in TAZE ürettiği bir DecisionEngine 1.1.0 nesnesi
    # (bkz. `api/decisions.py::get_decision` -- `channel_completeness` bu
    # yüzden HER ZAMAN mevcuttur, version-aware bir legacy dal GEREKMEZ).
    # `format_percent_value`/`format_percent_fraction`, Flutter'ın
    # `toStringAsFixed(0)` ile presentation-eşdeğer half-up rounding kullanır.
    score_line = (
        f"Final skor: {decision.final_score:+.1f}, "
        f"Sinyal Mutabakatı: {format_percent_value(decision.confidence)}, "
        f"Veri Kapsamı: {format_percent_fraction(decision.channel_completeness)}"
    )

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
        # NOT: messaging.Message'ın `fid` alanı FCM registration token'ı DEĞİL,
        # farklı bir kimlik türü olan Firebase Installation ID'yi bekliyor
        # (bkz. firebase_admin/_messaging_encoder.py docstring'i). Flutter'daki
        # FirebaseMessaging.instance.getToken() bir FCM registration token
        # döndürüyor — bu yüzden `fid` yerine `token` kullanılmalı, aksi halde
        # gerçek cihazda "NotRegistered" (404) hatası alınır (bkz.
        # KURULUM_GUNLUGU.md AŞAMA 56).
        token=token,
    )
    try:
        messaging.send(message)
    except firebase_exceptions.FirebaseError:
        return False

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

    Dedupe contract'ı HATA 4B'de DEĞİŞMEDİ: `(user_id, asset) -> son bildirilen
    karar` (`NotificationLogRepository`/`notification_log`) — bu fonksiyonun
    var olan davranışı, `notify_if_new_opportunity()` artık kendi AYRI
    event-specific dedupe'unu kullandığı için burada bilinçli olarak
    korundu (bkz. o fonksiyonun docstring'i).
    """
    if decision.decision not in STRONG_DECISIONS:
        return False

    log_repo = log_repo or NotificationLogRepository()
    if log_repo.get_last_decision(user_id, decision.asset) == decision.decision:
        return False  # Bu karar zaten bildirildi, tekrar gönderme

    token_repo = token_repo or FcmTokenRepository()
    sent = _compose_and_send(
        user_id, decision, token_repo, record_repo,
        quantity_held=quantity_held, suggested_buy_quantity=suggested_buy_quantity, budget_tl=budget_tl,
    )
    if sent:
        log_repo.set_last_decision(user_id, decision.asset, decision.decision)
    return sent


def notify_if_new_opportunity(
    user_id: str,
    decision: AIDecision,
    analysis_repo: TechnicalAnalysisRepository | None = None,
    provider: MarketDataProvider | None = None,
    config_repo: SystemConfigRepository | None = None,
    token_repo: FcmTokenRepository | None = None,
    new_opportunity_log_repo: NewOpportunityNotificationRepository | None = None,
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

    HATA 4B (27.08.2026) — EVENT-SPECIFIC, ATOMIC-CLAIM DEDUPE: bu fonksiyon
    eskiden `notify_if_strong_decision()`'ı DOĞRUDAN çağırıp onun
    `(user_id, asset) -> son bildirilen karar` dedupe'unu PAYLAŞIYORDU —
    audit'te kanıtlandı ki bu, iki kavramsal olarak ayrı bildirimin
    (portföy-bazlı SAT/AL ile elde tutulmayan bir varlıktaki "yeni fırsat")
    birbirini SESSİZCE bastırmasına yol açabiliyordu.

    Sonraki sürüm (`get_last_notified_event_id`/`set_last_notified_event_id`,
    TEK `(user,asset)` dokümanı) de HATA 4B pre-commit audit'inde BUG
    ÇIKTI: "son event" overwrite edildiğinden, event2 bildirildikten SONRA
    `select_live_breakout_event()` (event2 INVALIDATED olup düştüğünde)
    event1'e GERİ DÖNERSE, event1 zaten bir kez bildirilmiş olmasına RAĞMEN
    tekrar gönderiliyordu — gerçek repository sınıfıyla kanıtlandı. Ayrıca bu
    "check sonra write" deseni ATOMIK DEĞİLDİ (`GET /decisions/{symbol}` ile
    günlük job aynı event için yakın zamanda çalışırsa duplicate riski vardı).

    Artık `NewOpportunityNotificationRepository`'nin ATOMİK CLAIM/SENT/RELEASE
    üçlüsü kullanılıyor (her event kendi Firestore dokümanına sahip, `create()`
    precondition'ı ile atomik "kontrol et VE claim et") — bkz. o sınıfın
    docstring'i, DUPLICATE-AVERSE/AT-MOST-ONCE delivery semantiği dahil. Claim
    BİLEREK en son adımda (BUY/STRONG-sinyal/event_id/quote/bütçe kontrollerinin
    HEPSİ geçtikten SONRA, FCM'den HEMEN ÖNCE) alınır — aksi halde ör. geçici
    bir fiyat hatası yüzünden erken alınmış bir claim hiç release edilmeden
    kalıp o event'i sonsuza dek "bildirilecekmiş gibi kilitli" bırakabilirdi.
    """
    if decision.decision != "BUY":
        return False

    analysis_repo = analysis_repo or TechnicalAnalysisRepository()
    analysis = analysis_repo.get_latest(decision.asset)
    if analysis is None or analysis.signal_class != STRONG_NEW_OPPORTUNITY_SIGNAL_CLASS:
        return False
    if not analysis.breakout_event_id:
        return False  # STRONG sinyal ama event_id yok -- savunmacı, normalde oluşmamalı

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

    new_opportunity_log_repo = new_opportunity_log_repo or NewOpportunityNotificationRepository()
    claim_token = new_opportunity_log_repo.claim_new_opportunity(user_id, decision.asset, analysis.breakout_event_id)
    if claim_token is None:
        return False  # Bu SPESİFİK breakout event için zaten claim edilmiş/bildirilmiş

    token_repo = token_repo or FcmTokenRepository()
    sent = _compose_and_send(
        user_id, decision, token_repo, record_repo,
        quantity_held=None, suggested_buy_quantity=suggested_quantity, budget_tl=budget_tl,
    )
    if sent:
        new_opportunity_log_repo.mark_new_opportunity_sent(user_id, decision.asset, analysis.breakout_event_id, claim_token)
    else:
        new_opportunity_log_repo.release_new_opportunity_claim(user_id, decision.asset, analysis.breakout_event_id, claim_token)
    return sent


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
        # NOT: messaging.Message'ın `fid` alanı FCM registration token'ı DEĞİL,
        # farklı bir kimlik türü olan Firebase Installation ID'yi bekliyor
        # (bkz. firebase_admin/_messaging_encoder.py docstring'i). Flutter'daki
        # FirebaseMessaging.instance.getToken() bir FCM registration token
        # döndürüyor — bu yüzden `fid` yerine `token` kullanılmalı, aksi halde
        # gerçek cihazda "NotRegistered" (404) hatası alınır (bkz.
        # KURULUM_GUNLUGU.md AŞAMA 56).
        token=token,
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
