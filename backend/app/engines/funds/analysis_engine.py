"""FundAnalysisEngine — AŞAMA 58.

Kullanıcı isteği: "fonlar için de analiz yaptır... hangisi alınabilir hangisi
en mantıklı gibisinden... aylık yıllık gibi analizleri oradan yapıp."

Yöntem: TEFAS'ın "tek istekte tüm fonlar" özelliğinden yararlanılır — fon
başına ayrı ayrı geçmiş çekmek yerine (2000 fon × N istek, dakikada 6 istek
limitiyle saatler sürerdi), yalnızca 5 REFERANS TARİHİ (son işlem günü, -1ay,
-3ay, -6ay, -1yıl) için birer "tüm fonlar" anlık görüntüsü çekilip fund_code'a
göre birleştirilir. Her tarih FundSnapshotRepository ile KALICI önbelleğe
alındığından bu 5 istek gerçekte TEFAS'a yalnızca ilk seferinde gider.

Missing Data Davranışı (ana doküman kural 6 ile aynı ilke — bkz.
DecisionEngine): bir fonun bir referans tarihte verisi yoksa (yeni kurulmuş
fon), o ufuk skora dahil edilmez; kalan ufukların ağırlığı otomatik normalize
edilir. Hiçbir ufukta veri yoksa fon sıralamaya hiç girmez.
"""

import math
from datetime import datetime, timedelta, timezone

from app.engines.funds.explanation import build_explanation
from app.engines.funds.risk import classify_risk
from app.models.fund_analysis import FundAnalysis
from app.repositories.fund_breakdown_repository import FundBreakdownRepository
from app.repositories.fund_snapshot_repository import FundSnapshotRepository
from app.services.funds.tefas_provider import TefasProvider

DEFAULT_KIND = "YAT"

RETURN_HORIZON_WEIGHTS = {
    "return_1m_pct": 0.15,
    "return_3m_pct": 0.25,
    "return_6m_pct": 0.30,
    "return_1y_pct": 0.30,
}

# Küçük/az yatırımcılı fonlar veri gürültüsü ve düşük likidite riski taşır —
# öneri listesine hiç girmezler (ana doküman kural: veri kalitesi hard-veto,
# bkz. AŞAMA 48/1 data_quality.py ile aynı ilke).
MIN_PORTFOLIO_SIZE_TL = 5_000_000.0
MIN_INVESTOR_COUNT = 20

MAX_LOOKBACK_DAYS = 10  # hafta sonu/tatil telafisi için bir referans tarihten geriye en fazla kaç gün denenir


def _valid_number(value) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True


def _composite_score(returns: dict[str, float | None]) -> float | None:
    available = {k: v for k, v in returns.items() if v is not None}
    if not available:
        return None
    weight_sum = sum(RETURN_HORIZON_WEIGHTS[k] for k in available)
    weighted = sum(available[k] * RETURN_HORIZON_WEIGHTS[k] for k in available)
    return round(weighted / weight_sum, 2)


class FundAnalysisEngine:
    def __init__(
        self,
        provider: TefasProvider | None = None,
        snapshot_repo: FundSnapshotRepository | None = None,
        breakdown_repo: FundBreakdownRepository | None = None,
    ):
        self._provider = provider or TefasProvider()
        self._snapshot_repo = snapshot_repo or FundSnapshotRepository()
        self._breakdown_repo = breakdown_repo or FundBreakdownRepository()

    def _snapshot_near(self, target_date: datetime, kind: str) -> tuple[str, dict[str, dict]]:
        """target_date'ten geriye doğru en fazla MAX_LOOKBACK_DAYS gün denenip
        veri bulunan ilk tarihin {fund_code: kayıt} sözlüğünü döner. Yalnızca
        gerekli 3 alanı (price/portfolio_size/investor_count) geçerli sayısal
        değere sahip kayıtlar dahil edilir.
        """
        for offset in range(MAX_LOOKBACK_DAYS):
            date_str = (target_date - timedelta(days=offset)).strftime("%Y-%m-%d")
            funds = self._snapshot_repo.get_or_fetch(date_str, self._provider, kind=kind)
            if funds:
                by_code = {
                    f["fund_code"]: f
                    for f in funds
                    if _valid_number(f.get("price")) and _valid_number(f.get("portfolio_size")) and _valid_number(f.get("investor_count"))
                }
                if by_code:
                    return date_str, by_code
        return "", {}

    def _breakdown_near(self, target_date: datetime, kind: str) -> dict[str, dict]:
        """Risk sınıflandırması için — yalnızca EN GÜNCEL portföy dağılımı
        gerekir (geçmiş dağılım değil), bu yüzden _snapshot_near ile aynı
        geriye-bakma mantığı ama tek bir tarih için.
        """
        for offset in range(MAX_LOOKBACK_DAYS):
            date_str = (target_date - timedelta(days=offset)).strftime("%Y-%m-%d")
            funds = self._breakdown_repo.get_or_fetch(date_str, self._provider, kind=kind)
            if funds:
                return {f["fund_code"]: f for f in funds}
        return {}

    def analyze_all(self, kind: str = DEFAULT_KIND) -> list[FundAnalysis]:
        now = datetime.now(timezone.utc)
        latest_date, latest_by_code = self._snapshot_near(now, kind)
        if not latest_by_code:
            raise ValueError("TEFAS'tan güncel fon verisi alınamadı")

        horizon_snapshots = {
            "return_1m_pct": self._snapshot_near(now - timedelta(days=30), kind)[1],
            "return_3m_pct": self._snapshot_near(now - timedelta(days=91), kind)[1],
            "return_6m_pct": self._snapshot_near(now - timedelta(days=182), kind)[1],
            "return_1y_pct": self._snapshot_near(now - timedelta(days=365), kind)[1],
        }
        breakdown_by_code = self._breakdown_near(now, kind)

        generated_at = datetime.now(timezone.utc)
        results: list[FundAnalysis] = []
        for code, record in latest_by_code.items():
            portfolio_size = float(record["portfolio_size"])
            investor_count = int(record["investor_count"])
            if portfolio_size < MIN_PORTFOLIO_SIZE_TL or investor_count < MIN_INVESTOR_COUNT:
                continue

            price_now = float(record["price"])
            returns: dict[str, float | None] = {}
            for key, snapshot in horizon_snapshots.items():
                past = snapshot.get(code)
                returns[key] = None if past is None or not past["price"] else round((price_now - past["price"]) / past["price"] * 100, 2)

            score = _composite_score(returns)
            if score is None:
                continue

            breakdown = breakdown_by_code.get(code)
            risk = classify_risk(breakdown) if breakdown is not None else None

            results.append(
                FundAnalysis(
                    fund_code=code,
                    fund_name=record["fund_name"],
                    price=price_now,
                    portfolio_size=portfolio_size,
                    investor_count=investor_count,
                    composite_score=score,
                    risk_level=risk["risk_level"] if risk else None,
                    equity_exposure_pct=risk["equity_exposure_pct"] if risk else None,
                    safe_exposure_pct=risk["safe_exposure_pct"] if risk else None,
                    as_of_date=latest_date,
                    generated_at=generated_at,
                    **returns,
                )
            )

        results.sort(key=lambda f: f.composite_score, reverse=True)

        total_count = len(results)
        for rank, fund in enumerate(results, start=1):
            fund.explanation = build_explanation(
                fund.return_1m_pct,
                fund.return_3m_pct,
                fund.return_6m_pct,
                fund.return_1y_pct,
                fund.risk_level,
                rank,
                total_count,
            )

        return results
