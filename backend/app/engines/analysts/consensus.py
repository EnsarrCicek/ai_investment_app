from datetime import datetime

from app.models.analyst_consensus import AnalystConsensus

# Deterministik, LLM'siz sınıflandırma (bkz. engines/funds/risk.py ile aynı
# felsefe): gerçek analist AL/SAT/TUT sayıları zaten net bir sinyal, bunu
# yorumlamak için bir dil modeline ihtiyaç yok — sadece ağırlıklı ortalama.
CONSENSUS_WEIGHTS = {
    "strong_buy": 2.0,
    "buy": 1.0,
    "hold": 0.0,
    "sell": -1.0,
    "strong_sell": -2.0,
}

CONSENSUS_LABELS_TR = {
    "GUCLU_AL": "Güçlü Al",
    "AL": "Al",
    "TUT": "Tut",
    "SAT": "Sat",
    "GUCLU_SAT": "Güçlü Sat",
    "VERI_YOK": "Veri Yok",
}


def classify_consensus(strong_buy: int, buy: int, hold: int, sell: int, strong_sell: int) -> tuple[float | None, str]:
    total = strong_buy + buy + hold + sell + strong_sell
    if total == 0:
        return None, "VERI_YOK"

    score = (
        strong_buy * CONSENSUS_WEIGHTS["strong_buy"]
        + buy * CONSENSUS_WEIGHTS["buy"]
        + hold * CONSENSUS_WEIGHTS["hold"]
        + sell * CONSENSUS_WEIGHTS["sell"]
        + strong_sell * CONSENSUS_WEIGHTS["strong_sell"]
    ) / total

    if score >= 1.2:
        label = "GUCLU_AL"
    elif score >= 0.4:
        label = "AL"
    elif score > -0.4:
        label = "TUT"
    elif score > -1.2:
        label = "SAT"
    else:
        label = "GUCLU_SAT"

    return round(score, 2), label


def build_consensus(symbol: str, raw: dict, now: datetime) -> AnalystConsensus:
    recommendations = raw.get("recommendations") or []
    current = recommendations[0] if recommendations else {}

    strong_buy = int(current.get("strong_buy", 0))
    buy = int(current.get("buy", 0))
    hold = int(current.get("hold", 0))
    sell = int(current.get("sell", 0))
    strong_sell = int(current.get("strong_sell", 0))

    score, label = classify_consensus(strong_buy, buy, hold, sell, strong_sell)

    price_targets = raw.get("price_targets") or {}
    current_price = price_targets.get("current")
    mean_target = price_targets.get("mean")
    upside_pct = None
    if current_price and mean_target and current_price > 0:
        upside_pct = round((mean_target - current_price) / current_price * 100, 1)

    return AnalystConsensus(
        symbol=symbol,
        as_of=now,
        strong_buy=strong_buy,
        buy=buy,
        hold=hold,
        sell=sell,
        strong_sell=strong_sell,
        total_analysts=strong_buy + buy + hold + sell + strong_sell,
        consensus_score=score,
        consensus_label=label,
        price_target_current=current_price,
        price_target_high=price_targets.get("high"),
        price_target_low=price_targets.get("low"),
        price_target_mean=mean_target,
        price_target_median=price_targets.get("median"),
        upside_pct=upside_pct,
        trend=recommendations,
    )
