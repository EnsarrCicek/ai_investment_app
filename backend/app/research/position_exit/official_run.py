"""EXIT-EXP-1 — resmî bülten fiyatları + resmî veriden yeniden hesaplanan teknik sınıflarla normalize çalıştırma (ağsız).

Kullanım (backend dizininden): python -X utf8 -m app.research.position_exit.official_run <çıktı_klasörü>

* Sözleşme K ve `normalized.py` hesaplayıcısı (`reference_episodes`, `run_policy`) AYNEN kullanılır; parametreler
  değişmez (%10 hedef, %8 zarar sınırı, C için %5 iz süren, 20 seans, %0,1 komisyon, asgari/ek kayma yok).
* Semboller: KAP inceleme sürüm 3'te READY_FOR_RESEARCH_WITH_LIMITS olanlar. Her sembolün takvimi, izinli ilk ve son
  seans arasındaki BEKLENEN seanslardır; izinli olmayan, bayraklı veya OK olmayan seansta bar/sınıf verilmez
  (dolum belirsiz / durum BİLİNMİYOR olur; sonraki bara atlanmaz). Referans izinli ilk seansta DÜZ başlar.
* Fiyat: resmî bülten ham seans fiyatı (açılış, yüksek, düşük, kapanış; hacim = toplam işlem adedi). İzinli kapsamda
  tarihli kurumsal işlem olmadığı (sürüm 3) için düzeltme uygulanmaz; bu, olay yokluğunun kanıtı değildir.
* Kapılar: ham CSV hash'i = inceleme bağlı hash'i; teknik sonuç seansları = izinli seanslar; bilinen sorun kaydı
  kontrolü atlanmaz. Resmî dosyalar için yalnız bu dosya kimliğine ve seans kapsamına bağlı sınırlı inceleme kaydı
  çıktı klasörüne yazılır ve kayıt kopyasına eklenir; known_issues.json değişmez, Yahoo blokları kalkmaz.
* Sınıflama: referans çıkışı veri içinde gerçekleşen epizot TAMAMLANDI; veri sonunda referans hâlâ açıksa AÇIK
  (zorunlu satış yok; kapanış değerlemesi satış değildir); referans/politika dolumu belirsiz olanlar DEĞERLENDİRİLEMEDİ.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from app.research.data_issues.registry import check_input_files, load_registry
from app.research.position_exit.normalized import C, MAX_HOLD, POLICIES, STOP, TARGET, TRAIL, Bar, reference_episodes, run_policy
from app.services.market_data.trading_calendar import expected_trading_sessions

BACKEND = Path(__file__).resolve().parents[3]
RUNS = BACKEND / "app/research/official_bist/runs"
REVIEW = RUNS / "kap_scan_27_20261001" / "review_v3.json"
TECH = RUNS / "technical_recompute_10_20261001" / "technical_results.json"
PKG = RUNS / "raw_package_20260930" / "symbols"
YAHOO = BACKEND / "app/research/market_risk_shadow/runs/universe_20260925/inputs"
CODE = ["app/research/position_exit/official_run.py", "app/research/position_exit/normalized.py",
        "app/research/position_exit/EVALUATION_CONTRACT.md", "app/research/official_bist/kap_scan_review_v3.py",
        "app/research/data_issues/registry.py", "app/research/data_issues/known_issues.json"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def clean_row(r: dict) -> bool:
    return r["status"] == "OK" and not r["corporate_action_flag"] and r["suspended_flag"] in ("", "0")


def symbol_inputs(sym: str, review: dict, tech: dict, raw_path: Path) -> dict:
    """Hash ve kapsam kontrolü; uymazsa NOT_RUN. Bar/sınıf yalnız izinli seanslarda."""
    allowed = review["usable_sessions"]
    if not allowed:
        return {"status": "NOT_RUN", "reason": "NO_ALLOWED_SESSION"}
    digest = sha(raw_path)
    if digest != review["bound_to"]["raw_csv_sha256"] or tech.get("raw_csv_sha256") != digest:
        return {"status": "NOT_RUN", "reason": "RAW_CSV_HASH_MISMATCH"}
    ok_tech = [r for r in tech["records"] if r["status"] == "OK"]
    if tech.get("accepted") != allowed or any(r["session"] not in set(allowed) for r in tech["records"]):
        return {"status": "NOT_RUN", "reason": "TECHNICAL_SESSIONS_NOT_EQUAL_TO_REVIEW_SCOPE"}
    allow = set(allowed)
    sessions = expected_trading_sessions(date.fromisoformat(allowed[0]), date.fromisoformat(allowed[-1]))
    bars, dropped = {}, []
    for r in csv.DictReader(raw_path.open(encoding="utf-8")):
        if r["trade_date"] not in allow:
            continue
        if not clean_row(r):
            dropped.append(r["trade_date"])
            continue
        bars[date.fromisoformat(r["trade_date"])] = Bar(float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
                                                        float(r["total_traded_quantity_raw"] or 0))
    classes = {date.fromisoformat(r["session"]): r["raw_class"] for r in ok_tech}
    return {"status": "RUN", "sessions": sessions, "bars": bars, "classes": classes, "raw_sha256": digest,
            "dropped_bars": dropped, "allowed": [allowed[0], allowed[-1], len(allowed)],
            "calendar_sessions_not_allowed": [d.isoformat() for d in sessions if d.isoformat() not in allow]}


def b_principal(run: dict, sessions: list[date], bars: dict, q0: float) -> list[dict]:
    """B hedef kısmi satışları: T kapanışında planlanan net anapara ile T+1 açılış varsayımıyla gerçekleşen net."""
    out = []
    idx = {d.isoformat(): i for i, d in enumerate(sessions)}
    for s in run["sales"]:
        if s["reasons"] != ["TARGET"]:
            continue
        t = sessions[idx[s["session"]] - 1]
        qty = s["qty_fraction"] * q0
        out.append({"request_session": t.isoformat(), "fill_session": s["session"],
                    "planned_net": qty * bars[t].close * (1 - C), "actual_net": s["net"]})
    return out


def evaluate_symbols(inputs: dict[str, dict]) -> dict:
    completed, open_eps, unevaluable, unknown_buys, final_buys = [], [], [], [], []
    for sym in sorted(inputs):
        x = inputs[sym]
        ref = reference_episodes(sym, x["sessions"], x["bars"], x["classes"])
        unknown_buys += ref["unknown_state_buy_days"]
        final_buys += ref["buy_signal_on_final_session"]
        for ep in ref["episodes"]:
            if ep["status"] != "OK":
                unevaluable.append({"id": ep["id"], "reason": ep["reason"], "policy": "REFERENCE"})
                continue
            ep["runs"] = {p: run_policy(p, ep, x["sessions"], x["bars"]) for p in POLICIES}
            bad = {p: r for p, r in ep["runs"].items() if r["status"] != "OK"}
            if bad:
                unevaluable.append({"id": ep["id"], "reason": "POLICY_EXECUTION_UNDETERMINED",
                                    "policy": sorted(bad), "sessions": {p: r["session"] for p, r in bad.items()}})
                continue
            q0 = 1.0 / (ep["entry_price"] * (1 + C))
            ep["b_principal"] = b_principal(ep["runs"]["B"], x["sessions"], x["bars"], q0)
            (completed if ep["end_kind"] == "REFERENCE_EXIT" else open_eps).append(ep)
    return {"completed": completed, "open": open_eps, "unevaluable": unevaluable,
            "unknown_state_buy_days": unknown_buys, "buy_signal_on_final_session": final_buys}


def _pct(x):
    return None if x is None else round(100 * x, 3)


def completed_table(eps: list[dict]) -> dict:
    out = {"episodes": len(eps), "symbols": sorted({e["symbol"] for e in eps})}
    for p in POLICIES:
        runs = [(e["id"], e["runs"][p]) for e in eps]
        rets = [r["return"] for _, r in runs]
        hold = [r["full_exit_sessions"] for _, r in runs if r["full_exit_sessions"] is not None]
        worst = min(runs, key=lambda t: t[1]["return"]) if runs else None
        out[p] = {"mean_net_return_pct": _pct(statistics.fmean(rets)) if rets else None,
                  "median_net_return_pct": _pct(statistics.median(rets)) if rets else None,
                  "loss_share": round(sum(r < 0 for r in rets) / len(rets), 4) if rets else None,
                  "worst_episode": {"id": worst[0], "return_pct": _pct(worst[1]["return"])} if worst else None,
                  "holding_sessions_median": statistics.median(hold) if hold else None,
                  "holding_sessions_max": max(hold) if hold else None,
                  "exit_reasons": dict(Counter(r["exit_reason"] for _, r in runs)),
                  "not_fully_exited": len(runs) - len(hold)}
    out["B_principal"] = principal_summary(eps)
    return out


def principal_summary(eps: list[dict]) -> dict:
    b = [x for e in eps for x in e["b_principal"]]
    remaining = []
    for e in eps:
        r = e["runs"]["B"]
        tgt = [i for i, s in enumerate(r["sales"]) if s["reasons"] == ["TARGET"]]
        if not tgt:
            continue
        after = r["sales"][tgt[-1] + 1:]
        frac = 1 - sum(s["qty_fraction"] for s in r["sales"][:tgt[-1] + 1])
        if frac > 1e-9:  # kalan miktarın maliyeti = kalan oran (1 birimlik girişin payı)
            proceeds = sum(s["net"] for s in after) + (r["final_value"] - r["cash"])  # açıksa kalan × son kapanış
            remaining.append({"id": e["id"], "remaining_fraction": frac, "remaining_result": proceeds - frac})
    return {"target_partial_sales": len(b),
            "planned_principal_net_sum": round(sum(x["planned_net"] for x in b), 6),
            "actual_net_proceeds_sum": round(sum(x["actual_net"] for x in b), 6),
            "actual_below_planned": sum(x["actual_net"] < x["planned_net"] - 1e-12 for x in b),
            "actual_minus_planned_median_pct": _pct(statistics.median([x["actual_net"] - x["planned_net"] for x in b])) if b else None,
            "actual_minus_planned_min_pct": _pct(min((x["actual_net"] - x["planned_net"] for x in b), default=None)),
            "episodes_cum_net_reached_1_incl_later_sales": sum(e["runs"]["B"]["recovered"] for e in eps if e["b_principal"]),
            "remaining_positions": len(remaining),
            "remaining_positions_with_loss": sum(x["remaining_result"] < 0 for x in remaining),
            "remaining_result_min_pct": _pct(min((x["remaining_result"] for x in remaining), default=None)),
            "note": "Planlanan = T kapanışı × miktar × 0,999; gerçekleşen = T+1 açılışı varsayımsal dolum. Kalan pozisyon "
                    "risksiz değildir: sonucu = sonraki net satışlar (açıksa kapanış değerlemesi) − kalan oranın maliyeti."}


def open_table(eps: list[dict]) -> dict:
    out = {"episodes": len(eps), "ids": [e["id"] for e in eps],
           "note": "Referans veri sonunda açık; zorunlu satış yok. Değer = nakit + kalan × son kapanış (satış masrafı düşülmedi); "
                   "tamamlanmış satış DEĞİLDİR ve tamamlanmış tabloya katılmadı."}
    for p in POLICIES:
        runs = [e["runs"][p] for e in eps]
        still = [r for r in runs if r["open_at_end"]]
        out[p] = {"position_open_at_data_end": len(still), "fully_exited_before_data_end": len(runs) - len(still),
                  "remaining_fraction": [round(r["remaining_fraction"], 4) for r in runs],
                  "mark_to_close_value_minus_1_pct": [_pct(r["return"]) for r in runs],
                  "unrealized_units": [round(r["unrealized"], 4) for r in runs],
                  "unexecuted_request_at_data_end": [r["unexecuted_at_window_end"] for r in runs]}
    return out


def main(out: Path) -> int:
    out = out.resolve()
    review = json.loads(REVIEW.read_text(encoding="utf-8"))["symbols"]
    tech = json.loads(TECH.read_text(encoding="utf-8"))["results"]
    eligible = [s for s, r in review.items() if r["status"] == "READY_FOR_RESEARCH_WITH_LIMITS"]
    if not eligible:
        print("Uygun kapsam yok; çalıştırılmadı.", file=sys.stderr)
        return 4
    out.mkdir(parents=True, exist_ok=False)
    raw_paths = {s: PKG / f"{s}_official_raw.csv" for s in eligible}
    scoped = [{"symbol": s, "sha256": sha(raw_paths[s]), "status": "REVIEWED_NO_KNOWN_ISSUE",
               "scope": {"sessions": [review[s]["usable_sessions"][0], review[s]["usable_sessions"][-1]],
                         "session_count": len(review[s]["usable_sessions"]), "review_v3_sha256": sha(REVIEW),
                         "file": str(raw_paths[s].relative_to(BACKEND)).replace("\\", "/")},
               "basis": "Resmî BIST günlük bülteni ham satırları (OK; bayraksız); KAP inceleme v3 READY; kayıtlı sorunlar "
                        "Yahoo dosya kimliklerine aittir. Yalnız bu dosya kimliği ve seans aralığı için geçerlidir.",
               "reviewed": datetime.now().astimezone().isoformat()} for s in eligible]
    (out / "official_data_review.json").write_text(json.dumps(scoped, ensure_ascii=False, indent=1), encoding="utf-8")
    registry = load_registry()
    registry = dict(registry, reviews=list(registry.get("reviews", [])) + scoped)
    gate = check_input_files(raw_paths, registry)
    yahoo_gate = check_input_files({s: YAHOO / f"{s}_provider_ohlcv.csv" for s in eligible})  # bilgi: eski bloklar duruyor
    if gate["status"] == "BLOCKED":
        print(json.dumps({"status": "BLOCKED_KNOWN_DATA_ISSUE", "blocked": gate["blocked"]}, ensure_ascii=False, indent=1), file=sys.stderr)
        return 3
    inputs, not_run = {}, {}
    for s in eligible:
        x = symbol_inputs(s, review[s], tech.get(s, {"records": []}), raw_paths[s])
        (inputs if x["status"] == "RUN" else not_run)[s] = x
    res = evaluate_symbols(inputs)
    tables = {"completed_common": completed_table(res["completed"]), "open_at_data_end": open_table(res["open"]),
              "unevaluable": {"episodes": len(res["unevaluable"]), "reasons": dict(Counter(u["reason"] for u in res["unevaluable"])),
                              "items": res["unevaluable"],
                              "unknown_state_buy_days": res["unknown_state_buy_days"],
                              "buy_signal_on_final_session_no_next_session": res["buy_signal_on_final_session"]}}
    identity = {
        "created": datetime.now().astimezone().isoformat(), "network_calls": 0,
        "scope": "NORMALIZE_KESIFSEL: resmî ham bülten fiyatı, kesirli miktar; gerçek TL/tam lot/emir sonucu DEĞİL; tüm dolumlar "
                 "VARSAYIMSAL; dönem daha önce Yahoo ile incelendi, bağımsız holdout DEĞİL; BIST geneline genellenmez",
        "params": {"target_gross": TARGET, "stop": STOP, "trailing_C": TRAIL, "max_hold_sessions": MAX_HOLD,
                   "commission_each_side": C, "min_commission": 0, "extra_slippage": 0},
        "signal": "resmî veriden yeniden hesaplanan raw_class (V2 dondurulmuş ağırlık, DEFAULT_THRESHOLDS); T kapanışı -> "
                  "sonraki BEKLENEN seans açılışı",
        "eligible_symbols": eligible, "not_run": {s: v["reason"] for s, v in not_run.items()},
        "per_symbol": {s: {"raw_sha256": v["raw_sha256"], "allowed": v["allowed"], "dropped_bars": v["dropped_bars"],
                           "calendar_sessions_not_allowed": v["calendar_sessions_not_allowed"]} for s, v in inputs.items()},
        "review_v3_sha256": sha(REVIEW), "technical_results_sha256": sha(TECH),
        "official_data_review_sha256": sha(out / "official_data_review.json"),
        "code_sha256": {c: sha(BACKEND / c) for c in CODE},
        "data_issue_check_official": gate, "data_issue_check_yahoo_info": {"status": yahoo_gate["status"], "blocked": len(yahoo_gate["blocked"])},
    }
    (out / "result.json").write_text(json.dumps({"identity": identity, "tables": tables}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (out / "episodes.jsonl").open("w", encoding="utf-8") as fh:
        for kind in ("completed", "open"):
            for e in res[kind]:
                fh.write(json.dumps({"category": kind, **e}, ensure_ascii=False, default=str) + "\n")
    files = sorted(p for p in out.iterdir() if p.name != "hashes.json")
    (out / "hashes.json").write_text(json.dumps({p.name: sha(p) for p in files}, indent=1), encoding="utf-8")
    print(json.dumps(tables["completed_common"], ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in tables["open_at_data_end"].items()}, ensure_ascii=False))
    print(json.dumps({k: v for k, v in tables["unevaluable"].items() if k != "items"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
