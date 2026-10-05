"""EXIT-EXP-1 resmî 9 sembol — tamamlanmış + veri sonunda açık epizotların birlikte raporu (SONRADAN İSTENEN EK ANALİZ).

Kullanım (backend dizininden): python -X utf8 -m app.research.position_exit.combined_report <çıktı_klasörü>

* Strateji yeniden ÇALIŞTIRILMAZ; yalnız kayıtlı `episodes.jsonl` + `result.json` okunur, resmî ham CSV yalnız
  değerleme kapanışını doğrulamak için okunur. Kaynak klasör değiştirilmez; çıktı ayrı klasöre yazılır.
* Değerleme: tamamlanmış epizot = ortak referans çıkış açılışı (tüm politikalar o açılışta düz). Açık epizot = dört
  politika için aynı son izinli seans kapanışı. Epizot özsermayesi = net nakit (ödenmiş alış/satış komisyonları dahil)
  + kalan miktar × kapanış. Varsayımsal kapanış satışı ve komisyonu EKLENMEZ; açık değer tasfiye sonrası net tahsilat değildir.
* Ayrım: gerçekleşmiş K/Z = net nakit − satılan oranın maliyeti; gerçekleşmemiş = kalan piyasa değeri − kalan oranın
  maliyeti; toplam = özsermaye − 1. Maliyet = 1 birim (alış komisyonu dahil), oransal; masraf iki kez sayılmaz.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

from app.research.position_exit.normalized import C, POLICIES

BACKEND = Path(__file__).resolve().parents[3]
SRC = BACKEND / "app/research/position_exit/runs/exit_exp1_official9_20261001"
PKG = BACKEND / "app/research/official_bist/runs/raw_package_20260930/symbols"
TOL = 1e-9


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def account(ep: dict, policy: str, closes: dict[str, float]) -> dict:
    """Bir politikanın epizot muhasebesi; değerleme tarihi epizot için ortaktır."""
    r = ep["runs"][policy]
    q0 = 1.0 / (ep["entry_price"] * (1 + C))
    f = r["remaining_fraction"]
    if ep["end_kind"] == "REFERENCE_EXIT":
        when, price = ("open", ep["exit_session"]), None
        mv = 0.0
        if f > TOL:
            raise ValueError(f"{ep['id']} {policy}: referans çıkışında kalan miktar olamaz")
    else:
        when = ("close", ep["end_session"])
        price = closes[ep["end_session"]]
        mv = f * q0 * price
        if abs((r["final_value"] - r["cash"]) - mv) > 1e-9:
            raise ValueError(f"{ep['id']} {policy}: kayıtlı değer resmî kapanışla uyuşmuyor")
    cash = sum(s["net"] for s in r["sales"])
    if abs(cash - r["cash"]) > 1e-9:
        raise ValueError(f"{ep['id']} {policy}: satış tahsilatı toplamı kayıtlı nakitle uyuşmuyor")
    realized = cash - (1 - f)
    unrealized = mv - f
    equity = cash + mv
    total = equity - 1
    if abs(realized + unrealized - total) > 1e-9 or abs(total - r["return"]) > 1e-9:
        raise ValueError(f"{ep['id']} {policy}: muhasebe eşitliği sağlanmadı")
    return {"valuation": when, "valuation_price": price, "net_cash": cash, "remaining_fraction": f, "market_value": mv,
            "equity": equity, "realized_pnl": realized, "unrealized_pnl": unrealized, "total_change": total,
            "position_open": f > TOL, "exit_reason": r["exit_reason"]}


def _pct(x):
    return None if x is None else round(100 * x, 3)


def table(rows: list[dict]) -> dict:
    out = {"episodes": len(rows)}
    for p in POLICIES:
        v = [r["acct"][p]["total_change"] for r in rows]
        out[p] = {"n": len(v), "mean_pct": _pct(statistics.fmean(v)) if v else None,
                  "median_pct": _pct(statistics.median(v)) if v else None,
                  "negative_share": round(sum(x < 0 for x in v) / len(v), 4) if v else None,
                  "realized_mean_pct": _pct(statistics.fmean(r["acct"][p]["realized_pnl"] for r in rows)) if v else None,
                  "unrealized_mean_pct": _pct(statistics.fmean(r["acct"][p]["unrealized_pnl"] for r in rows)) if v else None,
                  "position_open_at_valuation": sum(r["acct"][p]["position_open"] for r in rows)}
        if p != "REF":
            d = [r["acct"][p]["total_change"] - r["acct"]["REF"]["total_change"] for r in rows]
            out[p]["vs_ref"] = {"mean_diff_pct": _pct(statistics.fmean(d)) if d else None,
                                "median_diff_pct": _pct(statistics.median(d)) if d else None,
                                "above_ref": sum(x > 1e-12 for x in d), "below_ref": sum(x < -1e-12 for x in d),
                                "equal_ref": sum(abs(x) <= 1e-12 for x in d)}
    return out


def main(out: Path) -> int:
    out = out.resolve()
    eps = [json.loads(line) for line in (SRC / "episodes.jsonl").read_text(encoding="utf-8").splitlines() if line]
    result = json.loads((SRC / "result.json").read_text(encoding="utf-8"))
    ids = [e["id"] for e in eps]
    n_c = result["tables"]["completed_common"]["episodes"]
    n_o = result["tables"]["open_at_data_end"]["episodes"]
    if len(set(ids)) != len(ids) or len(ids) != n_c + n_o or result["tables"]["unevaluable"]["episodes"] != 0:
        print("Epizot sayısı/benzersizliği doğrulanamadı; rapor üretilmedi.", file=sys.stderr)
        return 3
    raw = {}
    for e in eps:
        sym = e["symbol"]
        if sym not in raw:
            p = PKG / f"{sym}_official_raw.csv"
            bound = result["identity"]["per_symbol"][sym]["raw_sha256"]
            if sha(p) != bound:
                print(f"{sym}: ham CSV hash'i kayıtlı çalıştırmayla uyuşmuyor", file=sys.stderr)
                return 3
            raw[sym] = {r["trade_date"]: float(r["close"]) for r in csv.DictReader(p.open(encoding="utf-8")) if r["status"] == "OK"}
        e["acct"] = {pol: account(e, pol, raw[sym]) for pol in POLICIES}
        if e["end_kind"] != "REFERENCE_EXIT":
            last_allowed = result["identity"]["per_symbol"][sym]["allowed"][1]
            if e["end_session"] != last_allowed:
                print(f"{e['id']}: değerleme tarihi son izinli seans değil", file=sys.stderr)
                return 3
    completed = [e for e in eps if e["category"] == "completed"]
    open_eps = [e for e in eps if e["category"] == "open"]
    detail = {e["id"]: {"category": e["category"], "entry": [e["entry_session"], e["entry_price"]],
                        **{p: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in e["acct"][p].items()} for p in POLICIES},
                        "sales": {p: e["runs"][p]["sales"] for p in POLICIES}} for e in eps}
    report = {
        "identity": {"created": datetime.now().astimezone().isoformat(), "network_calls": 0, "strategy_rerun": False,
                     "nature": "SONRADAN İSTENEN EK ANALİZ; önceden belirlenmiş ana sonuç değildir",
                     "source_files_sha256": {f: sha(SRC / f) for f in ("result.json", "episodes.jsonl", "hashes.json")},
                     "code_sha256": sha(Path(__file__)),
                     "valuation": "tamamlanmış: ortak referans çıkış açılışı; açık: dört politika için aynı son izinli kapanış; "
                                  "kapanış satışı/komisyonu eklenmedi; açık değer tasfiye sonrası net tahsilat değildir",
                     "not": "Farklı tarihlerdeki epizot sonuçları; portföy getirisi, yıllık getiri veya TL sonucu değildir"},
        "tables": {"completed_23": table(completed), "reference_open_7": table(open_eps), "all_30": table(eps)},
        "open_episode_status": {e["id"]: {p: ("AÇIK" if e["acct"][p]["position_open"] else f"KAPALI ({e['acct'][p]['exit_reason']})")
                                          for p in POLICIES} for e in open_eps},
        "episodes": detail,
    }
    out.mkdir(parents=True, exist_ok=False)
    (out / "combined_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "hashes.json").write_text(json.dumps({"combined_report.json": sha(out / "combined_report.json")}, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("tables", "open_episode_status")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
