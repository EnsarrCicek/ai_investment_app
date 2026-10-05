import csv
import hashlib
import math
from datetime import date

import pandas as pd

from app.research.official_bist import recompute_universe_technical as ru
from app.services.market_data.trading_calendar import expected_trading_sessions

SESSIONS = expected_trading_sessions(date(2024, 5, 7), date(2024, 12, 20))
INDEX = pd.Series([1000 + i for i in range(len(SESSIONS))], index=SESSIONS)
COLS = ["trade_date", "share_code", "status", "open", "high", "low", "close", "previous_last_price", "total_traded_quantity_raw",
        "total_traded_value_raw", "corporate_action_flag", "suspended_flag", "price_basis", "source_file", "source_sha256"]


def write_csv(path, change_after=None):
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        for i, d in enumerate(SESSIONS):
            c = 50 + 5 * math.sin(i / 9) + i * 0.05
            if change_after and d > change_after:
                c = 1.0
            w.writerow({k: "" for k in COLS} | {"trade_date": d.isoformat(), "share_code": "ABC.E", "status": "OK",
                                                "open": f"{c:.4f}", "high": f"{c * 1.01:.4f}", "low": f"{c * 0.99:.4f}",
                                                "close": f"{c:.4f}", "total_traded_quantity_raw": "1000"})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup(tmp_path, monkeypatch, change_after=None):
    monkeypatch.setattr(ru, "PKG", tmp_path)
    digest = write_csv(tmp_path / "ABC_official_raw.csv", change_after)
    return {"bound_to": {"raw_csv_sha256": digest}, "usable_sessions": ["2024-11-22", "2024-11-25", "2024-12-02"]}


def test_out_of_scope_sessions_rejected(tmp_path, monkeypatch):
    review = setup(tmp_path, monkeypatch)
    res = ru.run_symbol("ABC", review, INDEX, requested=["2024-11-22", "2024-11-26", "2024-12-02"])
    assert res["rejected"] == ["2024-11-26"] and [r["session"] for r in res["records"]] == ["2024-11-22", "2024-12-02"]


def test_hash_mismatch_not_run(tmp_path, monkeypatch):
    review = setup(tmp_path, monkeypatch)
    review["bound_to"]["raw_csv_sha256"] = "x"
    assert ru.run_symbol("ABC", review, INDEX)["status"] == "NOT_RUN"


def test_reproducible_and_future_independent(tmp_path, monkeypatch):
    review = setup(tmp_path, monkeypatch)
    a = ru.run_symbol("ABC", review, INDEX, requested=["2024-11-22"])
    b = ru.run_symbol("ABC", review, INDEX, requested=["2024-11-22"])
    assert a["records"] == b["records"] and a["records"][0]["status"] == "OK" and "components" in a["records"][0]
    review2 = setup(tmp_path, monkeypatch, change_after=date(2024, 11, 22))  # T sonrası fiyatlar bozuldu
    c = ru.run_symbol("ABC", review2, INDEX, requested=["2024-11-22"])
    assert c["records"][0]["technical_score"] == a["records"][0]["technical_score"]
