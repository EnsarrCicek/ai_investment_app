"""İkincil depo çakışma kaydı (regresyon): kaynak bir öğeyi bir kez düzenleyip sonraki her getirmede aynı düzenlenmiş
hali döndürdüğünde DUPLICATE_CONFLICT yalnız BİR kez kaydedilir (sonrası DUPLICATE_CONFLICT_KNOWN); farklı yeni bir
düzenleme yine kaydedilir; orijinal kayıt hiçbir durumda değişmez."""

import hashlib
from datetime import datetime, timedelta, timezone

from app.research.momentum_sources.common import raw_hash
from app.research.momentum_sources.kap.models import KapDisclosure
from app.research.momentum_sources.matriks.models import TradeTick
from app.research.momentum_sources.news_archive.models import NewsArchiveItem
from app.research.momentum_sources.storage import CONFLICT_KNOWN, SecondaryStore

UTC = timezone.utc
T = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def news(head, minutes=0):
    return NewsArchiveItem(provider="foreks", source="Foreks", symbol="UNRESOLVED", company=None, published_at=T,
                           received_at=T + timedelta(minutes=minutes), headline=head, event_type="other",
                           event_importance=None, source_url_hash=None,
                           content_hash=hashlib.sha256(head.encode()).hexdigest(),
                           raw_hash=raw_hash({"h": head}), published_at_semantics="x", item_key="foreks:abc")


def test_news_conflict_logged_once_per_distinct_revision(tmp_path):
    s = SecondaryStore(tmp_path)
    assert s.add_news(news("Lagarde: iklim maliyetleri artıyor, Avrupa acil önlem")) == "NEW"
    edited = news("Lagarde: Avrupa acil önlem almalı", 5)
    assert s.add_news(edited) == "DUPLICATE_CONFLICT"
    for k in range(5):  # sonraki getirmeler aynı düzenlenmiş hali döndürür
        assert s.add_news(news("Lagarde: Avrupa acil önlem almalı", 10 + 5 * k)) == CONFLICT_KNOWN
    assert s.add_news(news("Lagarde: Avrupa'ya çağrı", 60)) == "DUPLICATE_CONFLICT"  # yeni, farklı düzenleme
    rows = s.db.execute("SELECT COUNT(*) FROM source_failures WHERE error_type='DUPLICATE_CONFLICT'").fetchone()[0]
    assert rows == 2
    assert s.db.execute("SELECT headline FROM news_events").fetchall() == [
        ("Lagarde: iklim maliyetleri artıyor, Avrupa acil önlem",)]
    s.close()


def test_trade_and_kap_conflicts_logged_once(tmp_path):
    s = SecondaryStore(tmp_path)

    def tick(price):
        return TradeTick(provider="matriks", symbol="AKBNK", received_at=T + timedelta(seconds=1), price=price,
                         quantity=10.0, raw_hash=raw_hash({"p": price}), source_timestamp=T, trade_id="t1")
    assert s.add_trade(tick(60.0)) == "NEW"
    assert s.add_trade(tick(61.0)) == "DUPLICATE_CONFLICT"
    assert s.add_trade(tick(61.0)) == CONFLICT_KNOWN

    def disc(subject):
        return KapDisclosure(received_at=T + timedelta(seconds=30), raw_hash=raw_hash({"s": subject}),
                             disclosure_id="D1", source_timestamp=T, subject=subject)
    assert s.add_kap_disclosure(disc("a")) == "NEW"
    assert s.add_kap_disclosure(disc("b")) == "DUPLICATE_CONFLICT"
    assert s.add_kap_disclosure(disc("b")) == CONFLICT_KNOWN
    assert s.db.execute("SELECT COUNT(*) FROM source_failures").fetchone()[0] == 1
    assert s.db.execute("SELECT COUNT(*) FROM kap_failures").fetchone()[0] == 1
    assert s.db.execute("SELECT price FROM trade_ticks").fetchall() == [(60.0,)]
    assert s.db.execute("SELECT subject FROM kap_disclosures").fetchall() == [("a",)]
    s.close()
