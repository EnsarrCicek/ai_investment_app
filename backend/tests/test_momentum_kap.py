"""Resmi KAP API hazırlığı (ağsız): WAITING_FOR_AUTHORIZATION, yapılandırmasız istek yok, uydurma uç nokta yok, servis
kaydı birebir, alan eşlemeleri UNKNOWN, rol EXPERIMENTAL_SECONDARY, zaman damgaları korunur, Foreks/KAP birleşmez,
holdout ham toplama serbest / sonuç birleştirme yasak, herkese açık KAP kazıyıcısı yok, gizli değer sızmaz,
raw hash deterministik, artımlı toplama checkpoint'i kalıcılaştırmadan sonra ilerler."""

import inspect
import json
import logging
import pkgutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.research.momentum_pilot import split as sp
from app.research.momentum_sources import holdout
from app.research.momentum_sources import kap as kap_pkg
from app.research.momentum_sources.common import SECONDARY_ROLE, SourceContractError, raw_hash
from app.research.momentum_sources.kap import collector as kc
from app.research.momentum_sources.kap import config as kcfg
from app.research.momentum_sources.kap import field_mapping as fm
from app.research.momentum_sources.kap.adapter import KapOfficialAdapter, KapServiceClient
from app.research.momentum_sources.kap.models import KapDisclosure, KapSecurity, symbol_from_company_name
from app.research.momentum_sources.storage import SecondaryStore

UTC = timezone.utc
T = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
SECRET = "kap-secret-key-never-logged"
KAP_DIR = Path(kap_pkg.__file__).parent


def disc(i, **kw):
    base = dict(received_at=T + timedelta(seconds=30 + i), raw_hash=raw_hash({"i": i, **{k: str(v) for k, v in
                                                                                      kw.items()}}),
                disclosure_id=f"D{i}", disclosure_index=i, source_timestamp=T + timedelta(seconds=i), subject=f"s{i}")
    return KapDisclosure(**{**base, **kw})


def test_starts_waiting_for_authorization_and_fails_closed(monkeypatch):
    monkeypatch.setenv("KAP_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("KAP_API_KEY", SECRET)
    a = KapOfficialAdapter()
    assert a.status()["access_state"] == kcfg.WAITING_FOR_AUTHORIZATION
    for call in (a.last_disclosure_index, lambda: a.disclosures_after(0, 5), lambda: a.disclosure_detail("D1"),
                 lambda: a.events(T, T)):
        with pytest.raises(kcfg.KapConfigurationRequired):
            call()
    assert set(kcfg.ACCESS_STATES) == {"NOT_CONFIGURED", "WAITING_FOR_AUTHORIZATION", "READY_FOR_SMOKE_TEST",
                                       "ACTIVE", "ERROR"}


def test_access_state_transitions_only_with_documentation(monkeypatch):
    monkeypatch.setattr(kcfg, "DOCUMENTATION_REF", "official doc v1 (test)")
    c = kcfg.KapConfig(None, kcfg.Secret(None), None)
    assert c.access_state() == kcfg.NOT_CONFIGURED
    c = kcfg.KapConfig("http://x", kcfg.Secret(SECRET), None)
    assert c.access_state() == kcfg.ERROR
    c = kcfg.KapConfig("https://x", kcfg.Secret(SECRET), None)
    assert c.access_state(endpoints_mapped=False) == kcfg.NOT_CONFIGURED
    assert c.access_state(endpoints_mapped=True) == kcfg.READY_FOR_SMOKE_TEST
    assert c.access_state(endpoints_mapped=True, smoke_test_passed=True) == kcfg.ACTIVE


def test_smoke_test_does_not_run_without_configuration(capsys):
    from app.research.momentum_sources.kap import kap_smoke_test
    assert kap_smoke_test.main([]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "NOT ACTIVE" and out["network_calls"] == 0 and out["persist"] is False


def test_official_service_registry_exact_and_no_invented_endpoints():
    assert fm.SERVICE_NAMES == ("disclosures", "disclosureDetail", "downloadAttachment", "lastDisclosureIndex",
                                "members", "memberDetail", "funds", "fundDetail", "memberSecurities",
                                "blockedDisclosures", "caEventStatus")
    for s in fm.SERVICES.values():
        assert s.availability == "CONFIRMED_SERVICE" and s.official_description == "NOT_SUPPLIED"
        assert (s.endpoint_path, s.http_method, s.request_schema, s.response_schema) == ("UNKNOWN",) * 4
        assert not s.mapped
        with pytest.raises(kcfg.KapConfigurationRequired):
            fm.resolve_service(s.service_name)
    assert not fm.endpoints_mapped()
    code = "".join((KAP_DIR / f).read_text(encoding="utf-8") for f in
                   ("config.py", "adapter.py", "collector.py", "field_mapping.py", "models.py", "kap_smoke_test.py"))
    for forbidden in ("http://", "https://www.kap", "kap.org.tr", "/api/", "Authorization:", "X-API-KEY", "apikey=",
                      "requests.", "urllib", "httpx"):
        assert forbidden not in code, forbidden


def test_field_mappings_unknown():
    assert set(fm.unknown_fields()) == set(fm.CANONICAL_FIELDS)
    for f in ("disclosure_id", "published_at", "member_code", "subject", "summary", "symbol", "isin"):
        with pytest.raises(kcfg.KapConfigurationRequired):
            fm.resolve_field(f)
    assert fm.DISCLOSURE_ID_SEMANTICS_CONFIRMED is False


def test_models_role_timestamps_and_no_inference():
    d = disc(1)
    assert d.source_role == SECONDARY_ROLE and d.source_timestamp == T + timedelta(seconds=1)
    assert d.received_at == T + timedelta(seconds=31) and d.archival_discovery_lag == timedelta(seconds=30)
    with pytest.raises(SourceContractError):
        disc(2, source_role="REFERENCE_PRIMARY")
    with pytest.raises(SourceContractError):
        disc(3, received_at=T - timedelta(minutes=1))  # geriye tarihleme yasak
    nots = disc(4, source_timestamp=None)
    assert nots.timestamp_status == "UNVERIFIED" and nots.archival_discovery_lag is None
    sec = KapSecurity(received_at=T, raw_hash=raw_hash("s"), member_code="X")
    assert sec.symbol is None and sec.isin is None and sec.exchange is None
    with pytest.raises(SourceContractError):
        symbol_from_company_name("Akbank T.A.S.")


def test_raw_hash_deterministic():
    assert raw_hash({"b": [1, None], "a": "ş"}) == raw_hash({"a": "ş", "b": [1, None]})


def test_storage_separate_tables_duplicates_and_no_invented_ids(tmp_path):
    s = SecondaryStore(tmp_path)
    assert s.add_kap_disclosure(disc(1)) == "NEW" and s.add_kap_disclosure(disc(1)) == "DUPLICATE"
    changed = disc(1, subject="changed")
    assert s.add_kap_disclosure(changed) == "DUPLICATE_CONFLICT"
    assert s.db.execute("SELECT subject FROM kap_disclosures WHERE disclosure_id='D1'").fetchall() == [("s1",)]
    assert s.db.execute("SELECT error_type FROM kap_failures").fetchall() == [("DUPLICATE_CONFLICT",)]
    with pytest.raises(SourceContractError):
        s.add_kap_disclosure(disc(5, disclosure_id=None))
    row = s.db.execute("SELECT source_timestamp, received_at, source_role FROM kap_disclosures").fetchone()
    assert row == ((T + timedelta(seconds=1)).isoformat(), (T + timedelta(seconds=31)).isoformat(), SECONDARY_ROLE)
    assert s.db.execute("SELECT COUNT(*) FROM news_events").fetchone()[0] == 0  # Foreks tablosuna yazılmadı
    with pytest.raises(Exception):
        s.db.execute("UPDATE kap_disclosures SET subject='x'")
    assert s.integrity()["ok"]
    s.close()


def test_no_foreks_kap_silent_merge(tmp_path):
    from app.research.momentum_sources.news_archive.models import NewsArchiveItem
    s = SecondaryStore(tmp_path)
    s.add_kap_disclosure(disc(1, subject="GARAN pay geri alım"))
    s.add_news(NewsArchiveItem(provider="foreks", source="Foreks", symbol="GARAN", company=None, published_at=T,
                               received_at=T + timedelta(minutes=1), headline="GARAN pay geri alım",
                               event_type="buyback", event_importance=None, source_url_hash=None,
                               content_hash=raw_hash("c"), raw_hash=raw_hash("r"), published_at_semantics="x",
                               item_key="foreks:1"))
    st = s.stats()
    assert st["kap"]["disclosures"] == 1 and st["news_events"]["foreks"]["rows"] == 1
    assert "kap_official" not in st["news_events"]
    s.close()


class FakeClient(KapServiceClient):
    """Test istemcisi (ağ yok): resmi servislerin anlamsal karşılıkları."""

    def __init__(self, remote: int, rows, fail_on_detail=False):
        self.remote, self.rows, self.fail = remote, rows, fail_on_detail

    def last_disclosure_index(self):
        return self.remote

    def disclosures_after(self, index, max_records):
        return [r for r in self.rows if r.disclosure_index > index][:max_records]

    def disclosure_detail(self, disclosure_id):
        if self.fail:
            raise RuntimeError("detail failed")
        return {}


def test_incremental_design_requires_confirmed_id_semantics(tmp_path):
    s = SecondaryStore(tmp_path)
    with pytest.raises(kcfg.KapConfigurationRequired):
        kc.incremental_run(FakeClient(3, [disc(1)]), s, now_fn=lambda: T)
    s.close()


def test_checkpoint_advances_only_after_persistence(tmp_path):
    s = SecondaryStore(tmp_path)
    rows = [disc(i) for i in (1, 2, 3)]
    r = kc.incremental_run(FakeClient(3, rows), s, now_fn=lambda: T + timedelta(minutes=1),
                           id_semantics_confirmed=True)
    assert r["status"] == "BASELINE_ESTABLISHED" and s.kap_checkpoint() == 3  # geçmiş doldurulmaz
    assert s.db.execute("SELECT COUNT(*) FROM kap_disclosures").fetchone()[0] == 0
    more = rows + [disc(4), disc(5)]
    r = kc.incremental_run(FakeClient(5, more), s, now_fn=lambda: T + timedelta(minutes=2),
                           id_semantics_confirmed=True)
    assert r["status"] == "COMPLETED" and r["new"] == 2 and s.kap_checkpoint() == 5
    r = kc.incremental_run(FakeClient(5, more), s, now_fn=lambda: T + timedelta(minutes=3),
                           id_semantics_confirmed=True)
    assert r["status"] == "NO_NEW_DISCLOSURES" and s.kap_checkpoint() == 5
    with pytest.raises(RuntimeError):
        kc.incremental_run(FakeClient(7, more + [disc(6), disc(7)], fail_on_detail=True), s,
                           now_fn=lambda: T + timedelta(minutes=4), fetch_detail=True, id_semantics_confirmed=True)
    assert s.kap_checkpoint() == 5  # başarısız çalıştırmada checkpoint ilerlemez
    assert s.db.execute("SELECT COUNT(*) FROM kap_failures WHERE error_type='RuntimeError'").fetchone()[0] == 1
    s.close()


def test_holdout_raw_collection_allowed_outcome_join_forbidden(tmp_path):
    assert holdout.raw_collection_allowed(date(2026, 11, 4))
    s = SecondaryStore(tmp_path)
    assert s.add_kap_disclosure(disc(1)) == "NEW"  # 2026-11-04 tarihli ham bildirim saklanabilir
    s.close()
    for field in holdout.FORBIDDEN_NEWS_JOINS:
        with pytest.raises(sp.HoldoutAccessError):
            holdout.assert_news_join_allowed(["2026-11-04"], [field])
    src = inspect.getsource(kc)
    for word in ("session_events", "momentum_pilot.deep", "ranking", "mfe", "precision"):
        assert word not in src


def test_no_public_kap_scraper_exists():
    import app.research.momentum_sources as ms
    for m in pkgutil.walk_packages(ms.__path__, ms.__name__ + "."):
        text = Path(__import__(m.name, fromlist=["x"]).__file__).read_text(encoding="utf-8").lower()
        for pattern in ("://kap.org.tr", "://www.kap.org.tr", "kap.org.tr/"):  # kullanım, açıklama değil
            assert pattern not in text, (m.name, pattern)
    kap_code = "".join(p.read_text(encoding="utf-8") for p in KAP_DIR.glob("*.py"))
    for http in ("import requests", "import httpx", "urllib.request", "selenium", "playwright", "BeautifulSoup"):
        assert http not in kap_code, http
    from app.research.momentum_sources.news_archive import adapters as ad
    with pytest.raises(ad.KapSourceNotConfigured):
        ad.KapArchiveAdapter().fetch()


def test_secrets_never_logged(monkeypatch, caplog):
    monkeypatch.setenv("KAP_API_KEY", SECRET)
    monkeypatch.setenv("KAP_BASE_URL", "https://example.invalid")
    a = KapOfficialAdapter()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("t").info("cfg %s %r", a.config, a)
    with pytest.raises(kcfg.KapConfigurationRequired) as e:
        a.last_disclosure_index()
    blob = " ".join([str(a.config), repr(a), json.dumps(a.status(), default=str), str(e.value), caplog.text])
    assert SECRET not in blob and a.config.api_key.reveal() == SECRET


def test_support_contact_documented_not_emailed():
    assert kcfg.SUPPORT_CONTACT == "kapdestek@mkk.com.tr"
    doc = (KAP_DIR / "REQUIRED_ACCESS.md").read_text(encoding="utf-8")
    assert "kapdestek@mkk.com.tr" in doc and "Borsa İstanbul veri dağıtım sözleşmesi" in doc
    code = "".join(p.read_text(encoding="utf-8") for p in KAP_DIR.glob("*.py"))
    assert "smtplib" not in code and "sendmail" not in code
