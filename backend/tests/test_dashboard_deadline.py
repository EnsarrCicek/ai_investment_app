"""Dashboard süre bütçesi ve süreç genelinde eşzamanlılık sınırı.

Gerçek ağ/Firestore yok. Yavaş semboller test sonunda serbest bırakılan bir `threading.Event` üzerinde bekler; duvar
saati yalnız küçük bir bütçe kadar (kesirli saniye) harcanır. Ön yükleme süresi sahte saatle simüle edilir. Her test
kendi havuzunu kullanır (süreç geneli havuz testler arasında kirlenmez) ve sonunda havuzu kapatır.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from google.api_core.exceptions import ResourceExhausted

from app.services.decisions import dashboard as db
from tests.test_dashboard_quota import NOW, SYMBOLS, Macro, dashboard_client, deps

BUDGET = 0.3


class Behaviour:
    """Sembol başına davranış: fast | hang | boom | quota. Tüm istekler boyunca eşzamanlılık tepe değerini kaydeder."""

    def __init__(self, plan):
        self.plan, self.release = plan, threading.Event()
        self.lock, self.running, self.peak = threading.Lock(), 0, 0
        self.started, self.finished = [], []

    def factory(self, config_repo, analysis_repo, benchmark_repo):
        behaviour = self

        class Engine:
            def analyze_with_id(self, symbol, persist=True):
                with behaviour.lock:
                    behaviour.started.append(symbol)
                    behaviour.running += 1
                    behaviour.peak = max(behaviour.peak, behaviour.running)
                try:
                    kind = behaviour.plan(symbol)
                    if kind == "hang":
                        behaviour.release.wait(timeout=10)
                    elif kind == "boom":
                        raise RuntimeError("teknik hesaplama hatası")
                    elif kind == "quota":
                        raise ResourceExhausted("q")
                    return SimpleNamespace(technical_score=float(int(symbol[1:]) - 50)), None
                finally:
                    with behaviour.lock:
                        behaviour.running -= 1
                        behaviour.finished.append(symbol)

        return Engine()

    def wait_idle(self, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self.lock:
                if self.running == 0:
                    return
            time.sleep(0.01)
        raise AssertionError("arka plan işleri bitmedi")


@pytest.fixture
def env():
    """(davranış üreticisi, havuz üreticisi); sonunda takılan işler serbest bırakılır ve havuzlar kapatılır."""
    behaviours, pools = [], []

    def make_behaviour(plan):
        b = Behaviour(plan)
        behaviours.append(b)
        return b

    def make_pool(workers=db.MAX_WORKERS):
        p = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="test-dashboard")
        pools.append(p)
        return p

    yield make_behaviour, make_pool
    for b in behaviours:
        b.release.set()
        b.wait_idle()
    for p in pools:
        p.shutdown(wait=True)


def run(behaviour, pool, budget=BUDGET, d=None, **kw):
    d = d or deps()
    d.technical_engine_factory = behaviour.factory
    started = time.monotonic()
    out = db.build_dashboard(SYMBOLS, "FIRESTORE", d, now=NOW, budget_seconds=budget, executor=pool, **kw)
    return out, time.monotonic() - started


def statuses(out):
    return {i["asset"]: (i["status"], i["reason"]) for i in out["items"]}


def assert_no_scores(item):
    assert all(item[k] is None for k in ("decision", "final_score", "confidence", "channel_completeness",
                                         "technical_score", "news_score", "macro_score"))


# --- A–E ---------------------------------------------------------------------------------------------------------

def test_A_all_fast_complete_ok(env):
    make, pool = env
    b = make(lambda s: "fast")
    out, elapsed = run(b, pool(), budget=10)
    assert len(out["items"]) == 100 and {i["status"] for i in out["items"]} == {"OK"}
    assert elapsed < 10 and b.peak <= db.MAX_WORKERS


def test_B_one_hung_symbol_does_not_block_others(env):
    make, pool = env
    b = make(lambda s: "hang" if s == "S042" else "fast")
    out, elapsed = run(b, pool())
    st = statuses(out)
    assert st["S042"] == ("ERROR", db.DEADLINE_EXCEEDED)
    assert sum(1 for v in st.values() if v[0] == "OK") == 99
    assert elapsed < BUDGET + 1.0
    assert out["items"][-1]["asset"] == "S042"  # hata satırı en altta, sıralama bozulmaz
    assert_no_scores(out["items"][-1])
    ok_scores = [i["final_score"] for i in out["items"] if i["status"] == "OK"]
    assert ok_scores == sorted(ok_scores, reverse=True)


def test_C_half_hung_classification(env):
    """Sınıflandırma mantığı: yeterli işçi varsa 50 OK + 50 deadline (test havuzu, yalnız mantık için)."""
    make, pool = env
    b = make(lambda s: "hang" if int(s[1:]) % 2 else "fast")
    out, elapsed = run(b, pool(workers=60))
    st = statuses(out)
    assert sum(1 for v in st.values() if v == ("ERROR", db.DEADLINE_EXCEEDED)) == 50
    assert sum(1 for v in st.values() if v[0] == "OK") == 50
    assert elapsed < BUDGET + 1.0


def test_C2_half_hung_under_real_cap_is_fail_visible(env):
    """Gerçek sınır (8): takılanlar işçileri doldurunca hızlılar da kuyrukta kalıp deadline olabilir — bu, sınırlı
    eşzamanlılığın bilinçli bedeli. Yanıt geçerli, her satır OK ya da skorsuz deadline, tepe 8'i aşmaz."""
    make, pool = env
    b = make(lambda s: "hang" if int(s[1:]) % 2 else "fast")
    out, elapsed = run(b, pool())
    st = statuses(out)
    assert set(st.values()) <= {("OK", None), ("ERROR", db.DEADLINE_EXCEEDED)}
    assert sum(1 for v in st.values() if v[0] == "OK") >= 4
    for item in out["items"]:
        if item["status"] != "OK":
            assert_no_scores(item)
    assert b.peak <= db.MAX_WORKERS and elapsed < BUDGET + 1.0


def test_D_all_hung_returns_contract_valid_response_and_cancels_unstarted(env):
    make, pool = env
    b = make(lambda s: "hang")
    out, elapsed = run(b, pool())
    assert elapsed < BUDGET + 1.0
    assert out["mode"] == "NORMAL" and len(out["items"]) == 100
    for item in out["items"]:
        assert (item["status"], item["reason"]) == ("ERROR", db.DEADLINE_EXCEEDED)
        assert_no_scores(item)
    assert len(b.started) == db.MAX_WORKERS  # yalnız havuz kadar başladı; 92'si iptal
    b.release.set()
    b.wait_idle()
    time.sleep(0.05)
    assert len(b.started) == db.MAX_WORKERS and len(b.finished) == db.MAX_WORKERS


def test_E_one_symbol_exception_only_that_row(env):
    make, pool = env
    b = make(lambda s: "boom" if s == "S007" else "fast")
    out, _ = run(b, pool(), budget=10)
    st = statuses(out)
    assert st["S007"][0] == "ERROR" and "teknik hesaplama hatası" in st["S007"][1]
    assert sum(1 for v in st.values() if v[0] == "OK") == 99


# --- F/G: bütçe isteğin başından sayılır -------------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SlowMacro(Macro):
    """Ön yükleme süresini sahte saatte ilerletir."""

    def __init__(self, clock, seconds):
        super().__init__()
        self.clock, self.seconds = clock, seconds

    def get_latest_with_id(self):
        self.clock.t += self.seconds
        return super().get_latest_with_id()


def test_F_preload_time_is_deducted_from_worker_wait(env, monkeypatch):
    make, pool = env
    b = make(lambda s: "hang")
    clock = FakeClock()
    seen = []
    real_wait = db._wait
    monkeypatch.setattr(db, "_wait", lambda fs, timeout, return_when: (seen.append(timeout), real_wait(
        fs, timeout=timeout, return_when=return_when))[1])
    out, elapsed = run(b, pool(), budget=0.1, d=deps(macro=SlowMacro(clock, 0.08)), clock=clock)
    assert seen == [pytest.approx(0.02)]  # 100 ms bütçe − 80 ms ön yükleme
    assert elapsed < 0.1 + 0.5  # gerçek bekleme ~20 ms; 180 ms (80 + 100) değil
    assert {i["reason"] for i in out["items"]} == {db.DEADLINE_EXCEEDED}


def test_G_budget_exhausted_before_pool_starts_no_provider_calls(env):
    make, pool = env
    b = make(lambda s: "fast")
    clock = FakeClock()
    p = pool()
    out, _ = run(b, p, budget=0.1, d=deps(macro=SlowMacro(clock, 0.1)), clock=clock)
    assert b.started == []  # hiçbir sağlayıcı/teknik çağrısı başlamadı
    assert len(out["items"]) == 100 and out["mode"] == "NORMAL"
    for item in out["items"]:
        assert (item["status"], item["reason"]) == ("ERROR", db.DEADLINE_EXCEEDED)
        assert_no_scores(item)


# --- H/I: üst üste istekler süreç sınırını aşamaz ---------------------------------------------------------------

def test_H_overlapping_request_cannot_exceed_process_cap(env):
    make, pool = env
    shared = pool()
    b = make(lambda s: "hang")
    run(b, shared)  # A: 8 işçi takılı kaldı, deadline
    assert b.running == db.MAX_WORKERS
    out_b, elapsed = run(b, shared)  # B: A'nın işleri hâlâ sürerken
    assert elapsed < BUDGET + 1.0
    assert b.peak <= db.MAX_WORKERS and len(b.started) == db.MAX_WORKERS  # B hiç yeni işçi açamadı
    assert {i["reason"] for i in out_b["items"]} == {db.DEADLINE_EXCEEDED}


def test_I_repeated_refresh_peak_bounded_and_pending_never_start(env):
    make, pool = env
    shared = pool()
    b = make(lambda s: "hang")
    for _ in range(3):
        run(b, shared, budget=0.15)
    assert b.peak <= db.MAX_WORKERS
    b.release.set()
    b.wait_idle()
    time.sleep(0.05)
    assert len(b.started) == db.MAX_WORKERS  # 3 isteğin iptal edilen işleri deadline sonrası başlamadı


def test_I2_requests_share_pool_but_not_results(env):
    """İki istek aynı havuzu kullanır; sonuçlar karışmaz (her istek yalnız kendi sembollerini görür)."""
    make, pool = env
    shared = pool()
    b = make(lambda s: "fast")
    d = deps()
    d.technical_engine_factory = b.factory
    out1 = db.build_dashboard(["S001", "S002"], "FIRESTORE", d, now=NOW, budget_seconds=5, executor=shared)
    out2 = db.build_dashboard(["S090"], "FIRESTORE", d, now=NOW, budget_seconds=5, executor=shared)
    assert [i["asset"] for i in out1["items"]] == ["S002", "S001"] and [i["asset"] for i in out2["items"]] == ["S090"]


def test_completed_after_wait_is_conservatively_deadline(env, monkeypatch):
    """Bekleme dönüşünde `done` dışında kalan iş sonradan bitmiş olsa da sonucu seçilmez (ihtiyatlı deadline)."""
    make, pool = env
    b = make(lambda s: "fast")
    real_wait = db._wait

    def wait_then_report_none(fs, timeout, return_when):
        real_wait(fs, timeout=5)
        return set(), set(fs)

    monkeypatch.setattr(db, "_wait", wait_then_report_none)
    out, _ = run(b, pool(), budget=5)
    assert {i["status"] for i in out["items"]} == {"ERROR"}
    assert {i["reason"] for i in out["items"]} == {db.DEADLINE_EXCEEDED}


# --- kota, API, yapılandırma ------------------------------------------------------------------------------------

def test_production_quota_fails_fast_even_with_hung_symbols(env):
    make, pool = env
    b = make(lambda s: "quota" if s == "S000" else "hang")
    started = time.monotonic()
    with pytest.raises(ResourceExhausted):
        run(b, pool(), budget=30)
    assert time.monotonic() - started < 5  # bütçenin tamamı beklenmez


def test_api_all_hung_is_200_not_500(monkeypatch, env):
    make, pool = env
    b = make(lambda s: "hang")
    p = pool()
    d = deps()
    d.technical_engine_factory = b.factory
    client, _ = dashboard_client(monkeypatch, dependencies=d)
    real = db.build_dashboard
    import app.api.decisions as decisions_api
    monkeypatch.setattr(decisions_api, "build_dashboard",
                        lambda symbols, source: real(symbols, source, d, now=NOW, budget_seconds=BUDGET, executor=p))
    r = client.get("/decisions/dashboard")
    assert r.status_code == 200
    assert {i["reason"] for i in r.json()["items"]} == {db.DEADLINE_EXCEEDED}


def test_process_executor_is_singleton_with_cap():
    a, b = db.dashboard_executor(), db.dashboard_executor()
    assert a is b and a._max_workers == db.MAX_WORKERS


@pytest.mark.parametrize("raw,expected", [(None, 45.0), ("30", 30.0), ("240", 240.0)])
def test_budget_config(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("DASHBOARD_TOTAL_BUDGET_SECONDS", raising=False)
    else:
        monkeypatch.setenv("DASHBOARD_TOTAL_BUDGET_SECONDS", raw)
    assert db.dashboard_budget_seconds() == expected


@pytest.mark.parametrize("raw", ["abc", "0", "-5", "241", "290"])
def test_budget_config_invalid_fails_loudly(monkeypatch, raw):
    monkeypatch.setenv("DASHBOARD_TOTAL_BUDGET_SECONDS", raw)
    with pytest.raises(ValueError):
        db.dashboard_budget_seconds()


def test_default_budget_is_bounded_well_below_cloud_run_timeout():
    # tek sembolün sağlayıcı zinciri (3 × 10 sn + 2 × 2 sn = 34 sn) sığar; üst sınır 300 sn'ye ön yükleme payı bırakır
    assert 34 < db.DEFAULT_DASHBOARD_TOTAL_BUDGET_SECONDS <= db.MAX_DASHBOARD_TOTAL_BUDGET_SECONDS < 300
