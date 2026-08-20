"""Bütçeyi en iyi sıralanan fonlara dağıtma — AŞAMA 58.

Basit, şeffaf, config'e bağlı bir sezgisel yöntem (AŞAMA 48/19'daki sabit TL
bütçesi / fiyat mantığıyla aynı ruh): en iyi N fon arasında, skora orantılı
ağırlıklandırma. Gerçek bir portföy optimizasyonu (Markowitz vb.) DEĞİLDİR —
kullanıcının risk toleransını bilmeden yapılabilecek en basit, en yorumlanabilir
tahmin.
"""

from app.models.fund_analysis import FundAnalysis

DEFAULT_TOP_N = 3


def recommend_allocation(ranked_funds: list[FundAnalysis], budget_tl: float, top_n: int = DEFAULT_TOP_N) -> list[dict]:
    if budget_tl <= 0 or not ranked_funds:
        return []

    top = ranked_funds[:top_n]

    # Skorlar negatif olabilir (ör. tüm piyasa düşüş döneminde) — ağırlıklandırma
    # için pozitif bir ölçeğe kaydırılır, aksi halde negatif skor negatif TL
    # tutarına yol açardı. En düşük skorlu fon bile küçük ama sıfır olmayan pay alır.
    min_score = min(f.composite_score for f in top)
    shift = abs(min_score) + 1.0 if min_score <= 0 else 0.0

    weighted = [(fund, fund.composite_score + shift) for fund in top]
    weight_sum = sum(weight for _, weight in weighted)

    return [
        {
            "fund_code": fund.fund_code,
            "fund_name": fund.fund_name,
            "amount_tl": round(budget_tl * weight / weight_sum, 2),
            "composite_score": fund.composite_score,
        }
        for fund, weight in weighted
    ]
