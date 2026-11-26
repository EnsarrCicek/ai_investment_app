"""Protokol V2 değerlendirme modları — A (d15, birincil), B (d20, duyarlılık), C (gerçek first_seen kullanılabilirliği).

Satır anlamı (dondurulmuş hat): `t` = d15 karar/görünür zamanı; öznitelikler bar_end <= t − 15 dk olan barlardan
(BİLGİ ZAMANI). Mod B: aynı satırlar t + 5 dk'da (bilgi zamanı + 20 dk) görünür. Mod C: satır, bağımlı olduğu her
sembolün bar_end <= bilgi zamanı olan TÜM barlarının en geç first_seen anında görünür (kümülatif maksimum); değerler
ilk görülen değerlerdir (revizyon uygulanmaz); seansın son gösterge barı bitişinden sonra görünen satır kullanılamaz.
Kurallar/eşikler/etiketler DEĞİŞMEZ; yalnız görünür zaman ve giriş fiyatının alındığı an değişir.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from app.research.momentum_final_holdout import evaluator as ev
from app.research.momentum_final_holdout import protocol_v2 as p2

MIN_NS = ev.MIN_NS
NO_TIME = np.iinfo(np.int64).max


# ------------------------------------------------------------------ saf: gözlenen kullanılabilirlik
def observed_visibility(info_ns: np.ndarray, bar_end_ns: np.ndarray, first_seen_ns: np.ndarray) -> np.ndarray:
    """Her bilgi zamanı için: bar_end <= bilgi zamanı olan barların en geç first_seen'i (yoksa NO_TIME).
    Gelecekte görülen bir bar geçmişe TAŞINMAZ: satır o bar görülene kadar kullanılamaz."""
    order = np.argsort(bar_end_ns, kind="stable")
    ends = np.asarray(bar_end_ns, dtype=np.int64)[order]
    seen = np.maximum.accumulate(np.asarray(first_seen_ns, dtype=np.int64)[order]) if len(order) else ends
    idx = np.searchsorted(ends, np.asarray(info_ns, dtype=np.int64), side="right") - 1
    out = np.full(len(info_ns), NO_TIME, dtype=np.int64)
    ok = idx >= 0
    out[ok] = seen[idx[ok]]
    return np.maximum(out, np.where(ok, np.asarray(info_ns, dtype=np.int64), NO_TIME))


def live_visible_times(info_ns: np.ndarray, symbols: list[str], deps: list[str], bars: dict[str, tuple],
                       benchmark: str) -> np.ndarray:
    """Kural bağımlılıkları (ASSET / BENCHMARK) için en geç görünürlük. `bars[sym] = (bar_end_ns, first_seen_ns)`."""
    out = np.zeros(len(info_ns), dtype=np.int64)
    sym_arr = np.asarray(symbols)
    for dep in deps:
        if dep == "BENCHMARK":
            be, fs = bars.get(benchmark, (np.array([], np.int64), np.array([], np.int64)))
            out = np.maximum(out, observed_visibility(info_ns, be, fs))
        else:
            for s in np.unique(sym_arr):
                rows = np.flatnonzero(sym_arr == s)
                be, fs = bars.get(str(s), (np.array([], np.int64), np.array([], np.int64)))
                out[rows] = np.maximum(out[rows], observed_visibility(info_ns[rows], be, fs))
    return out


def live_coverage(visible: np.ndarray, info_ns: np.ndarray, sess: np.ndarray, close_ns: np.ndarray) -> dict:
    """Satır zamanında ⇔ görünür <= bilgi + 30 dk ve görünür <= seans kapanışı. Seans canlı uygun ⇔ pay >= 0.8."""
    usable = (visible != NO_TIME) & (visible <= close_ns)
    timely = usable & (visible - info_ns <= p2.LIVE_TIMELY_MAX_MIN * MIN_NS)
    keep, share = set(), {}
    for s in np.unique(sess):
        r = sess == s
        share[int(s)] = float(timely[r].mean())
        if share[int(s)] >= p2.LIVE_SESSION_ROW_SHARE:
            keep.add(int(s))
    return {"usable": usable, "timely": timely, "live_sessions": keep, "share": share}


# ------------------------------------------------------------------ girdiler
def shift_input(inp: ev.EvalInput, t_ns: np.ndarray, entry: np.ndarray, masks: dict | None = None) -> ev.EvalInput:
    return ev.EvalInput(inp.sessions, inp.sess, inp.seg_start, t_ns, entry, inp.events,
                        dict(inp.masks if masks is None else masks))


def entries_at(times_ns: np.ndarray, sess: np.ndarray, sessions: list[tuple[str, str]], bars: dict) -> np.ndarray:
    """Görünür andaki giriş fiyatı (mevcut `labels_for_session` tanımı: ilk bar başlangıcı >= t'nin açılışı)."""
    from datetime import date

    from app.engines.technical.session_timing import ISTANBUL_TZ
    from app.research.momentum_calibration.labels import labels_for_session
    out = np.full(len(times_ns), np.nan)
    for s in np.unique(sess):
        idx = np.flatnonzero(sess == s)
        sym, day = sessions[int(s)]
        ok = [i for i in idx if times_ns[i] != NO_TIME]
        if not ok:
            continue
        ts = [pd.Timestamp(int(times_ns[i]), tz="UTC").tz_convert(ISTANBUL_TZ).to_pydatetime() for i in ok]
        _, labs = labels_for_session(bars[sym], date.fromisoformat(day), ts)
        for i, lab in zip(ok, labs):
            out[i] = np.nan if lab.entry is None else lab.entry
    return out


def evaluate_modes(base: ev.EvalInput, d20: ev.EvalInput, live: dict, nd, rules: list[dict]) -> dict:
    """A = birincil PASS/FAIL (+ Foreks açıklayıcı); B ve C asla PASS/FAIL'i değiştirmez."""
    a = ev.evaluate(base, nd, rules)
    b = ev.evaluate(d20, None, rules)
    for v in b["rules"].values():
        if "verdict" in v:
            v["sensitivity_targets_check"] = v.pop("verdict")  # yalnız bilgi; birincil karar değil
    c = {}
    for r in rules:
        rid = r["rule_id"]
        L = live.get(rid)
        if L is None or r["status"] != "EVALUABLE":
            c[rid] = {"status": p2.NOT_EVALUABLE_LIVE, "reason": "rule not evaluable"}
            continue
        keep = L["coverage"]["live_sessions"]
        if len(keep) < p2.LIVE_MIN_ASSET_SESSIONS:
            c[rid] = {"status": p2.NOT_EVALUABLE_LIVE, "live_asset_sessions": len(keep),
                      "required": p2.LIVE_MIN_ASSET_SESSIONS, "live_symbols": L["live_symbols"]}
            continue
        sub = ev.subset(L["input"], keep)
        m = ev.rule_metrics(sub, sub.masks[rid])
        c[rid] = {"status": "DESCRIPTIVE_ONLY", "live_asset_sessions": len(keep), "live_symbols": L["live_symbols"],
                  **{k: v for k, v in m.items() if not k.startswith("_")},
                  "targets_check_descriptive": ev.pass_fail(m)["checks"],
                  "scope": "probe-observed assets only; not generalizable to all evaluable assets"}
    return {"primary_mode": p2.MODE_A, p2.MODE_A: a, p2.MODE_B: b, p2.MODE_C: c,
            "primary_verdicts": {k: v.get("verdict") for k, v in a["rules"].items()}}


def build_mode_inputs(guard, eval_sessions: list[str], evaluable: list[str], workers: int = 7) -> dict:
    """Gerçek yükleme (YALNIZ kapı + ön kontrol açıkken, jetonla): dondurulmuş hat → üç modun girdileri."""
    from datetime import date

    from app.research.momentum_collector import manifest as mm
    from app.research.momentum_final import candidate as cd
    from app.research.momentum_final import experiment as mf
    from app.research.momentum_label_v2 import experiment as lx
    from app.research.momentum_pilot import analysis as an
    from app.research.momentum_pilot import experiment as pe
    from app.research.momentum_pilot import split as sp
    c = mm.load()["config"]
    a = pe._ReadOnlyArchive()
    try:
        full, warm = pe.session_classes(a)
        sessions = warm + [d for d in full if d <= max(eval_sessions)]
        b5 = sp.load_primary_bars(a.db, guard, sessions, "5m", list(c["universe"]) + [c["benchmark"]])
    finally:
        a.close()
    data = {s: an.to_asset_data(s, g) for s, g in b5.groupby("symbol")}
    bench = data.pop(c["benchmark"])
    rows = an.build_rows(data, bench, [date.fromisoformat(d) for d in eval_sessions], workers)  # 87 varlık: aynı hat
    p = an.PilotPanel(rows, {s: d.bars for s, d in data.items()})
    p.build_labels(15)
    p.build_labels(20)
    events, _ = an.build_events(p)
    raw = lx.masks(p, cd.load_frozen(mf.MANIFEST)["candidate"])
    masks = {rid: raw[k] for rid, k in ev.MASK_KEYS.items()}
    sess_keys = [(s, str(d)) for s, d in p.sessions]
    full_inp = ev.EvalInput(sess_keys, p.sess, p.seg_start, p.labels[15].t_ns, p.labels[15].entry, events, masks)
    keep = {i for i, (s, _) in enumerate(sess_keys) if s in set(evaluable)}  # V2: yalnız uygun varlıklar
    base = ev.subset(full_inp, keep)
    rows_kept = np.flatnonzero(np.isin(p.sess, sorted(keep)))
    d20 = shift_input(base, p.labels[20].t_ns[rows_kept], p.labels[20].entry[rows_kept])
    # Mod C
    info = p.t15_ns[rows_kept] - 15 * MIN_NS
    syms = [base.sessions[int(s)][0] for s in base.sess]
    seen = {s: (g["bar_end_ns"].to_numpy(np.int64), g["first_seen_ns"].to_numpy(np.int64)) for s, g in b5.groupby("symbol")}
    bmask = b5["symbol"] == c["benchmark"]
    close_by_day = b5[bmask].groupby("session_date")["bar_end_ns"].max().to_dict()
    close = np.array([close_by_day.get(base.sessions[int(s)][1], 0) for s in base.sess], dtype=np.int64)
    live = {}
    for rid, deps in p2.RULE_DEPENDENCIES.items():
        vis = live_visible_times(info, syms, deps, seen, c["benchmark"])
        cov = live_coverage(vis, info, base.sess, close)
        entry = entries_at(np.where(cov["usable"], vis, NO_TIME), base.sess, base.sessions, p.bars)
        mask = base.masks[rid] & cov["usable"]
        inp = shift_input(base, np.where(cov["usable"], vis, NO_TIME), entry, {rid: mask})
        live[rid] = {"input": inp, "coverage": cov,
                     "live_symbols": sorted({base.sessions[s][0] for s in cov["live_sessions"]})}
    return {"A": base, "B": d20, "C": live,
            "fingerprint": {"sessions": sorted({d for _, d in base.sessions}),
                            "symbols": sorted({s for s, _ in base.sessions})}}
