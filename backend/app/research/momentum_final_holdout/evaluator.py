"""Momentum FINAL prospektif holdout değerlendiricisi — KAPI KAPALIYKEN ÇALIŞMAZ (fail closed), TEK SEFERLİK.

Kullanım (backend klasöründen):
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final_holdout.evaluator freeze
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final_holdout.evaluator dry-run
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final_holdout.evaluator smoke-pilot
    .venv\\Scripts\\python.exe -X utf8 -m app.research.momentum_final_holdout.evaluator execute --one-shot

* dry-run: yalnız toplayıcı META verisi (FULL seans sınıfı, arşiv bütünlüğü, ham dosya hash'leri) + manifest/Label V2
  parmak izleri. Holdout barları/etiketleri/olayları/alarmları OKUNMAZ; yükleyiciler çağrılmaz.
* execute: kapı açıksa → yazma-bir-kez başlangıç kaydı → yükleme → değerlendirme → sonuç + FINAL_HOLDOUT_CONSUMED.
  Kapı kapalıysa FINAL_HOLDOUT_GATE_CLOSED + eksik koşullar; hiçbir yükleyici çağrılmaz. Tüketilmiş holdout'ta tekrar
  çalıştırma yalnız `--reanalysis` ile ve REANALYSIS_OF_CONSUMED_HOLDOUT etiketiyle (aday seçiminde kullanılamaz).
* smoke-pilot: aynı yükleme hattı YALNIZ pilot seanslarında (pilot HoldoutGuard altında); yalnız yapısal sayımlar,
  performans metriği/PASS-FAIL YOK.
Model eğitimi, eşik araması, aday seçimi YOKTUR: kurallar manifestteki sabit tanımlardır.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from app.research.momentum_final import candidate as cd
from app.research.momentum_final_holdout import protocol as pr
from app.research.momentum_label_v2 import labels as lv

GATE_CLOSED = "FINAL_HOLDOUT_GATE_CLOSED"
GATE_OPEN = "FINAL_HOLDOUT_GATE_OPEN"
CONSUMED = "FINAL_HOLDOUT_CONSUMED"
REANALYSIS = "REANALYSIS_OF_CONSUMED_HOLDOUT"
START_RECORD = "FINAL_HOLDOUT_STARTED.json"
RESULT_FILE = "final_holdout_result.json"
MIN_NS = lv.MIN_NS
# manifestteki kural kimliği → mevcut maske üreticisinin (`momentum_label_v2.experiment.masks`) anahtarı
MASK_KEYS = {"A_ROUND1_FINAL_WATCH_3OF3_D15": "round1_final_watch_3of3",
             "B_ROUND1_FINAL_STRONG_3OF3_D15": "round1_final_strong_3of3",
             "C_FROZEN_REL_RET_Z3_1OF1_D15": "frozen_candidate_watch_1of1"}


class GateClosedError(RuntimeError):
    pass


# ------------------------------------------------------------------ girdiler
@dataclass
class EvalInput:
    """Satırlar seans ve zaman sıralı. `t_ns` = d15 GÖRÜNÜR zaman; `events` gecikmeden bağımsız V2 olayları."""
    sessions: list[tuple[str, str]]
    sess: np.ndarray
    seg_start: np.ndarray
    t_ns: np.ndarray
    entry: np.ndarray
    events: list[list[lv.Swing]]
    masks: dict[str, np.ndarray]


@dataclass
class NewsData:
    """Foreks kanonik haber satırları (öğe × sembol tek satır) + tamamlanmış getirme zamanları."""
    items: list[dict]  # item_key, symbol, received_ns, published_ns, event_type
    fetch_ns: np.ndarray
    first_fetch_ns: int | None
    revisions: dict = field(default_factory=dict)  # (item_key, symbol) → farklı düzenleme sayısı (meta veri)


class GateToken:
    """Yalnız `execute` kapı açıkken üretir; gerçek holdout yükleyicileri bunu ister."""
    _key = object()

    def __init__(self, key, sessions: list[str]):
        if key is not GateToken._key:
            raise GateClosedError("holdout loader requires a token issued by an open final gate")
        self.sessions = list(sessions)


# ------------------------------------------------------------------ metrikler (saf)
def _local_min(ns: int) -> int:
    return (int(ns) // MIN_NS + 180) % 1440  # UTC → Europe/Istanbul (+3, yaz saati yok)


def _med(v):
    return float(np.median(v)) if len(v) else None


def rule_metrics(inp: EvalInput, mask: np.ndarray) -> dict:
    m = lv.evaluate(mask, inp.sess, inp.seg_start, inp.t_ns, inp.entry, inp.events, lv.FIRST_ALERT)
    onset = lv.evaluate(mask, inp.sess, inp.seg_start, inp.t_ns, inp.entry, inp.events, lv.ALERT_ONSET)
    cls = m["alert_classes"]
    tp = cls[lv.IN_EVENT] + cls[lv.IN_EVENT_DUPLICATE]
    leads = [e["lead"] for e in m["_events"] if e["caught"] and e["lead"] is not None]
    per_date: dict[str, list[int]] = {}
    for s, (_, day) in enumerate(inp.sessions):
        per_date.setdefault(day, [0, 0])[1] += 1
    for a in m["_alerts"]:
        per_date[inp.sessions[a["sess"]][1]][0] += 1
    return {
        "evaluable_events": m["event_count_evaluable"], "raw_events": m["event_count_raw"],
        "primary_alerts": m["alerts"], "TP": tp, "FP": m["alerts"] - tp,
        "precision": m["precision_v2"], "raw_recall": m["recall_raw_v2"],
        "evaluable_recall": m["recall_evaluable_v2"], "non_event_sessions": m["non_event_sessions"],
        "FPR": m["FPR_v2"], "median_visible_lead": m["median_lead_v2"],
        "lead_le_0_50_share": (sum(x <= lv.LEAD_TARGET for x in leads) / len(leads)) if leads else None,
        "pre_observation_events": sum(e["event_class"] == lv.PRE_OBSERVATION for e in m["_events"]),
        "post_peak_alerts": cls[lv.POST_PEAK], "pre_event_alerts": cls[lv.PRE_EVENT],
        "duplicate_alerts": cls[lv.IN_EVENT_DUPLICATE], "no_event_session_alerts": cls[lv.NO_EVENT],
        "activations_collapsed": onset["alerts"] - m["alerts"],
        "alarm_density_per_session": {d: {"alerts": a, "asset_sessions": n, "density": a / n if n else None}
                                      for d, (a, n) in sorted(per_date.items())},
        "_events": m["_events"], "_alerts": m["_alerts"]}


def pass_fail(metrics: dict, targets: dict = pr.TARGETS) -> dict:
    """HEPSİ gerekli; eksik metrik = FAIL. Ağırlık yok, 'neredeyse' yok."""
    ops = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b}
    checks = {k: (metrics.get(k) is not None and ops[op](metrics[k], v)) for k, (op, v) in targets.items()}
    return {"checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"}


def subset(inp: EvalInput, keep: set[int]) -> EvalInput:
    rows = np.flatnonzero(np.isin(inp.sess, sorted(keep)))
    old = sorted(keep)
    remap = {s: i for i, s in enumerate(old)}
    sess = np.array([remap[int(s)] for s in inp.sess[rows]], dtype=int)
    first = {}
    for i, s in enumerate(sess):
        first.setdefault(int(s), i)
    return EvalInput([inp.sessions[s] for s in old], sess, np.array([first[int(s)] for s in sess], dtype=int),
                     inp.t_ns[rows], inp.entry[rows], [inp.events[s] for s in old],
                     {k: v[rows] for k, v in inp.masks.items()})


def session_groups(inp: EvalInput) -> dict[str, set[int]]:
    share: dict[str, list[int]] = {}
    for s, (_, day) in enumerate(inp.sessions):
        share.setdefault(day, [0, 0])
        share[day][0] += bool(inp.events[s])
        share[day][1] += 1
    broad = {d for d, (e, n) in share.items() if n and e / n >= pr.BROAD_MARKET_EVENT_SHARE}
    return {"broad_market_high_participation_sessions": {s for s, (_, d) in enumerate(inp.sessions) if d in broad},
            "normal_sessions": {s for s, (_, d) in enumerate(inp.sessions) if d not in broad}}


def event_category(ev: lv.Swing) -> list[str]:
    hh, mm_ = map(int, pr.OPENING_PERIOD_END.split(":"))
    cats = ["opening_period_events" if _local_min(ev.start_ns) < hh * 60 + mm_ else "intraday_events"]
    if ev.evaluable and ev.peak_ns - ev.start_ns < pr.DELAY_MINUTES * MIN_NS:
        cats.append("yahoo_latency_lost_events")
    return cats


def breakdowns(inp: EvalInput, mask: np.ndarray, base: dict) -> dict:
    out = {}
    for name, keep in session_groups(inp).items():
        if keep:
            m = rule_metrics(subset(inp, keep), mask[np.isin(inp.sess, sorted(keep))])
            out[name] = {k: m[k] for k in ("evaluable_events", "primary_alerts", "evaluable_recall", "FPR",
                                           "median_visible_lead", "non_event_sessions")} | {"sessions": len(keep)}
        else:
            out[name] = {"sessions": 0}
    cats: dict[str, list[dict]] = {}
    for e in base["_events"]:
        if e["evaluable"]:
            for c in event_category(inp.events[e["sess"]][e["k"]]):
                cats.setdefault(c, []).append(e)
    for c in ("opening_period_events", "intraday_events", "yahoo_latency_lost_events"):
        evs = cats.get(c, [])
        leads = [e["lead"] for e in evs if e["caught"] and e["lead"] is not None]
        out[c] = {"evaluable_events": len(evs), "caught": sum(e["caught"] for e in evs),
                  "evaluable_recall": (sum(e["caught"] for e in evs) / len(evs)) if evs else None,
                  "median_visible_lead": _med(leads)}
    return out


# ------------------------------------------------------------------ ikincil haber analizi (açıklayıcı)
def logical_catalysts(items: list[dict]) -> list[dict]:
    """(item_key, symbol) başına TEK mantıksal katalizör; düzenlemeler yeni katalizör eklemez."""
    best: dict[tuple, dict] = {}
    for it in items:
        k = (it["item_key"], it["symbol"])
        if k not in best or it["received_ns"] < best[k]["received_ns"]:
            best[k] = it
    return list(best.values())


def news_eligible(nd: NewsData, obs_ns: int, window_min: int) -> bool:
    """Pencere boyunca Foreks toplayıcısı çalışıyordu: ardışık tamamlanmış getirmeler arası <= 15 dk ve pencere ilk
    prospektif getirmeden sonra. Aksi halde gözlenmedi (NO_NEWS DEĞİL)."""
    g = pr.NEWS_MAX_FETCH_GAP_MIN * MIN_NS
    start = obs_ns - window_min * MIN_NS
    if nd.first_fetch_ns is None or start < nd.first_fetch_ns:
        return False
    f = nd.fetch_ns[(nd.fetch_ns >= start - g) & (nd.fetch_ns <= obs_ns)]
    if not len(f) or f[0] > start + g or obs_ns - f[-1] > g:
        return False
    return bool(np.all(np.diff(f) <= g))


def news_status(nd: NewsData, catalysts: list[dict], symbol: str, obs_ns: int, window_min: int) -> tuple[str, list]:
    if not news_eligible(nd, obs_ns, window_min):
        return pr.NEWS_NOT_OBSERVED, []
    lo = obs_ns - window_min * MIN_NS
    hit = [c for c in catalysts if c["symbol"] == symbol and lo < c["received_ns"] <= obs_ns]  # received_at!
    return (pr.NEWS_PRESENT if hit else pr.NO_NEWS), hit


def _news_counts(points: list[tuple[str, int]], nd, cats, w) -> dict:
    c = {pr.NEWS_NOT_OBSERVED: 0, pr.NO_NEWS: 0, pr.NEWS_PRESENT: 0, "present_only_other": 0,
         "present_non_other": 0, "present_with_revision_metadata": 0}
    for sym, obs in points:
        st, hit = news_status(nd, cats, sym, obs, w)
        c[st] += 1
        if st == pr.NEWS_PRESENT:
            c["present_non_other" if any(h["event_type"] != "other" for h in hit) else "present_only_other"] += 1
            c["present_with_revision_metadata"] += any(nd.revisions.get((h["item_key"], h["symbol"]))
                                                       for h in hit)
    elig = c[pr.NO_NEWS] + c[pr.NEWS_PRESENT]
    c["news_eligible"] = elig
    c["present_share_of_eligible"] = c[pr.NEWS_PRESENT] / elig if elig else None
    return c


def news_analysis(inp: EvalInput, per_rule: dict[str, dict], nd: NewsData) -> dict:
    cats = [c for c in logical_catalysts(nd.items) if c["symbol"] != "UNRESOLVED"]
    ev_points = [(inp.sessions[s][0], ev.start_ns) for s, evs in enumerate(inp.events) for ev in evs if ev.evaluable]
    out = {"role": "DESCRIPTIVE ONLY", "logical_catalysts": len(cats),
           "events_by_window": {w: _news_counts(ev_points, nd, cats, w) for w in pr.NEWS_WINDOWS_MIN}, "rules": {}}
    for rid, m in per_rule.items():
        al = [(inp.sessions[a["sess"]][0], int(inp.t_ns[a["row"]])) for a in m["_alerts"]]
        leads = {}
        for w in pr.NEWS_WINDOWS_MIN:
            obs_leads = [e["lead"] for e in m["_events"] if e["evaluable"] and e["caught"] and e["lead"] is not None
                         and news_status(nd, cats, inp.sessions[e["sess"]][0],
                                         inp.events[e["sess"]][e["k"]].start_ns, w)[0] == pr.NEWS_PRESENT]
            leads[w] = {"n": len(obs_leads), "median_visible_lead": _med(obs_leads)}
        out["rules"][rid] = {"primary_alerts_by_window": {w: _news_counts(al, nd, cats, w) for w in pr.NEWS_WINDOWS_MIN},
                             "news_observed_caught_event_lead": leads}
    return out


# ------------------------------------------------------------------ değerlendirme (saf)
def evaluate(inp: EvalInput, nd: NewsData | None, rules: list[dict]) -> dict:
    out = {}
    per = {}
    for r in rules:
        rid = r["rule_id"]
        if r["status"] != pr.EVALUABLE or rid not in inp.masks:
            out[rid] = {"status": pr.NOT_EVALUABLE, "verdict": pr.NOT_EVALUABLE}
            continue
        m = rule_metrics(inp, inp.masks[rid])
        per[rid] = m
        out[rid] = {"status": pr.EVALUABLE, "config_sha256": r["config_sha256"],
                    **{k: v for k, v in m.items() if not k.startswith("_")},
                    **pass_fail(m), "stress": breakdowns(inp, inp.masks[rid], m)}
    passing = [k for k, v in out.items() if v.get("verdict") == "PASS"]
    return {"rules": out, "asset_sessions": len(inp.sessions),
            "sessions": sorted({d for _, d in inp.sessions}),
            "conclusion": ("rules PASS independently: " + ", ".join(passing)) if passing else
            "no predeclared rule passed; current OHLCV architectures do not satisfy the target",
            "selection_note": "holdout is evaluation, not selection; no rule is promoted to a new candidate",
            "news_secondary": news_analysis(inp, per, nd) if nd is not None else None}


# ------------------------------------------------------------------ kapı
def collect_gate_state() -> dict:
    """YALNIZ meta veri: FULL seans sınıfı, arşiv bütünlüğü, holdout dönemi ham dosyaları, düzeltme zinciri."""
    from app.research.momentum_collector import amendments as am
    from app.research.momentum_collector import integrity as ig
    from app.research.momentum_collector import manifest as mm
    from app.research.momentum_collector import snapshot as sn
    from app.research.momentum_label_v2 import experiment as lx
    from app.research.momentum_pilot import split as sp
    m = mm.load()
    c = m["config"]
    pm = sp.load_manifest()
    a = am.readonly_archive()
    try:
        sess = ig.classify_sessions(a, c["benchmark"])
        full = sp.observed_full_sessions(sess, c["prospective_start_session"])
        cutoff = pm["manifest"]["pilot_cutoff_session"]
        integ = ig.verify_archive(a, m)
        reqs = a.db.execute("SELECT raw_path, response_hash FROM requests WHERE retrieved_at >= ? ORDER BY "
                            "response_hash", (pr.HOLDOUT_START,)).fetchall()
        missing = sum(1 for p, _ in reqs if not p or not (a.root / p).exists())
        invalid = sum(1 for p, h in reqs if p and (a.root / p).exists() and not a.raw_hash_valid(p, h))
    finally:
        a.close()
    try:
        label_sha = lx.load_manifest()["sha256"]
    except Exception as e:
        label_sha = f"ERROR {type(e).__name__}"
    try:
        chain = am.verify_chain(sn.load())["approved_amendment_chain_valid"]
    except Exception:
        chain = False
    return {"pilot_manifest_sha256": pm["sha256"], "pilot_cutoff": cutoff,
            "holdout_sessions": [d for d in full if d > cutoff and d >= pr.HOLDOUT_START],
            "short_sessions": sorted(sess.loc[(sess["session_class"] != "FULL")
                                              & (sess["session_date"] >= pr.HOLDOUT_START), "session_date"]),
            "archive_integrity": bool(integ["ok"]), "raw_requests": len(reqs), "raw_missing": missing,
            "raw_invalid": invalid,
            "raw_fingerprint": hashlib.sha256("\n".join(h for _, h in reqs).encode()).hexdigest(),
            "label_v2_sha256": label_sha, "amendment_chain_valid": bool(chain)}


def check_gate(state: dict, manifest_path: Path = pr.MANIFEST_PATH, state_dir: Path = pr.STATE_DIR,
               reanalysis: bool = False, payload: dict | None = None) -> dict:
    missing = []
    n = len(state["holdout_sessions"])
    if n < pr.REQUIRED_FULL_SESSIONS:
        missing.append(f"future_holdout_full_sessions {n} < {pr.REQUIRED_FULL_SESSIONS}")
    if not state["archive_integrity"]:
        missing.append("archive integrity != OK")
    if state["raw_missing"] or state["raw_invalid"] or not state["raw_requests"]:
        missing.append(f"required raw files: missing={state['raw_missing']} invalid={state['raw_invalid']} "
                       f"requests={state['raw_requests']}")
    if state["label_v2_sha256"] != pr.LABEL_V2_SHA256:
        missing.append(f"Label V2 fingerprint {state['label_v2_sha256']} != {pr.LABEL_V2_SHA256}")
    if state.get("pilot_manifest_sha256") != pr.PILOT_MANIFEST_SHA256 or state.get("pilot_cutoff") != pr.PILOT_CUTOFF:
        missing.append("pilot split manifest fingerprint/cutoff mismatch")
    manifest_sha = None
    try:
        m = pr.load_manifest(manifest_path)
        manifest_sha = m["manifest_sha256"]
        if not pr.manifest_matches_code(m, payload):
            missing.append("protocol manifest fingerprint != current protocol code")
    except pr.ProtocolError as e:
        missing.append(f"protocol manifest: {e}")
    consumed = (state_dir / CONSUMED).exists()
    started = (state_dir / START_RECORD).exists()
    if reanalysis:
        if not consumed:
            missing.append("reanalysis requested but holdout not consumed")
    elif consumed or started:
        missing.append("previous final evaluation start/completion record exists (use reanalysis; never selection)")
    return {"status": GATE_OPEN if not missing else GATE_CLOSED, "open": not missing, "missing": missing,
            "future_holdout_full_sessions": n, "required_full_sessions": pr.REQUIRED_FULL_SESSIONS,
            "missing_full_sessions_count": max(0, pr.REQUIRED_FULL_SESSIONS - n), "manifest_sha256": manifest_sha,
            "mode": REANALYSIS if reanalysis else "FIRST_FINAL_EVALUATION"}


def _write_once(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False, default=str) + "\n")


def execute(loader, news_loader, state: dict | None = None, *, reanalysis: bool = False,
            manifest_path: Path = pr.MANIFEST_PATH, state_dir: Path = pr.STATE_DIR, now=None,
            payload: dict | None = None, head: str | None = None, preflight=None) -> dict:
    """Kapı VEYA ek ön kontrol (preflight) kapalıysa yükleyiciler ÇAĞRILMAZ. İkisi de açıksa: başlangıç kaydı
    (yazma-bir-kez) → yükle → değerlendir → sonuç (yazma-bir-kez) → FINAL_HOLDOUT_CONSUMED.
    `preflight`: None → gerçek `preflight.run`; çağrılabilir → onun sonucu (testler); sonuç `open` değilse KAPALI."""
    state = collect_gate_state() if state is None else state
    gate = check_gate(state, manifest_path, state_dir, reanalysis, payload)
    if not gate["open"]:
        return {"gate": gate}
    if preflight is None:
        from app.research.momentum_final_holdout import preflight as pf
        pre = pf.run(reanalysis)
    else:
        pre = preflight()
    if not (isinstance(pre, dict) and pre.get("open") is True):
        return {"gate": {**gate, "status": GATE_CLOSED, "open": False,
                         "missing": [f"preflight: {x}" for x in (pre or {}).get("failed", ["unknown"])]},
                "preflight": pre}
    m = pr.load_manifest(manifest_path)
    sessions = sorted(state["holdout_sessions"])[:pr.REQUIRED_FULL_SESSIONS]
    ts = (now or datetime.now(timezone.utc)).isoformat()
    record = {"mode": gate["mode"], "protocol_sha256": m["protocol_sha256"], "manifest_sha256": m["manifest_sha256"],
              "label_v2_sha256": state["label_v2_sha256"], "amendment_chain_valid": state["amendment_chain_valid"],
              "eligible_sessions": sessions, "raw_input_fingerprint": state["raw_fingerprint"],
              "raw_requests": state["raw_requests"], "preflight_checks": pre.get("checks"),
              "code_head": head if head is not None else pr.git_head(),
              "timestamp": ts}
    if reanalysis:
        tag = ts.replace(":", "").replace("-", "")[:15]
        _write_once(state_dir / f"reanalysis_{tag}_start.json", record)
    else:
        _write_once(state_dir / START_RECORD, record)
    token = GateToken(GateToken._key, sessions)
    inp = loader(token)
    nd = news_loader(token)
    result = {"label": gate["mode"], "start_record": record,
              **evaluate(inp, nd, m["protocol"]["rules"])}
    if reanalysis:
        result["warning"] = "REANALYSIS_OF_CONSUMED_HOLDOUT — never used for candidate selection"
        _write_once(state_dir / f"reanalysis_{tag}_result.json", result)
    else:
        _write_once(state_dir / RESULT_FILE, result)
        _write_once(state_dir / CONSUMED, {"consumed_at": datetime.now(timezone.utc).isoformat(),
                                           "protocol_sha256": m["protocol_sha256"], "sessions": sessions})
    return {"gate": gate, "result": result}


# ------------------------------------------------------------------ protokol V2 yürütme (tek seferlik)
FINGERPRINT_MISMATCH = "INVALID_FINGERPRINT_MISMATCH"


def execute_v2(loader, news_loader, state: dict | None = None, *, reanalysis: bool = False,
               manifest_path: Path = pr.MANIFEST_PATH, v2_path: Path | None = None, state_dir: Path = pr.STATE_DIR,
               now=None, payload: dict | None = None, head: str | None = None, preflight=None,
               evaluate_fn=None) -> dict:
    """V1 temel kapısı + V2 ön kontrolü + ön kontrol/çalıştırma parmak izi eşitliği. Herhangi biri sağlanmazsa
    yükleyiciler ÇAĞRILMAZ. `loader(token)` → modes.build_mode_inputs çıktısı."""
    from app.research.momentum_final_holdout import modes as md
    from app.research.momentum_final_holdout import preflight as pf
    from app.research.momentum_final_holdout import protocol_v2 as p2
    v2_path = p2.MANIFEST_V2_PATH if v2_path is None else v2_path
    state = collect_gate_state() if state is None else state
    gate = check_gate(state, manifest_path, state_dir, reanalysis, payload)

    def closed(reasons, pre=None):
        return {"gate": {**gate, "status": GATE_CLOSED, "open": False, "missing": gate["missing"] + reasons},
                "preflight": pre}
    if not gate["open"]:
        return {"gate": gate}
    pre = pf.run_v2(reanalysis) if preflight is None else preflight()
    if not (isinstance(pre, dict) and pre.get("open") is True):
        return closed([f"preflight_v2: {x}" for x in (pre or {}).get("failed", ["unknown"])], pre)
    sessions = sorted(state["holdout_sessions"])[:pr.REQUIRED_FULL_SESSIONS]
    if pre.get("holdout_sessions") != sessions or pre.get("raw_fingerprint") != state["raw_fingerprint"]:
        return closed(["preflight/execution session list or raw fingerprint differ"], pre)
    m2 = p2.load_v2(v2_path)
    evaluable = list(m2["protocol"]["evaluable_universe"]["symbols"])
    if pre.get("evaluable") != evaluable:
        return closed(["preflight evaluable list differs from frozen V2 list"], pre)
    ts = (now or datetime.now(timezone.utc)).isoformat()
    record = {"mode": gate["mode"], "protocol_v1_sha256": pr.load_manifest(manifest_path)["protocol_sha256"],
              "protocol_v2_sha256": m2["protocol_sha256"], "manifest_v2_sha256": m2["manifest_sha256"],
              "label_v2_sha256": state["label_v2_sha256"], "amendment_chain_valid": state["amendment_chain_valid"],
              "eligible_sessions": sessions, "evaluable_assets": evaluable,
              "raw_input_fingerprint": state["raw_fingerprint"], "raw_requests": state["raw_requests"],
              "preflight_checks": pre.get("checks"), "code_head": head if head is not None else pr.git_head(),
              "timestamp": ts}
    tag = ts.replace(":", "").replace("-", "")[:15]
    _write_once(state_dir / (f"reanalysis_{tag}_start.json" if reanalysis else START_RECORD), record)
    token = GateToken(GateToken._key, sessions)
    inputs = loader(token)
    nd = news_loader(token)
    fp = inputs.get("fingerprint", {})
    if fp.get("sessions") != sessions or not set(fp.get("symbols", [])) <= set(evaluable):
        result = {"label": gate["mode"], "status": FINGERPRINT_MISMATCH, "start_record": record, "loaded": fp}
    else:
        fn = evaluate_fn or md.evaluate_modes
        result = {"label": gate["mode"], "status": "COMPLETED", "start_record": record,
                  "generalization": m2["protocol"]["disclosure"]["generalization"],
                  **fn(inputs["A"], inputs["B"], inputs["C"], nd, m2["protocol"]["rules"])}
    if reanalysis:
        result["warning"] = "REANALYSIS_OF_CONSUMED_HOLDOUT — never used for candidate selection"
        _write_once(state_dir / f"reanalysis_{tag}_result.json", result)
    else:
        _write_once(state_dir / RESULT_FILE, result)
        _write_once(state_dir / CONSUMED, {"consumed_at": datetime.now(timezone.utc).isoformat(),
                                           "protocol_v2_sha256": m2["protocol_sha256"], "sessions": sessions})
    return {"gate": gate, "preflight": pre, "result": result}


def load_holdout_inputs_v2(token: GateToken) -> dict:
    if not isinstance(token, GateToken):
        raise GateClosedError("holdout loader requires a gate token")
    from app.research.momentum_final_holdout import modes as md
    from app.research.momentum_final_holdout import protocol_v2 as p2
    evaluable = p2.load_v2()["protocol"]["evaluable_universe"]["symbols"]
    return md.build_mode_inputs(_SessionGuard(max(token.sessions)), token.sessions, evaluable)


# ------------------------------------------------------------------ gerçek yükleyiciler (yalnız jetonla)
class _SessionGuard:
    """`momentum_pilot.split` yükleyicilerinin beklediği arayüz: izin verilen son seansı aşan istek HATA."""

    def __init__(self, last_allowed: str):
        self.cutoff = last_allowed

    def check_session(self, s):
        if str(s) > self.cutoff:
            from app.research.momentum_pilot import split as sp
            raise sp.HoldoutAccessError(f"session {s} beyond allowed {self.cutoff}")

    def check_sessions(self, ss):
        for s in ss:
            self.check_session(s)

    def check_frame(self, df, col="session_date"):
        if len(df):
            self.check_session(str(df[col].max()))
        return df


def build_input(guard, eval_sessions: list[str], workers: int = 7) -> EvalInput:
    """Pilot hattıyla AYNI: FIRST_SEEN 5m barları, üretim öznitelikleri, d15 etiket zamanı, V2 olayları, maskeler."""
    from app.research.momentum_collector import manifest as mm
    from app.research.momentum_final import experiment as mf
    from app.research.momentum_label_v2 import experiment as lx
    from app.research.momentum_pilot import analysis as an
    from app.research.momentum_pilot import experiment as pe
    from app.research.momentum_pilot import split as sp
    c = mm.load()["config"]
    last = max(eval_sessions)
    a = pe._ReadOnlyArchive()
    try:
        full, warm = pe.session_classes(a)
        sessions = warm + [d for d in full if d <= last]
        b5 = sp.load_primary_bars(a.db, guard, sessions, "5m", list(c["universe"]) + [c["benchmark"]])
    finally:
        a.close()
    data = {s: an.to_asset_data(s, g) for s, g in b5.groupby("symbol")}
    bench = data.pop(c["benchmark"])
    rows = an.build_rows(data, bench, [date.fromisoformat(d) for d in eval_sessions], workers)
    p = an.PilotPanel(rows, {s: d.bars for s, d in data.items()})
    p.build_labels(pr.DELAY_MINUTES)
    events, _gap = an.build_events(p)
    raw = lx.masks(p, cd.load_frozen(mf.MANIFEST)["candidate"])
    lab = p.labels[pr.DELAY_MINUTES]
    return EvalInput([(s, str(d)) for s, d in p.sessions], p.sess, p.seg_start, lab.t_ns, lab.entry, events,
                     {rid: raw[k] for rid, k in MASK_KEYS.items()})


def load_holdout_input(token: GateToken) -> EvalInput:
    if not isinstance(token, GateToken):
        raise GateClosedError("holdout loader requires a gate token")
    return build_input(_SessionGuard(max(token.sessions)), token.sessions)


def load_news(token) -> NewsData:
    import sqlite3
    from app.research.momentum_sources import storage as ss
    db = sqlite3.connect(f"file:{(ss.DEFAULT_ROOT / ss.DB_NAME).as_posix()}?mode=ro", uri=True)
    try:
        def ns(t):
            return int(datetime.fromisoformat(t).timestamp() * 1e9) if t else None
        items = [{"item_key": k, "symbol": s, "received_ns": ns(r), "published_ns": ns(p), "event_type": e}
                 for k, s, r, p, e in db.execute("SELECT item_key, symbol, received_at, published_at, event_type "
                                                 "FROM news_events WHERE provider='foreks'")]
        fetch = np.array(sorted(ns(r) for (r,) in db.execute(
            "SELECT received_at FROM source_runs WHERE provider='foreks' AND kind='news_archive' AND "
            "status='COMPLETED'")), dtype=np.int64)
        revs = {(k, s): n for k, s, n in db.execute("SELECT item_key, symbol, COUNT(*) FROM source_revisions "
                                                     "WHERE provider='foreks' GROUP BY 1, 2")}
    finally:
        db.close()
    return NewsData(items, fetch, int(fetch[0]) if len(fetch) else None, revs)


# ------------------------------------------------------------------ CLI
def main(argv: list[str]) -> int:
    from app.research.momentum_final_holdout import report
    cmd = argv[0] if argv else "dry-run"
    if cmd == "freeze":
        m, created = pr.freeze_manifest()
        print(json.dumps({"created": created, "manifest_sha256": m["manifest_sha256"],
                          "protocol_sha256": m["protocol_sha256"], "git_head": m["git_head"],
                          "created_at": m["created_at"],
                          "rules": [(r["rule_id"], r["status"], r.get("config_sha256")) for r in
                                    m["protocol"]["rules"]]}, indent=1))
        return 0
    if cmd == "dry-run":
        from app.research.momentum_final_holdout import preflight as pf
        state = collect_gate_state()
        print(report.dry_run_text(state, check_gate(state)))
        pre = pf.run()
        print(json.dumps({"preflight_status": pre["status"], "failed": pre["failed"], "checks": pre["checks"],
                          "coverage_dataset": {k: pre["coverage_dataset"].get(k) for k in (
                              "asset_sessions", "minimum_asset_sessions", "minimum_sessions_per_primary_asset",
                              "assets_below_minimum", "min_sessions_any_asset")},
                          "coverage_holdout_only_report": pre["coverage_holdout_only_report"]}, indent=1))
        return 0
    if cmd == "smoke-pilot":
        from app.research.momentum_pilot import split as sp
        pm = sp.load_manifest()
        inp = build_input(sp.HoldoutGuard(pm), list(pm["manifest"]["pilot_sessions"]))
        print(report.smoke_text(inp, load_news(None)))
        return 0
    if cmd == "freeze-v2":
        from app.research.momentum_final_holdout import protocol_v2 as p2
        m, created = p2.freeze_v2()
        p = m["protocol"]
        print(json.dumps({"created": created, "protocol_v2_sha256": m["protocol_sha256"],
                          "manifest_v2_sha256": m["manifest_sha256"], "git_head": m["git_head"],
                          "created_at": m["created_at"], "previous": p["previous_protocol"],
                          "evaluable": p["evaluable_universe"]["count"], "excluded": p["excluded_assets"]},
                         indent=1, ensure_ascii=False))
        return 0
    if cmd == "dry-run-v2":
        from app.research.momentum_final_holdout import preflight as pf
        state = collect_gate_state()
        gate = check_gate(state)
        pre = pf.run_v2()
        print(json.dumps({"base_gate": gate["status"], "base_missing": gate["missing"],
                          "future_holdout_full_sessions": gate["future_holdout_full_sessions"],
                          "preflight_v2": pre["status"], "failed": pre["failed"], "checks": pre["checks"],
                          "info": pre["info"], "excluded": pre["excluded"],
                          "holdout_outcomes": "UNREAD (no loaders called)"}, indent=1, ensure_ascii=False))
        return 0
    if cmd == "execute":
        if "--one-shot" not in argv and "--reanalysis" not in argv:
            print("refusing: pass --one-shot (first final evaluation) or --reanalysis")
            return 2
        out = execute_v2(load_holdout_inputs_v2, load_news, reanalysis="--reanalysis" in argv)
        print(json.dumps(out["gate"], indent=1))
        return 0 if out["gate"]["open"] else 3
    print(f"unknown command {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
