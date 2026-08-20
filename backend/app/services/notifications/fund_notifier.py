"""Fon bildirimleri — AŞAMA 58. fcm_sender.py'deki deseni izler (`token=`
FCM registration token, `fid` DEĞİL — bkz. AŞAMA 56) ama fon tarafına özgü
üç bildirim türü ekler:

1) Aylık öneri (notify_monthly_allocation): kullanıcının ayarladığı aylık
   bütçeyi en iyi sıralanan fonlara dağıtıp önerir. Scheduler olmadığından
   (bkz. fcm_sender.py modül docstring'i) GET /funds her çağrıldığında "bu ay
   zaten bildirildi mi" kontrolü yapılır — kullanıcı ayın ilk gününden SONRA
   ilk kez Fonlar sayfasını açtığında tetiklenir, tam gece yarısı değil (aynı
   mimari sözleşme: kullanıcı eylemiyle tetiklenir).

2) Ad-hoc/"ekstra para" önerisi (notify_ad_hoc_allocation): kullanıcı Fonlar
   sayfasındaki butona anlık bir tutar girip bastığında — dedup YOK, her
   basışta yeniden hesaplanıp gönderilir (send_test_notification ile aynı
   ruh: kullanıcının kendi açık eylemi, istediği kadar deneyebilir).

3) Fon değiştirme önerisi (notify_switch_recommendations): kullanıcının
   tuttuğu her fon için, o fonun güncel skoru en iyi fondan ANLAMLI ÖLÇÜDE
   düşükse "bunu satıp şuna geçmeyi düşünebilirsiniz" bildirimi — aynı öneri
   aynı gün tekrar gönderilmez (dedup).

ÖNEMLİ SINIR: Bu modül YALNIZCA bildirim gönderir, gerçek bir alım-satım
YAPMAZ — TEFAS'a genel kullanıcılar için açık bir işlem-emri API'si yok
(bkz. KURULUM_GUNLUGU.md AŞAMA 58). Kullanıcı önerilen alımı kendi
banka/aracı kurum uygulamasından yapar.
"""

from datetime import datetime, timezone

from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from app.models.fund_analysis import FundAnalysis
from app.models.notification_record import NotificationRecord
from app.repositories.fcm_token_repository import FcmTokenRepository
from app.repositories.fund_notification_log_repository import FundNotificationLogRepository
from app.repositories.notification_record_repository import NotificationRecordRepository
from app.services.funds.allocation import recommend_allocation

# Bir tutulan fonun skoru, en iyi fonun skorundan bu kadar (mutlak puan) düşükse
# "değiştir" önerisi tetiklenir — küçük farklar için gereksiz bildirim spam'i
# olmasın diye bilinçli olarak belirgin bir eşik.
SWITCH_SCORE_GAP_THRESHOLD = 15.0


def _send_fcm(token: str, title: str, body: str) -> bool:
    message = messaging.Message(notification=messaging.Notification(title=title, body=body), token=token)
    try:
        messaging.send(message)
    except firebase_exceptions.FirebaseError:
        return False
    return True


def _format_allocation_body(allocation: list[dict]) -> str:
    return " · ".join(f"{a['fund_code']}: ~{a['amount_tl']:.0f} TL" for a in allocation)


def _notify_allocation(
    user_id: str,
    title: str,
    kind: str,
    allocation: list[dict],
    token_repo: FcmTokenRepository,
    record_repo: NotificationRecordRepository,
) -> bool:
    if not allocation:
        return False
    token = token_repo.get(user_id)
    if not token:
        return False
    body = _format_allocation_body(allocation)
    if not _send_fcm(token, title, body):
        return False
    record_repo.add(
        NotificationRecord(
            user_id=user_id, asset=None, kind=kind, title=title, body=body, created_at=datetime.now(timezone.utc)
        )
    )
    return True


def notify_monthly_allocation(
    user_id: str,
    ranked_funds: list[FundAnalysis],
    budget_tl: float,
    token_repo: FcmTokenRepository | None = None,
    log_repo: FundNotificationLogRepository | None = None,
    record_repo: NotificationRecordRepository | None = None,
) -> bool:
    log_repo = log_repo or FundNotificationLogRepository()
    year_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if log_repo.get_last_monthly_notified(user_id) == year_month:
        return False
    if budget_tl <= 0:
        return False

    allocation = recommend_allocation(ranked_funds, budget_tl)
    sent = _notify_allocation(
        user_id,
        "Aylık Fon Önerisi",
        "FUND_BUY_MONTHLY",
        allocation,
        token_repo or FcmTokenRepository(),
        record_repo or NotificationRecordRepository(),
    )
    if sent:
        log_repo.set_last_monthly_notified(user_id, year_month)
    return sent


def notify_ad_hoc_allocation(
    user_id: str,
    ranked_funds: list[FundAnalysis],
    amount_tl: float,
    token_repo: FcmTokenRepository | None = None,
    record_repo: NotificationRecordRepository | None = None,
) -> bool:
    allocation = recommend_allocation(ranked_funds, amount_tl)
    return _notify_allocation(
        user_id,
        "Fon Alım Önerisi",
        "FUND_BUY_ADHOC",
        allocation,
        token_repo or FcmTokenRepository(),
        record_repo or NotificationRecordRepository(),
    )


def notify_switch_recommendations(
    user_id: str,
    held_fund_scores: dict[str, float],
    ranked_funds: list[FundAnalysis],
    token_repo: FcmTokenRepository | None = None,
    log_repo: FundNotificationLogRepository | None = None,
    record_repo: NotificationRecordRepository | None = None,
) -> int:
    """Her tutulan fon için en iyi alternatifle karşılaştırıp gerekiyorsa
    bildirim gönderir. Kaç bildirim gönderildiğini döner (0 = hiçbiri gerekmedi).
    """
    if not ranked_funds or not held_fund_scores:
        return 0

    log_repo = log_repo or FundNotificationLogRepository()
    token_repo = token_repo or FcmTokenRepository()
    record_repo = record_repo or NotificationRecordRepository()
    best_fund = ranked_funds[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    sent_count = 0
    for held_code, held_score in held_fund_scores.items():
        if held_code == best_fund.fund_code:
            continue
        gap = best_fund.composite_score - held_score
        if gap < SWITCH_SCORE_GAP_THRESHOLD:
            continue

        last = log_repo.get_last_switch_suggestion(user_id, held_code)
        if last is not None and last.get("suggested_code") == best_fund.fund_code and last.get("date") == today:
            continue

        token = token_repo.get(user_id)
        if not token:
            continue

        title = "Fon Değiştirme Önerisi"
        body = (
            f"{held_code} son dönemde zayıf performans gösteriyor ({held_score:+.1f} puan). "
            f"{best_fund.fund_code} ({best_fund.composite_score:+.1f} puan) daha iyi bir alternatif olabilir."
        )
        if not _send_fcm(token, title, body):
            continue

        record_repo.add(
            NotificationRecord(
                user_id=user_id,
                asset=held_code,
                kind="FUND_SWITCH",
                title=title,
                body=body,
                created_at=datetime.now(timezone.utc),
            )
        )
        log_repo.set_last_switch_suggestion(user_id, held_code, best_fund.fund_code, today)
        sent_count += 1

    return sent_count
