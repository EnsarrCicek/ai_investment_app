from datetime import datetime, timezone

import pytest

from app.models.ai_decision import AIDecision
from app.models.market_data import Quote
from app.models.technical_analysis import TechnicalAnalysis
from app.services.notifications import fcm_sender


class _FakeTokenRepo:
    def __init__(self, token=None):
        self._token = token

    def get(self, user_id):
        return self._token


class _FakeLogRepo:
    def __init__(self, last_decision=None):
        self._last = last_decision
        self.set_calls = []

    def get_last_decision(self, user_id, asset):
        return self._last

    def set_last_decision(self, user_id, asset, decision):
        self.set_calls.append((user_id, asset, decision))
        self._last = decision


class _FakeRecordRepo:
    def __init__(self):
        self.added = []

    def add(self, record):
        self.added.append(record)
        return "fake-record-id"


@pytest.fixture(autouse=True)
def _no_real_firestore_for_notification_records(monkeypatch):
    # record_repo verilmeyen testler gerçek NotificationRecordRepository()'ye
    # (Firestore) DÜŞMESİN diye modül içindeki varsayılan sınıf referansı
    # sahteyle değiştirilir (bkz. AŞAMA 48/17'deki aynı desen, benchmark_
    # cache_repo için).
    monkeypatch.setattr(fcm_sender, "NotificationRecordRepository", _FakeRecordRepo)


def _decision(decision="BUY", asset="THYAO", final_score=45.0, confidence=70.0, channel_completeness=0.8):
    # HATA 5C-UI4 (31.08.2026): production'da `_compose_and_send()`'e
    # geçirilen `decision` HER ZAMAN `decide_for_asset()`'in TAZE ürettiği
    # bir nesne olduğundan `channel_completeness` HİÇBİR ZAMAN None değildir
    # -- test fixture'ı bu gerçek contract'ı yansıtması için varsayılan bir
    # değer taşır (fabricated fallback DEĞİL, gerçek çağıranın garantisi).
    now = datetime.now(timezone.utc)
    return AIDecision(
        asset=asset,
        created_at=now,
        technical_score=final_score,
        news_score=None,
        macro_score=None,
        technical_weight=0.5,
        news_weight=0.3,
        macro_weight=0.2,
        final_score=final_score,
        decision=decision,
        confidence=confidence,
        channel_completeness=channel_completeness,
        decision_engine_version="1.1.0",
    )


def test_weak_decisions_never_notify():
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="HOLD"), token_repo=_FakeTokenRepo("tok"), log_repo=_FakeLogRepo()
    )
    assert sent is False


def test_no_registered_token_means_no_notification():
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="BUY"), token_repo=_FakeTokenRepo(None), log_repo=_FakeLogRepo()
    )
    assert sent is False


def test_same_decision_is_not_renotified():
    log_repo = _FakeLogRepo(last_decision="BUY")
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="BUY"), token_repo=_FakeTokenRepo("tok"), log_repo=log_repo
    )
    assert sent is False


def test_new_strong_decision_sends_and_logs(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    log_repo = _FakeLogRepo(last_decision=None)
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="SELL", asset="GARAN"), token_repo=_FakeTokenRepo("tok"), log_repo=log_repo
    )

    assert sent is True
    assert len(sent_messages) == 1
    assert sent_messages[0].token == "tok"
    assert log_repo.set_calls == [("u1", "GARAN", "SELL")]


def test_decision_change_renotifies(monkeypatch):
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)

    log_repo = _FakeLogRepo(last_decision="BUY")
    sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="SELL"), token_repo=_FakeTokenRepo("tok"), log_repo=log_repo
    )
    assert sent is True


def test_quantity_held_included_in_notification_body(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="SELL"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        quantity_held=100.0,
    )

    assert "100 adet" in sent_messages[0].notification.body


def test_no_quantity_held_omits_holding_text(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="SELL"), token_repo=_FakeTokenRepo("tok"), log_repo=_FakeLogRepo()
    )

    assert "adet" not in sent_messages[0].notification.body


def test_sell_with_quantity_held_instructs_to_sell(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="SELL", asset="TUPRS"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        quantity_held=50.0,
    )

    body = sent_messages[0].notification.body
    assert "50 adet" in body
    assert "SATMANIZ" in body


def test_suggested_buy_quantity_included_in_notification_body(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="BUY"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        suggested_buy_quantity=25.0,
        budget_tl=5000.0,
    )

    body = sent_messages[0].notification.body
    assert "25 adet" in body
    assert "ALMANIZ" in body
    assert "5000 TL" in body


def test_notification_body_uses_sinyal_mutabakati_and_veri_kapsami_not_guven(monkeypatch):
    """HATA 5C-UI4 (31.08.2026): eski generic "Güven: %XX" ifadesi kaldırıldı
    -- Sinyal Mutabakatı ve Veri Kapsamı AYRI AYRI, half-up rounding'le
    (Flutter ile presentation-eşdeğer) gösterilmeli. `confidence=62.5` için
    Python'un eski `f"{62.5:.0f}"` davranışı "%62" üretirdi (bkz. HATA
    5C-UI3 raporu) -- `format_percent_value` "%63" üretir."""
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="BUY", confidence=62.5, channel_completeness=0.8),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
    )

    body = sent_messages[0].notification.body
    assert "Sinyal Mutabakatı: %63" in body
    assert "Veri Kapsamı: %80" in body
    assert "Güven:" not in body


def test_notification_body_only_one_channel_shows_high_agreement_and_low_coverage_together(monkeypatch):
    """HATA 5C-UI4 madde 4 -- 5C'nin ana semantic invariant'ı: yalnızca tek
    kanal mevcutken Sinyal Mutabakatı yüksek/tam olsa bile Veri Kapsamı bunu
    YANSITMAZ -- ikisi AYNI bildirim body'sinde birlikte görünmeli."""
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="BUY", confidence=100.0, channel_completeness=0.2),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
    )

    body = sent_messages[0].notification.body
    assert "Sinyal Mutabakatı: %100" in body
    assert "Veri Kapsamı: %20" in body


def test_notification_composition_does_not_mutate_stored_decision_values(monkeypatch):
    """HATA 5C-UI4 madde 8 -- bu ticket yalnızca presentation string'i
    değiştirir; `AIDecision.confidence`/`channel_completeness`'ın kendisi
    (stored/calculated numeric değer) HİÇBİR ŞEKİLDE değişmemeli."""
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)

    decision = _decision(decision="BUY", confidence=62.5, channel_completeness=0.8)
    fcm_sender.notify_if_strong_decision(
        "u1", decision, token_repo=_FakeTokenRepo("tok"), log_repo=_FakeLogRepo()
    )

    assert decision.confidence == 62.5
    assert decision.channel_completeness == 0.8


class _FakeAnalysisRepo:
    def __init__(self, analysis: TechnicalAnalysis | None):
        self._analysis = analysis

    def get_latest(self, asset):
        return self._analysis


class _FakeQuoteProvider:
    def __init__(self, last_price: float = 100.0, raise_error: bool = False):
        self._last_price = last_price
        self._raise_error = raise_error

    def get_quote(self, symbol):
        if self._raise_error:
            raise ValueError(f"'{symbol}' için fiyat alınamadı")
        now = datetime.now(timezone.utc)
        return Quote(
            asset_id=symbol,
            timestamp=now,
            last_price=self._last_price,
            previous_close=self._last_price,
            change=0.0,
            change_percent=0.0,
            open=self._last_price,
            high=self._last_price,
            low=self._last_price,
            volume=1000,
            source="fake",
        )


class _FakeSettingsConfigRepo:
    def __init__(self, settings: dict | None = None):
        self._settings = settings

    def get(self, key, defaults):
        return self._settings if self._settings is not None else defaults


_UNSET = object()


def _strong_analysis(
    signal_class: str = "STRONG_BULLISH_INITIATION",
    breakout_event_id: str | None = "THYAO:BULLISH:2026-08-20",
    signal_breakout_event_id=_UNSET,
) -> TechnicalAnalysis:
    # HATA 9B-FIX: `signal_breakout_event_id` varsayılan olarak GENEL
    # `breakout_event_id` ile AYNI değere ayarlanır (yön-özel/genel event'in
    # AYNI olduğu -- gölgelenmenin OLMADIĞI -- normal/yaygın senaryo) -- bu,
    # aşağıdaki mevcut dedupe testlerinin İKİSİNİ de AYRICA güncellemeye
    # gerek kalmadan geçmeye devam etmesini sağlar. Testler bu iki alanı
    # KASITLI OLARAK farklı tutmak istediğinde `signal_breakout_event_id`'yi
    # açıkça geçer (bkz. provenance-specific testler).
    if signal_breakout_event_id is _UNSET:
        signal_breakout_event_id = breakout_event_id
    return TechnicalAnalysis(
        asset="THYAO",
        technical_score=50.0,
        trend="BULLISH",
        confidence=0.9,
        components={},
        indicators={},
        created_at=datetime.now(timezone.utc),
        signal_class=signal_class,
        breakout_event_id=breakout_event_id,
        signal_breakout_event_id=signal_breakout_event_id,
    )


class _FakeNewOpportunityLogRepo:
    """HATA 4B: gerçek `NewOpportunityNotificationRepository`'nin atomic
    claim/mark/release sözleşmesini (her (user,asset,event_id) ÜÇLÜSÜ için
    AYRI bir doküman, `PENDING`/`SENT` durumu, `claim_token` eşleşmesi
    zorunlu) in-memory olarak birebir taklit eden sahte -- gerçek Firestore'a
    dokunmadan davranışı doğrulamak için."""

    def __init__(self):
        self._docs: dict[tuple, dict] = {}
        self.claim_calls = []
        self.sent_calls = []
        self.release_calls = []

    def _key(self, user_id, asset, event_id):
        return (user_id, asset, event_id)

    def claim_new_opportunity(self, user_id, asset, event_id):
        import uuid

        self.claim_calls.append((user_id, asset, event_id))
        key = self._key(user_id, asset, event_id)
        if key in self._docs:
            return None  # AlreadyExists eşdeğeri
        token = uuid.uuid4().hex
        self._docs[key] = {"status": "PENDING", "claim_token": token}
        return token

    def mark_new_opportunity_sent(self, user_id, asset, event_id, claim_token):
        self.sent_calls.append((user_id, asset, event_id, claim_token))
        key = self._key(user_id, asset, event_id)
        doc = self._docs.get(key)
        if doc is not None and doc["status"] == "PENDING" and doc["claim_token"] == claim_token:
            doc["status"] = "SENT"

    def release_new_opportunity_claim(self, user_id, asset, event_id, claim_token):
        self.release_calls.append((user_id, asset, event_id, claim_token))
        key = self._key(user_id, asset, event_id)
        doc = self._docs.get(key)
        if doc is not None and doc["status"] == "PENDING" and doc["claim_token"] == claim_token:
            del self._docs[key]


def test_new_opportunity_skipped_when_decision_is_not_buy():
    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="SELL"), analysis_repo=_FakeAnalysisRepo(_strong_analysis())
    )
    assert sent is False


def test_new_opportunity_skipped_without_cached_analysis():
    sent = fcm_sender.notify_if_new_opportunity("u1", _decision(decision="BUY"), analysis_repo=_FakeAnalysisRepo(None))
    assert sent is False


def test_new_opportunity_skipped_when_signal_class_not_strong():
    analysis = _strong_analysis(signal_class="BULLISH_CANDIDATE")
    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY"), analysis_repo=_FakeAnalysisRepo(analysis)
    )
    assert sent is False


def test_new_opportunity_skipped_when_no_breakout_event_id():
    # HATA 4B -> HATA 9B-FIX: STRONG sinyal ama provenance
    # (`signal_breakout_event_id`) yok (savunmacı kontrol) -- normalde
    # oluşmaz (STRONG_BULLISH_INITIATION zaten confirmed BULLISH breakout
    # gerektirir) ama provenance'sız dedupe imkansız olacağından açıkça
    # bloklanır. Genel `breakout_event_id`'ye ASLA fallback YAPILMAZ (bkz.
    # aşağıdaki AYRI provenance testleri, HATA 9B2).
    analysis = _strong_analysis(breakout_event_id=None)
    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY"), analysis_repo=_FakeAnalysisRepo(analysis)
    )
    assert sent is False


def test_new_opportunity_skipped_when_signal_breakout_event_id_is_none_even_if_generic_exists(monkeypatch):
    # HATA 9B2 invariant: genel `breakout_event_id` DOLU olsa bile (ör.
    # gölgeleyen bir BEARISH event genel seçimi kazandığından), STRONG
    # sinyali GERÇEKTEN üreten event'in provenance'ı (`signal_breakout_
    # event_id`) yoksa bildirim GÖNDERİLMEZ ve genele ASLA fallback
    # YAPILMAZ -- aksi halde HATA 9B2'nin kanıtladığı yanlış-event dedupe
    # hatası geri gelirdi.
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    log_repo = _FakeNewOpportunityLogRepo()
    analysis = _strong_analysis(breakout_event_id="THYAO:BEARISH:2026-08-20", signal_breakout_event_id=None)

    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )

    assert sent is False
    assert log_repo.claim_calls == []  # genel event_id ile dedupe DENENMEDİ bile


def test_new_opportunity_uses_signal_breakout_event_id_not_generic_when_they_differ(monkeypatch):
    # HATA 9B2 invariant: signal_class'ı GERÇEKTEN üreten (yön-özel) event
    # farklı olduğunda, dedupe/claim GENEL `breakout_event_id`yi DEĞİL,
    # `signal_breakout_event_id`yi kullanmalı.
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    log_repo = _FakeNewOpportunityLogRepo()
    generic_id = "THYAO:BEARISH:2026-08-20"  # gölgeleyen, daha yeni event (genel seçim)
    signal_id = "THYAO:BULLISH:2026-08-15"  # signal_class'ı GERÇEKTEN üreten, gölgelenmiş event
    analysis = _strong_analysis(breakout_event_id=generic_id, signal_breakout_event_id=signal_id)

    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )

    assert sent is True
    assert log_repo.claim_calls == [("u1", "THYAO", signal_id)]  # GENEL id ASLA kullanılmadı
    assert ("u1", "THYAO", generic_id) not in log_repo._docs
    assert log_repo._docs[("u1", "THYAO", signal_id)]["status"] == "SENT"


def test_new_opportunity_skipped_when_quote_unavailable():
    sent = fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(raise_error=True),
        new_opportunity_log_repo=_FakeNewOpportunityLogRepo(),
    )
    assert sent is False


def test_new_opportunity_sends_with_computed_quantity(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    sent = fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(last_price=200.0),
        config_repo=_FakeSettingsConfigRepo({"default_trade_budget_tl": 1000.0}),
        token_repo=_FakeTokenRepo("tok"),
        new_opportunity_log_repo=_FakeNewOpportunityLogRepo(),
    )

    assert sent is True
    body = sent_messages[0].notification.body
    assert "5 adet" in body  # 1000 TL / 200 TL = 5 adet
    assert "1000 TL" in body


def test_new_opportunity_uses_default_budget_when_not_configured(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(last_price=100.0),
        config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"),
        new_opportunity_log_repo=_FakeNewOpportunityLogRepo(),
    )

    body = sent_messages[0].notification.body
    assert "50 adet" in body  # varsayılan 5000 TL / 100 TL = 50 adet


# ---------------------------------------------------------------------------
# HATA 4B (27.08.2026) — event-specific dedupe. Bkz. breakout_timeline.py ve
# NewOpportunityNotificationRepository docstring'leri: notify_if_new_
# opportunity() artık notify_if_strong_decision()'ın PAYLAŞILAN
# (user,asset)->last_decision dedupe'unu KULLANMIYOR, kendi AYRI
# breakout_event_id bazlı dedupe'unu kullanıyor.
# ---------------------------------------------------------------------------


def test_new_opportunity_same_event_id_is_not_renotified(monkeypatch):
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    log_repo = _FakeNewOpportunityLogRepo()
    event_id = "THYAO:BULLISH:2026-08-20"
    token = log_repo.claim_new_opportunity("u1", "THYAO", event_id)
    log_repo.mark_new_opportunity_sent("u1", "THYAO", event_id, token)  # önceden zaten SENT

    sent = fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis(breakout_event_id=event_id)),
        provider=_FakeQuoteProvider(),
        config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"),
        new_opportunity_log_repo=log_repo,
    )

    assert sent is False


def test_new_opportunity_new_event_id_sends_again(monkeypatch):
    # AYNI symbol/decision, ama event_id FARKLI (event1 çözüldü, event2 yeni
    # confirmed oldu) -- eski decision-bazlı dedupe bunu yanlışlıkla
    # bastırırdı (decision hâlâ "BUY"), event-specific dedupe göndermeli.
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))
    log_repo = _FakeNewOpportunityLogRepo()
    old_event_id = "THYAO:BULLISH:2026-06-01"
    token = log_repo.claim_new_opportunity("u1", "THYAO", old_event_id)
    log_repo.mark_new_opportunity_sent("u1", "THYAO", old_event_id, token)  # event1 zaten SENT

    sent = fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis(breakout_event_id="THYAO:BULLISH:2026-08-20")),
        provider=_FakeQuoteProvider(),
        config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"),
        new_opportunity_log_repo=log_repo,
    )

    assert sent is True
    assert len(sent_messages) == 1
    assert log_repo._docs[("u1", "THYAO", "THYAO:BULLISH:2026-08-20")]["status"] == "SENT"


def test_new_opportunity_event1_then_event2_then_event1_fallback_is_suppressed(monkeypatch):
    # HATA 4B pre-commit audit'inde kanıtlanan asıl bug: event1 SENT, sonra
    # event2 SENT, sonra live selector (event2 INVALIDATED olup düştüğü için)
    # event1'e GERİ DÖNER (breakout_timeline'da ayrıca kilitlenen davranış) --
    # event1 zaten bir kez bildirilmiş olduğundan İKİNCİ KEZ GÖNDERİLMEMELİ.
    # Eski last-only repository bunu YANLIŞ yapıyordu (event2'nin kaydı
    # event1'inkini overwrite ettiği için); yeni per-event doküman modeli bunu
    # yapısal olarak engeller.
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))
    log_repo = _FakeNewOpportunityLogRepo()
    event1 = "THYAO:BULLISH:2026-08-01"
    event2 = "THYAO:BULLISH:2026-08-08"

    sent1 = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis(breakout_event_id=event1)),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    sent2 = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis(breakout_event_id=event2)),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    # Live selection event1'e geri döner (breakout_timeline testinde ayrıca kilitlendi) -- aynı event1 tekrar sorulur.
    sent1_fallback = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis(breakout_event_id=event1)),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )

    assert sent1 is True
    assert sent2 is True
    assert sent1_fallback is False  # ZORUNLU: event1 ikinci kez GÖNDERİLMEMELİ
    assert len(sent_messages) == 2


def test_new_opportunity_concurrent_claim_only_one_succeeds():
    # Aynı (user,asset,event_id) için "eşzamanlı" iki claim -- gerçek
    # Firestore create() precondition'ının deterministic eşdeğeri: yalnız
    # BİRİ claim'i kazanabilir, ikincisi FCM gönderim aşamasına HİÇ geçemez.
    log_repo = _FakeNewOpportunityLogRepo()
    event_id = "THYAO:BULLISH:2026-08-20"

    token_a = log_repo.claim_new_opportunity("u1", "THYAO", event_id)
    token_b = log_repo.claim_new_opportunity("u1", "THYAO", event_id)  # "eşzamanlı" ikinci çağrı

    assert token_a is not None
    assert token_b is None  # ikinci caller FCM'e HİÇ ilerleyemez


def test_new_opportunity_send_failure_releases_claim_for_retry(monkeypatch):
    from firebase_admin import exceptions as firebase_exceptions

    def _raise(message):
        raise firebase_exceptions.UnavailableError("gecici hata")

    monkeypatch.setattr(fcm_sender.messaging, "send", _raise)
    log_repo = _FakeNewOpportunityLogRepo()
    event_id = "THYAO:BULLISH:2026-08-20"
    analysis = _strong_analysis(breakout_event_id=event_id)

    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    assert sent is False
    assert ("u1", "THYAO", event_id) not in log_repo._docs  # claim RELEASE edildi -- sonsuza dek kilitlenmedi

    # Gerçek FCM gönderimi bu kez BAŞARILI olsun -- retry başarıyla gönderebilmeli.
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    sent_retry = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    assert sent_retry is True


def test_new_opportunity_send_failure_releases_signal_event_id_not_generic(monkeypatch):
    # HATA 9B-FIX PRE-COMMIT BLOCKER, madde 5: generic ve signal-provenance
    # event id'leri KASITLI OLARAK FARKLI (gölgeleme senaryosu) -- claim
    # BULLISH-A ile başarılı olmalı, FCM gönderimi BAŞARISIZ olunca release
    # de AYNI BULLISH-A için çağrılmalı (BEARISH-B için ASLA), ve BULLISH-A'nın
    # PENDING claim'i gerçekten silinip retry'ın başarılı olabilmesi
    # sağlanmalı (HATA 4B retry semantics'i korunmalı).
    from firebase_admin import exceptions as firebase_exceptions

    def _raise(message):
        raise firebase_exceptions.UnavailableError("gecici hata")

    monkeypatch.setattr(fcm_sender.messaging, "send", _raise)
    log_repo = _FakeNewOpportunityLogRepo()
    generic_id = "THYAO:BEARISH:2026-08-20"  # gölgeleyen, genel event -- ASLA claim/release edilmemeli
    signal_id = "THYAO:BULLISH:2026-08-15"  # signal_class'ı GERÇEKTEN üreten event
    analysis = _strong_analysis(breakout_event_id=generic_id, signal_breakout_event_id=signal_id)

    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )

    assert sent is False
    assert log_repo.claim_calls == [("u1", "THYAO", signal_id)]  # yalnızca BULLISH-A claim edildi
    assert log_repo.release_calls == [("u1", "THYAO", signal_id, log_repo.release_calls[0][3])]  # release de AYNI id ile
    assert ("u1", "THYAO", signal_id) not in log_repo._docs  # PENDING claim silindi -- sonsuza dek kilitlenmedi
    assert ("u1", "THYAO", generic_id) not in log_repo._docs  # genel id'ye HİÇ dokunulmadı

    # Retry: FCM bu kez başarılı olsun -- AYNI (signal_id) event için başarıyla gönderebilmeli.
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    sent_retry = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    assert sent_retry is True
    assert log_repo._docs[("u1", "THYAO", signal_id)]["status"] == "SENT"


def test_new_opportunity_sent_document_is_never_released():
    # Yanlışlıkla (ör. eski/gecikmiş bir çağrı) AYNI token'la release
    # çağrılsa bile, zaten SENT olmuş bir doküman SİLİNMEMELİ.
    log_repo = _FakeNewOpportunityLogRepo()
    event_id = "THYAO:BULLISH:2026-08-20"
    token = log_repo.claim_new_opportunity("u1", "THYAO", event_id)
    log_repo.mark_new_opportunity_sent("u1", "THYAO", event_id, token)
    assert log_repo._docs[("u1", "THYAO", event_id)]["status"] == "SENT"

    log_repo.release_new_opportunity_claim("u1", "THYAO", event_id, token)  # yanlışlıkla çağrıldı

    assert ("u1", "THYAO", event_id) in log_repo._docs
    assert log_repo._docs[("u1", "THYAO", event_id)]["status"] == "SENT"


def test_new_opportunity_buy_sell_buy_same_event_id_suppressed_second_time(monkeypatch):
    # HATA 4B audit'inde kanıtlanan köşe durum: decision BUY->SELL->BUY
    # dalgalansa bile, AYNI breakout_event_id için new-opportunity ikinci kez
    # gönderilmemeli (regular notify_if_strong_decision dedupe'undan TAMAMEN
    # bağımsız çalışır).
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    log_repo = _FakeNewOpportunityLogRepo()
    analysis = _strong_analysis(breakout_event_id="THYAO:BULLISH:2026-08-20")

    sent1 = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    # Regular strong-decision dedupe SELL/BUY döngüsü -- notify_if_new_opportunity'yi ETKİLEMEMELİ
    fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="SELL", asset="THYAO"), token_repo=_FakeTokenRepo("tok"), log_repo=_FakeLogRepo()
    )
    sent2 = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(analysis),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )

    assert sent1 is True
    assert sent2 is False  # aynı event_id -- ikinci new-opportunity bastırılmalı, SELL arada ne olursa olsun


def test_new_opportunity_does_not_touch_regular_decision_log(monkeypatch):
    # HATA 4B'nin düzelttiği cross-suppression: new-opportunity artık
    # regular (user,asset)->last_decision kaydına HİÇ YAZMIYOR/OKUMUYOR.
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    regular_log_repo = _FakeLogRepo(last_decision=None)

    fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(),
        config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"),
        new_opportunity_log_repo=_FakeNewOpportunityLogRepo(),
    )

    assert regular_log_repo.set_calls == []
    assert regular_log_repo._last is None


def test_prior_regular_strong_decision_no_longer_suppresses_new_opportunity(monkeypatch):
    # HATA 4B'nin düzelttiği asıl bug: önceden notify_if_strong_decision()'ın
    # AYNI (user,asset) için "BUY" yazması, sonraki new-opportunity
    # bildirimini SESSİZCE bastırıyordu (shared dedupe key). Artık AYRI
    # dedupe'lar sayesinde bu olmamalı.
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))

    regular_sent = fcm_sender.notify_if_strong_decision(
        "u1", _decision(decision="BUY", asset="THYAO"), token_repo=_FakeTokenRepo("tok"), log_repo=_FakeLogRepo()
    )
    opportunity_sent = fcm_sender.notify_if_new_opportunity(
        "u1",
        _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_analysis()),
        provider=_FakeQuoteProvider(),
        config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"),
        new_opportunity_log_repo=_FakeNewOpportunityLogRepo(),
    )

    assert regular_sent is True
    assert opportunity_sent is True  # ARTIK bastırılmıyor
    assert len(sent_messages) == 2


def test_notify_if_strong_decision_persists_notification_record(monkeypatch):
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    record_repo = _FakeRecordRepo()

    fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="SELL", asset="GARAN"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        quantity_held=10.0,
        record_repo=record_repo,
    )

    assert len(record_repo.added) == 1
    record = record_repo.added[0]
    assert record.user_id == "u1"
    assert record.asset == "GARAN"
    assert record.kind == "SELL"
    assert "SATMANIZ" in record.body


def test_failed_send_does_not_persist_notification_record(monkeypatch):
    def _raise(message):
        from firebase_admin import exceptions as firebase_exceptions

        raise firebase_exceptions.UnavailableError("gecici hata")

    monkeypatch.setattr(fcm_sender.messaging, "send", _raise)
    record_repo = _FakeRecordRepo()

    sent = fcm_sender.notify_if_strong_decision(
        "u1",
        _decision(decision="SELL"),
        token_repo=_FakeTokenRepo("tok"),
        log_repo=_FakeLogRepo(),
        record_repo=record_repo,
    )

    assert sent is False
    assert record_repo.added == []


def test_send_test_notification_returns_false_without_token():
    sent = fcm_sender.send_test_notification("u1", token_repo=_FakeTokenRepo(None))
    assert sent is False


def test_send_test_notification_sends_and_persists_record(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))
    record_repo = _FakeRecordRepo()

    sent = fcm_sender.send_test_notification("u1", token_repo=_FakeTokenRepo("tok"), record_repo=record_repo)

    assert sent is True
    assert len(sent_messages) == 1
    assert sent_messages[0].token == "tok"
    assert len(record_repo.added) == 1
    assert record_repo.added[0].kind == "TEST"
    assert record_repo.added[0].asset is None


def test_send_test_notification_returns_false_on_firebase_error(monkeypatch):
    def _raise(message):
        from firebase_admin import exceptions as firebase_exceptions

        raise firebase_exceptions.UnavailableError("gecici hata")

    monkeypatch.setattr(fcm_sender.messaging, "send", _raise)
    record_repo = _FakeRecordRepo()

    sent = fcm_sender.send_test_notification("u1", token_repo=_FakeTokenRepo("tok"), record_repo=record_repo)

    assert sent is False
    assert record_repo.added == []


# ---------------------------------------------------------------------------
# TECH-VOL 1B (23.09.2026) — STRONG artık yüksek hacim gerektirmiyor.
# fcm_sender DAVRANIŞ kodu DEĞİŞMEDİ (signal_class'ı tüketir); bu testler
# düzeltilmiş sınıflandırıcıdan gelen hacimsiz bir STRONG'un uygunluğa
# ulaşabildiğini ve BUY kapısı + HATA 4B claim/dedupe yaşam döngüsünün
# aynen korunduğunu kanıtlar.
# ---------------------------------------------------------------------------


def _strong_without_high_volume_analysis(event_id: str = "THYAO:BULLISH:2026-09-01") -> TechnicalAnalysis:
    from app.engines.technical.breakout import BreakoutEvent
    from app.engines.technical.signal_classifier import SignalInputs, classify_signal
    from app.engines.technical.support_resistance import SRZone

    zone = SRZone(type="RESISTANCE", low=98.0, high=100.0, touch_count=3, last_touch_index=10)
    inputs = SignalInputs(
        technical_score=50.0, market_structure="UPTREND",
        breakout_event=BreakoutEvent(index=10, direction="BULLISH", zone=zone, breakout_atr=2.0, confirmed=True),
        relative_volume_class="NORMAL", mtf_aligned=True, mtf_consensus="UP",
    )
    signal_class = classify_signal(inputs)
    assert signal_class == "STRONG_BULLISH_INITIATION"  # 1.15.0: NORMAL hacimle STRONG
    analysis = _strong_analysis(signal_class=signal_class, breakout_event_id=event_id)
    return analysis.model_copy(update={"relative_volume_class": "NORMAL"})


def test_corrected_strong_without_high_volume_reaches_new_opportunity_eligibility(monkeypatch):
    sent_messages = []
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: sent_messages.append(message))
    log_repo = _FakeNewOpportunityLogRepo()

    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_without_high_volume_analysis()),
        provider=_FakeQuoteProvider(last_price=100.0), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )

    assert sent is True and len(sent_messages) == 1
    assert log_repo.claim_calls == [("u1", "THYAO", "THYAO:BULLISH:2026-09-01")]


@pytest.mark.parametrize("decision", ["SELL", "HOLD", "WEAK_BUY", "WEAK_SELL"])
def test_corrected_strong_without_high_volume_still_requires_decision_buy(monkeypatch, decision):
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: pytest.fail("gönderim olmamalı"))
    log_repo = _FakeNewOpportunityLogRepo()
    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision=decision, asset="THYAO"),
        analysis_repo=_FakeAnalysisRepo(_strong_without_high_volume_analysis()),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    assert sent is False and log_repo.claim_calls == []


def test_corrected_strong_same_event_is_not_renotified_dedupe_lifecycle_unchanged(monkeypatch):
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: None)
    log_repo = _FakeNewOpportunityLogRepo()
    kwargs = dict(
        analysis_repo=_FakeAnalysisRepo(_strong_without_high_volume_analysis()),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=log_repo,
    )
    first = fcm_sender.notify_if_new_opportunity("u1", _decision(decision="BUY", asset="THYAO"), **kwargs)
    second = fcm_sender.notify_if_new_opportunity("u1", _decision(decision="BUY", asset="THYAO"), **kwargs)
    assert (first, second) == (True, False)
    assert len(log_repo.sent_calls) == 1


def test_historical_stored_signal_class_is_consumed_as_is_not_reclassified(monkeypatch):
    # 1.14.0 döneminde kaydedilmiş bir BULLISH_CONFIRMED (hacim kapısı yüzünden)
    # TARİHSEL OLGUDUR: fcm_sender kayıtlı signal_class'ı okur, yeniden
    # sınıflandırmaz -> eski kayıt STRONG sayılmaz, bildirim gitmez.
    monkeypatch.setattr(fcm_sender.messaging, "send", lambda message: pytest.fail("gönderim olmamalı"))
    old = _strong_analysis(signal_class="BULLISH_CONFIRMED").model_copy(
        update={"engine_version": "1.14.0", "relative_volume_class": "NORMAL"})
    sent = fcm_sender.notify_if_new_opportunity(
        "u1", _decision(decision="BUY", asset="THYAO"), analysis_repo=_FakeAnalysisRepo(old),
        provider=_FakeQuoteProvider(), config_repo=_FakeSettingsConfigRepo(None),
        token_repo=_FakeTokenRepo("tok"), new_opportunity_log_repo=_FakeNewOpportunityLogRepo(),
    )
    assert sent is False and old.signal_class == "BULLISH_CONFIRMED" and old.engine_version == "1.14.0"
