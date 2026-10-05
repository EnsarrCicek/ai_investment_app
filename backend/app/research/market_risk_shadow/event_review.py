"""MARKET-RISK-1 — yerel olay incelemesi çalıştırıcısı (gölge mod, üretime bağlı değil).

Bu bir OLAY İNCELEMESİDİR: parametre geliştirme/doğrulama başarısı veya Technical
V2 holdout kanıtı değildir. "Bugünkü motorun, bugün indirilen geçmiş verilerle
yeniden canlandırılması"dır; o günlerde alınmış veri arşivi veya o günkü
sistem çıktısı DEĞİLDİR.

Zaman disiplini:
  * Çalıştırma girişinde `filter_completed_daily_bars(now=çalıştırma anı)` ile
    tamamlanmamış gün çıkarılır (tamamlanmış bar garantisi burada uygulanır).
  * Her T için "şimdi" = T kapanışı + kesinleşme payı + 1 dk kabul edilir ve
    teknik hat ile risk değerlendiricilerine YALNIZCA T'ye kadar olan satırlar
    verilir (ileri getiriler ayrıca, yalnızca raporlama için hesaplanır).

Teknik kanal: üretim teknik hattının aynısı (seans normalizasyonu, süreklilik,
bütünlük ve kalite kontrolleri, `compute_technical_analysis`), ağırlıklar
Technical V2 dondurulmuş manifestinden. Ham sınıf `_classify(teknik_skor,
DEFAULT_THRESHOLDS)` — yalnızca teknik kanal, kod içi varsayılan karar eşikleri;
tarihsel haber/makro/config yoktur ve tam DecisionEngine kararı DEĞİLDİR.

Çalıştırma (backend klasöründen):
    .venv\\Scripts\\python.exe -m app.research.market_risk_shadow.event_review
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.engines.decision.engine import DEFAULT_THRESHOLDS, _classify
from app.engines.decision.risk_gate import evaluate_shadow_risk_gate
from app.engines.risk.asset_risk import assess_asset_risk
from app.engines.risk.market_risk import assess_market_risk
from app.engines.risk.shadow_inputs import EXPERIMENTAL_PARAMS_V0, RULE_LOGIC_VERSION, ShadowRiskParams
from app.engines.technical.session_timing import ISTANBUL_TZ, SESSION_CLOSE
from app.services.market_data.completed_bars import (
    DAILY_BAR_FINALIZATION_DELAY_MINUTES,
    filter_completed_daily_bars,
    latest_expected_completed_date,
)
from app.services.market_data.trading_calendar import expected_trading_sessions

BACKEND_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = Path(__file__).resolve().parent / "runs"
REVIEW_START = date(2026, 8, 1)
FETCH_START = date(2024, 6, 1)  # ısınma: piyasa riski ~270 seans, teknik hat 6 ay + pre-roll
HORIZONS = (5, 10, 20)
CODE_FILES = (
    "app/engines/risk/shadow_inputs.py",
    "app/engines/risk/market_risk.py",
    "app/engines/risk/asset_risk.py",
    "app/engines/decision/risk_gate.py",
    "app/engines/decision/engine.py",
    "app/engines/technical/engine.py",
    "app/research/market_risk_shadow/event_review.py",
)


def prepare_run_input(provider_df: pd.DataFrame, run_now: datetime) -> pd.DataFrame:
    """Tamamlanmış bar garantisi: çalıştırma anında henüz kesinleşmemiş günlük
    bar (kapanış + kesinleşme payı dolmamış bugün) girişte çıkarılır."""
    return filter_completed_daily_bars(provider_df, now=run_now)


def completion_moment(session: date) -> datetime:
    close = datetime.combine(session, SESSION_CLOSE, tzinfo=ISTANBUL_TZ)
    return close + timedelta(minutes=DAILY_BAR_FINALIZATION_DELAY_MINUTES + 1)


def _upto(df, session: date):
    return df[[ts.date() <= session for ts in df.index]]


def default_technical(asset_df: pd.DataFrame, index_close_by_date: pd.Series, session: date, symbol: str,
                      include_components: bool = False) -> dict:
    """Üretim teknik hattı, T anına göre. Girdi zaten T'ye kadar kesilmiştir."""
    from app.engines.technical.data_quality import check_data_quality, check_raw_ohlcv_integrity, check_trading_day_continuity
    from app.engines.technical.engine import MIN_HISTORY_DAYS, compute_technical_analysis
    from app.engines.technical.history_window import compute_history_window, resolve_expected_start
    from app.services.market_data.trading_calendar import normalize_bist_daily_sessions, session_normalization_to_dict

    weights, family_weights, scoring_hash = frozen_v2_scoring()
    now_t = completion_moment(session)
    try:
        window = compute_history_window(now_t)
        normalized, normalization = normalize_bist_daily_sessions(asset_df, symbol=symbol, provider="yahoo_finance")
        expected_start, status = resolve_expected_start(normalized, window.analysis_start)
        check_trading_day_continuity(normalized, symbol, now=now_t, expected_start=expected_start)
        df = normalized[normalized.index.date >= expected_start]
        check_raw_ohlcv_integrity(df, symbol)
        check_data_quality(df, symbol, min_history_days=MIN_HISTORY_DAYS, now=now_t)
        analysis = compute_technical_analysis(
            df, symbol, weights, family_weights, scoring_hash, status.value,
            session_normalization_to_dict(normalization), benchmark_close_series=index_close_by_date, now=now_t,
        )
    except Exception as exc:  # noqa: BLE001 — teknik kanal bu T için yok; uydurulmaz
        return {"status": "TECHNICAL_UNAVAILABLE", "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    out = {"status": "OK", "technical_score": analysis.technical_score}
    if include_components:  # yalnızca ek alan; skor hesabı aynı
        out |= {"components": analysis.components, "family_scores": analysis.family_scores,
                "evidence_coverage": analysis.evidence_coverage, "confidence": analysis.confidence}
    return out


def frozen_v2_scoring():
    from app.engines.technical.scoring import compute_scoring_config_hash
    from app.research.technical_versions import TECHNICAL_V2_SPEC, load_evaluation_identity

    identity = load_evaluation_identity(TECHNICAL_V2_SPEC)
    manifest = json.loads(TECHNICAL_V2_SPEC.freeze_manifest_path.read_text(encoding="utf-8"))
    weights, family = manifest["technical_indicator_weights"], manifest["technical_family_weights"]
    scoring_hash = compute_scoring_config_hash(weights, family)
    if scoring_hash != identity.scoring_config_hash:
        raise RuntimeError("V2 manifest ağırlıkları dondurulmuş scoring hash ile eşleşmiyor")
    return weights, family, scoring_hash


def forward_returns(closes_by_date: pd.Series, session: date, calendar_sessions: list[date], horizons=HORIZONS) -> dict:
    """Sinyal sonrası kapanıştan kapanışa fiyat hareketi — uygulanmış strateji getirisi DEĞİL.
    Ufuk, BEKLENEN BIST seanslarıyla sayılır; ufuk seansı henüz tamamlanmadıysa
    PENDING, tamamlandı ama bar yoksa MISSING (eksik bar ileri doldurulmaz)."""
    if session not in closes_by_date.index:
        return {f"T+{h}": "MISSING_T" for h in horizons}
    position = calendar_sessions.index(session)
    out = {}
    for h in horizons:
        if position + h >= len(calendar_sessions):
            out[f"T+{h}"] = "PENDING"
        elif calendar_sessions[position + h] not in closes_by_date.index:
            out[f"T+{h}"] = "MISSING"
        else:
            target = calendar_sessions[position + h]
            out[f"T+{h}"] = round((closes_by_date[target] / closes_by_date[session] - 1) * 100, 4)
    return out


def _rules_out(assessment) -> dict:
    return {r.rule: {"status": r.status, "triggered": r.triggered, "measure": r.measure,
                     "required_sessions": r.required_sessions, "missing": list(r.missing_reasons)}
            for r in assessment.rules}


def review(
    asset_df: pd.DataFrame,
    index_df: pd.DataFrame,
    symbol: str,
    review_sessions: list[date],
    params: ShadowRiskParams,
    technical_fn=default_technical,
    calendar_sessions: list[date] | None = None,
) -> list[dict]:
    """Girdiler çalıştırma girişinde tamamlanmış-bar filtresinden geçmiş olmalıdır."""
    asset_close = pd.Series(asset_df["Close"].to_numpy(), index=[ts.date() for ts in asset_df.index])
    index_close = pd.Series(index_df["Close"].to_numpy(), index=[ts.date() for ts in index_df.index])
    calendar_sessions = calendar_sessions or review_sessions  # tamamlanmış son seansa kadar
    rows = []
    for t in review_sessions:
        asset_t, index_t = _upto(asset_df, t), _upto(index_df, t)
        index_close_t = index_close[index_close.index <= t]
        asset_close_t = asset_close[asset_close.index <= t]
        technical = technical_fn(asset_t, index_close_t, t, symbol)
        raw = _classify(technical["technical_score"], DEFAULT_THRESHOLDS) if technical["status"] == "OK" else None
        market = assess_market_risk(index_close_t, t, params)
        asset = assess_asset_risk(asset_close_t, index_close_t, t, params)
        gate = evaluate_shadow_risk_gate(raw, market, asset) if raw is not None else None
        rows.append({
            "session": t.isoformat(),
            "technical_status": technical["status"],
            "technical_reason": technical.get("reason", ""),
            "technical_score": technical.get("technical_score"),
            "raw_class_technical_only": raw,
            "market_data": market.data_status,
            "market_risk": market.risk_status,
            "market_reasons": list(market.reason_codes) + list(market.data_reason_codes),
            "market_measures": market.measures,
            "market_rules": _rules_out(market),
            "asset_data": asset.data_status,
            "asset_risk": asset.risk_status,
            "asset_reasons": list(asset.reason_codes) + list(asset.data_reason_codes),
            "asset_measures": asset.measures,
            "asset_rules": _rules_out(asset),
            "shadow_gate": gate.gate_outcome if gate else "NO_RAW_CLASS",
            "gate_reasons": list(gate.reason_codes) if gate else [],
            "asset_bar_present": t in asset_close.index,
            "price_move_after_close": forward_returns(asset_close, t, calendar_sessions),
        })
    return rows


# ------------------------------------------------------------------ I/O (yalnızca main)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _data_checks(symbol_df: pd.DataFrame, raw_close: pd.Series, actions: pd.DataFrame, review_from: date) -> dict:
    adj = pd.Series(symbol_df["Close"].to_numpy(), index=[ts.date() for ts in symbol_df.index])
    raw = pd.Series(raw_close.to_numpy(), index=[ts.date() for ts in raw_close.index]).reindex(adj.index)
    ratio = (adj / raw).round(8)
    ratio_changes = [d.isoformat() for d, changed in (ratio != ratio.shift()).items() if changed][1:]
    daily = adj.pct_change() * 100
    action_dates = {ts.date() for ts in actions.index} if actions is not None and len(actions) else set()
    large = [
        {"session": d.isoformat(), "daily_pct": round(v, 4), "has_corporate_action": d in action_dates}
        for d, v in daily.items() if abs(v) > 20 and d >= review_from - timedelta(days=400)
    ]
    return {
        "adjusted_vs_raw_ratio_change_sessions": ratio_changes,
        "corporate_actions": [
            {"date": ts.date().isoformat(), **{k: float(v) for k, v in row.items()}} for ts, row in actions.iterrows()
        ] if actions is not None else [],
        "abs_daily_move_over_20pct": large,
        "single_price_bars_in_review": [
            {"session": ts.date().isoformat(), "close": float(r["Close"]), "volume": float(r["Volume"])}
            for ts, r in symbol_df.iterrows()
            if ts.date() >= review_from and r["Open"] == r["High"] == r["Low"] == r["Close"]
        ],
    }


# Kayıtlı sağlayıcı CSV'leri bit düzeyinde sadık okunur: pandas'ın varsayılan/"high"
# dönüştürücüsü bazı değerlerin son bitini değiştirir (ör. 0.30000000000000004);
# "round_trip" dönüştürücüsü (yalnızca C motoru) dosya metnini aynen geri verir.
CSV_READER = {"engine": "c", "float_precision": "round_trip"}


def load_saved_provider_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0, **CSV_READER)
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(ISTANBUL_TZ)
    return df


def replay_saved(run_dir: Path, out_dir: Path) -> Path:
    """Kayıtlı girdiyle, kayıttaki çalıştırma anına göre (tamamlanmış bar sınırı
    aynı kalır) MEVCUT kodla yeniden değerlendirir. Ağ çağrısı yapmaz."""
    source = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    run_now = datetime.fromisoformat(source["run_at"])
    inputs = {s: prepare_run_input(load_saved_provider_csv(run_dir / f"{s}_provider_ohlcv.csv"), run_now)
              for s in ("IEYHO", "XU100")}
    last_completed = expected_trading_sessions(REVIEW_START, latest_expected_completed_date(run_now))[-1]
    sessions = expected_trading_sessions(REVIEW_START, last_completed)
    rows = review(inputs["IEYHO"], inputs["XU100"], "IEYHO", sessions, EXPERIMENTAL_PARAMS_V0, calendar_sessions=sessions)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "IEYHO_daily_review.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    manifest = {
        "study": "MARKET-RISK-1 replay of saved inputs with current code (no network)",
        "source_run": run_dir.name,
        "source_run_at": source["run_at"],
        "source_input_sha256": {s: _sha256_file(run_dir / f"{s}_provider_ohlcv.csv") for s in ("IEYHO", "XU100")},
        "last_completed_session_used": last_completed.isoformat(),
        "rule_logic_version": RULE_LOGIC_VERSION,
        "params": dataclasses.asdict(EXPERIMENTAL_PARAMS_V0),
        "code_file_sha256": {f: _sha256_file(BACKEND_ROOT / f) for f in CODE_FILES},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir


def main() -> int:
    # Kayıtlı girdiyle ağsız yeniden oynatma: --from-saved <run_dir> --out <out_dir>
    args = sys.argv[1:]
    if args:
        if len(args) != 4 or args[0] != "--from-saved" or args[2] != "--out":
            raise SystemExit("kullanım: --from-saved <run_dir> --out <out_dir> (argümansız: yeni indirme)")
        print(replay_saved(Path(args[1]), Path(args[3])))
        return 0
    import yfinance as yf

    from app.services.market_data.bist_provider import BistProvider

    run_now = datetime.now(ISTANBUL_TZ)
    run_id = run_now.strftime("%Y%m%dT%H%M%S")
    out = OUTPUT_ROOT / run_id
    out.mkdir(parents=True, exist_ok=True)
    provider = BistProvider()
    end_exclusive = (run_now.date() + timedelta(days=1)).isoformat()

    fetched = {}
    for symbol in ("IEYHO", "XU100"):
        raw_df = provider.get_history(symbol, start=FETCH_START.isoformat(), end=end_exclusive)
        raw_df.to_csv(out / f"{symbol}_provider_ohlcv.csv")
        completed = prepare_run_input(raw_df, run_now)
        fetched[symbol] = completed
    ticker = yf.Ticker("IEYHO.IS")
    ieyho_raw_close = ticker.history(start=FETCH_START.isoformat(), end=end_exclusive, auto_adjust=False)["Close"]
    ieyho_raw_close.to_csv(out / "IEYHO_unadjusted_close.csv")
    actions = ticker.actions
    actions.to_csv(out / "IEYHO_corporate_actions.csv")
    identity = {}
    for symbol in ("IEYHO", "XU100"):
        try:
            info = yf.Ticker(f"{symbol}.IS").info
            identity[symbol] = {k: info.get(k) for k in ("symbol", "shortName", "longName", "exchange", "currency", "quoteType")}
        except Exception as exc:  # noqa: BLE001
            identity[symbol] = {"error": type(exc).__name__}

    # Son tamamlanmış seans veri sağlayıcıdan değil, takvim + çalıştırma anından türetilir;
    # bir serinin o seansta barı yoksa bu "eksik veri" olarak görünür.
    last_completed = expected_trading_sessions(REVIEW_START, latest_expected_completed_date(run_now))[-1]
    sessions = expected_trading_sessions(REVIEW_START, last_completed)
    rows = review(fetched["IEYHO"], fetched["XU100"], "IEYHO", sessions, EXPERIMENTAL_PARAMS_V0,
                  calendar_sessions=sessions)

    with open(out / "IEYHO_daily_review.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1, default=str)
    with open(out / "IEYHO_daily_review.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["session", "technical_score", "raw_class_technical_only", "market_risk", "asset_risk",
                         "shadow_gate", "reasons", "market_data", "asset_data", "T+5", "T+10", "T+20"])
        for r in rows:
            f = r["price_move_after_close"]
            writer.writerow([r["session"], r["technical_score"], r["raw_class_technical_only"], r["market_risk"],
                             r["asset_risk"], r["shadow_gate"], ";".join(r["market_reasons"] + r["asset_reasons"]),
                             r["market_data"], r["asset_data"], f.get("T+5"), f.get("T+10"), f.get("T+20")])

    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *CODE_FILES], cwd=BACKEND_ROOT,
                               capture_output=True, text=True).stdout.splitlines()
    except OSError:
        head, dirty = "UNKNOWN", []
    manifest = {
        "study": "MARKET-RISK-1 event review (shadow; not parameter validation; not Technical V2 holdout evidence)",
        "nature": "today's engine re-run on historical data downloaded today; NOT a point-in-time archive",
        "run_at": run_now.isoformat(),
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_completed_session_used": last_completed.isoformat(),
        "review_range": [REVIEW_START.isoformat(), last_completed.isoformat()],
        "fetch_start": FETCH_START.isoformat(),
        "data_source": "Yahoo Finance via yfinance (BistProvider.get_history; yfinance default auto_adjust prices); "
                       "unofficial source, ~20 min delayed; symbols IEYHO.IS and XU100.IS",
        "yfinance_version": yf.__version__,
        "symbol_identity": identity,
        "params": dataclasses.asdict(EXPERIMENTAL_PARAMS_V0),
        "rule_logic_version": RULE_LOGIC_VERSION,
        "rule_combinations": {"market": "DRAWDOWN AND (VOLATILITY OR BELOW_TREND)",
                              "asset": "(PERIOD_DECLINE AND UNDERPERFORMS_INDEX) OR SHARP_DAILY_DECLINE"},
        "technical_channel": "production technical pipeline; weights from Technical V2 frozen manifest; "
                             "raw class = _classify(score, DEFAULT_THRESHOLDS) — technical channel only",
        "decision_thresholds": DEFAULT_THRESHOLDS,
        "git_head": head,
        "code_files_with_uncommitted_changes": dirty,
        "code_file_sha256": {f: _sha256_file(BACKEND_ROOT / f) for f in CODE_FILES},
        "data_checks_IEYHO": _data_checks(fetched["IEYHO"], ieyho_raw_close, actions, REVIEW_START),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
