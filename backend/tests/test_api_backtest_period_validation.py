"""HATA 3C (26.08.2026) — API seviyesinde period validasyonu uçtan uca testi.

`prepare_backtest_history()`'nin defense-in-depth doğrulaması (bkz.
`test_completed_history.py`, `test_backtest_completed_session.py`) zaten
motor seviyesinde kanıtlandı. Bu dosya, mevcut proje-geneli
`except ValueError as exc: raise HTTPException(422, str(exc))` deseninin
(`api/backtest.py`, route DEĞİŞTİRİLMEDİ) desteklenmeyen bir `period` için
gerçekten HTTP 422 ürettiğini FastAPI `TestClient` ile doğrular — route
kodu hiç değiştirilmedi, yalnızca davranış gözlemlendi.

Ağır/ağa bağımlı motor çağrılarından (`BistProvider` → gerçek Yahoo isteği)
kaçınmak için: red edilen (`max`/`10y`/vb.) durumlarda zaten hiçbir provider
çağrısı YAPILMAZ (period validasyonu `prepare_backtest_history()`'nin en
başında, fetch'ten ÖNCE çalışır) — bu yüzden mock GEREKMEZ. Kabul edilen
tek bir örnek (`2y`) için ise motor metodları monkeypatch'lenir (gerçek ağ
isteği yapılmadan "kabul edildi" (200) doğrulanır — bu testin amacı motorun
DOĞRU SONUÇ ürettiğini değil, period'un REDDEDİLMEDİĞİNİ kanıtlamaktır).
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.engines.backtest.engine import BacktestEngine
from app.engines.backtest.walk_forward import WalkForwardOptimizer

app = FastAPI()
app.include_router(backtest_api.router)
client = TestClient(app)


def test_run_backtest_rejects_unsupported_period_with_422():
    response = client.get("/backtest/THYAO?period=max")
    assert response.status_code == 422


def test_compare_strategies_rejects_unsupported_period_with_422():
    response = client.get("/backtest/THYAO/compare-strategies?period=10y")
    assert response.status_code == 422


def test_walk_forward_rejects_unsupported_period_with_422():
    response = client.get("/backtest/THYAO/walk-forward?period=ytd")
    assert response.status_code == 422


def test_run_backtest_accepts_a_supported_period(monkeypatch):
    monkeypatch.setattr(BacktestEngine, "run", lambda self, symbol, period="2y", **kwargs: {"asset": symbol, "period": period})

    response = client.get("/backtest/THYAO?period=2y")

    assert response.status_code == 200
    assert response.json()["period"] == "2y"


def test_compare_strategies_accepts_a_supported_period(monkeypatch):
    monkeypatch.setattr(
        BacktestEngine,
        "compare_strategies",
        lambda self, symbol, presets, period="2y", **kwargs: {"asset": symbol, "period": period, "results": []},
    )

    response = client.get("/backtest/THYAO/compare-strategies?period=1y")

    assert response.status_code == 200
    assert response.json()["period"] == "1y"


def test_walk_forward_accepts_a_supported_period(monkeypatch):
    monkeypatch.setattr(
        WalkForwardOptimizer, "run", lambda self, symbol, period="3y", **kwargs: {"asset": symbol, "period": period}
    )

    response = client.get("/backtest/THYAO/walk-forward?period=3y")

    assert response.status_code == 200
    assert response.json()["period"] == "3y"
