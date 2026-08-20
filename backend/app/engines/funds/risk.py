"""Fon risk sınıflandırması — AŞAMA 60.

Kullanıcı isteği: "risk oranı ne gibi oranları da detaylıca belirt." TEFAS'ın
kendi hesapladığı bir Sharpe/volatilite göstergesi yayınlanmıyor; bunun yerine
fonun GERÇEK portföy varlık dağılımından (bkz. tefas_provider.py
BREAKDOWN_COLUMNS) türetilen, şeffaf ve yorumlanabilir bir risk sınıfı
kullanılıyor — "bu fonun %X'i hisse senedi, %Y'si nakit/tahvil benzeri
güvenli varlık" gibi somut bir gerekçeyle.

Basit sezgisel eşikler: hisse/riskli varlık ağırlığı yüksekse YÜKSEK risk,
nakit/repo/mevduat/devlet tahvili ağırlığı yüksekse DÜŞÜK risk, aksi halde
ORTA. Bu bir portföy optimizasyon modeli DEĞİLDİR — kullanıcıya "bu fon ne
kadar dalgalı bir varlık sınıfında" sorusuna en basit, en şeffaf cevaptır.
"""

EQUITY_LIKE_COLUMNS = [
    "stock_pct",
    "foreign_stock_pct",
    "etf_pct",
    "foreign_etf_pct",
    "venture_capital_investment_pct",
    "real_estate_investment_pct",
    "derivative_pct",
]

SAFE_LIKE_COLUMNS = [
    "takasbank_money_market_pct",
    "bist_money_market_pct",
    "repo_pct",
    "reverse_repo_pct",
    "term_deposit_pct",
    "deposit_tl_pct",
    "deposit_fx_pct",
    "deposit_gold_pct",
    "government_bond_pct",
    "treasury_bill_pct",
    "participation_account_pct",
]

HIGH_RISK_EQUITY_THRESHOLD_PCT = 50.0
LOW_RISK_SAFE_THRESHOLD_PCT = 60.0

RISK_LABELS_TR = {"YUKSEK": "Yüksek", "ORTA": "Orta", "DUSUK": "Düşük"}


def classify_risk(breakdown_record: dict) -> dict:
    equity_pct = sum(float(breakdown_record.get(c) or 0.0) for c in EQUITY_LIKE_COLUMNS)
    safe_pct = sum(float(breakdown_record.get(c) or 0.0) for c in SAFE_LIKE_COLUMNS)

    if equity_pct >= HIGH_RISK_EQUITY_THRESHOLD_PCT:
        risk_level = "YUKSEK"
    elif safe_pct >= LOW_RISK_SAFE_THRESHOLD_PCT:
        risk_level = "DUSUK"
    else:
        risk_level = "ORTA"

    return {
        "risk_level": risk_level,
        "equity_exposure_pct": round(equity_pct, 1),
        "safe_exposure_pct": round(safe_pct, 1),
    }
