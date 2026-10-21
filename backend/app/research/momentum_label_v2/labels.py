"""MOMENTUM_EVENT_LABEL_V2 — olay / başlangıç / tepe / lead / yakalama AYNI kanonik swing üzerinde (YALNIZ araştırma).

V1 sorunu: olay = seans içi en büyük yükseliş (o ana kadarki en düşükten sonraki en yüksek) ≥ %5, ama tepe = SEANS
en yükseği ve taban = seans tepesinden önceki en düşük. İkisi farklı swing olabilir (ör. açılışta tepe, sonra düşüş
ve ayrı bir %5 yükseliş): olay bir swing'den, lead/yakalama başka bir swing'den ölçülür. Ayrıca ilk alarm, olay
penceresine bakılmadan olaya bağlanır (sabah alarmı → öğleden sonraki olay "yakalandı").

V2 (gelecek bilgi yalnız ETİKET için; dedektör girdisine asla girmez):
* Swing (i, j): j = aralıkta High[j] / min(Low[a..j]) oranının İLK argmaks'ı; i = o minimumun İLK görüldüğü bar.
* Swing politikası RECURSIVE_LARGEST_FIRST: seansın en büyük swing'i (birincil, V1 max_runup ile aynı) bulunur;
  dip barından ÖNCEKİ ve tepe barından SONRAKİ barlarda aynı işlem tekrarlanır. Oranı ≥ eşik olan tüm ayrık
  swing'ler olaydır. Pencereler [başlangıç, tepe] zamanca ayrıktır.
* event_start = dip barının başlangıcı; event_peak = tepe barının başlangıcı (tepenin olabileceği en erken an).
* Zamanlar piyasa bar zamanlarıdır; sağlayıcı gecikmesinden bağımsızdır. Gecikme yalnız alarmın görünür zamanını
  değiştirir.
* Değerlendirilebilir olay: tepe > ilk gözlem (seansın ilk barının bitişi) VE tepe barı > dip barı.
* Birincil alarm birimi: varlık-seans başına İLK WATCH alarmı (ürün anlamı: o gün bir kez bildirim). Sonraki
  yeniden girişler yeni TP üretmez, ilk yanlış alarmı temizlemez, duyarlılığı artırmaz. Her WATCH aktivasyonu
  (yükselen kenar) yalnız ikincil duyarlılık teşhisidir. TP yalnız event_start ≤ görünür zaman ≤ event_peak;
  kronolojik bire bir eşleme.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

LABEL_VERSION = "MOMENTUM_EVENT_LABEL_V2"
EVENT_THRESHOLD = 0.05
LEAD_TARGET = 0.5
MIN_NS = 60_000_000_000
BAR_NS = 5 * MIN_NS

# olay sınıfları
INTRADAY_EVALUABLE = "INTRADAY_EVALUABLE"
PRE_OBSERVATION = "PRE_OBSERVATION_EVENT"  # tepe, seansın ilk barı tamamlanmadan (açılış barı) — gözlem şansı yok
INTRABAR = "INTRABAR_EVENT"  # dip ve tepe aynı 5 dk barda — bar içi sıra bilinmez, nedensel gözlem yok
EVENT_CLASSES = (INTRADAY_EVALUABLE, PRE_OBSERVATION, INTRABAR)
OPENING_GAP = "OPENING_GAP_EVENT"  # önceki kapanış → açılış ≥ eşik; ayrı seans sınıfı, gün içi payda DIŞI

# alarm sınıfları
IN_EVENT = "IN_EVENT_ALERT"
IN_EVENT_DUPLICATE = "IN_EVENT_DUPLICATE"  # eşleşmiş olayın penceresinde sonraki başlangıç (duyarlılıkta sayılmaz)
PRE_EVENT = "PRE_EVENT_ALERT"
POST_PEAK = "POST_PEAK_ALERT"
NO_EVENT = "NO_EVENT_SESSION_ALERT"
ALERT_CLASSES = (IN_EVENT, IN_EVENT_DUPLICATE, PRE_EVENT, POST_PEAK, NO_EVENT)

FIRST_ALERT = "first_watch_alert_per_asset_session"  # birincil (ileriye dönük metrikler)
ALERT_ONSET = "each_watch_activation"  # ikincil duyarlılık teşhisi
DRAFT_SHA256 = "3adfa556ac579cbd8f3712b1ca4d93b310bac74ced21b9501158afe5022793b4"  # alert_unit = aktivasyon taslağı

MANIFEST_CONFIG = {
    "version": LABEL_VERSION,
    "manifest_status": "FINAL",
    "supersedes_draft_sha256": DRAFT_SHA256,
    "change_policy": "immutable; any change to the label definition requires a new LABEL VERSION and a new manifest",
    "bar_interval": "5m",
    "timestamps": "market bar start times (Europe/Istanbul); provider-delay independent",
    "event_threshold": EVENT_THRESHOLD,
    "swing_definition": "runup(j) = High[j] / min(Low[a..j]) - 1 within a bar range [a..b]; swing peak bar j = first "
                        "argmax of runup; swing low bar i = first bar in [a..j] attaining that minimum Low",
    "swing_policy": "RECURSIVE_LARGEST_FIRST: largest swing of the session is primary (equals V1 max_runup); repeat on "
                    "bars before its low bar and after its peak bar; every disjoint swing with runup >= "
                    "event_threshold is an event",
    "event_start": "start time of swing low bar",
    "event_peak": "start time of swing high bar (earliest instant the high can have printed)",
    "first_observation": "end of first session bar (first bar start + 5 min)",
    "evaluable_event_policy": "event_peak > first_observation AND peak_bar > low_bar",
    "event_classes": list(EVENT_CLASSES),
    "opening_gap_policy": "session open / previous session close - 1 >= event_threshold -> OPENING_GAP_EVENT session "
                          "flag; separate class, never an intraday event, never in intraday denominators",
    "alert_time": "visible time = information time + provider delay",
    "alert_unit": FIRST_ALERT,
    "alert_unit_definition": "only the first row of an asset-session where the final rule mask is on; later "
                             "re-entries (NONE -> WATCH again) produce no new true positive, do not clear an earlier "
                             "false alert and do not add recall",
    "sensitivity_alert_unit": ALERT_ONSET,
    "sensitivity_alert_unit_definition": "rising edge of the final rule mask within an asset-session (first row, or "
                                         "row whose previous row in the same session was not alerting); diagnostic "
                                         "only, never a primary metric",
    "alert_classes": list(ALERT_CLASSES),
    "true_positive": "event_start <= alert_visible_time <= event_peak",
    "pre_event_alert_policy": "alert outside every event window and before the start of a later event in the same "
                              "session -> PRE_EVENT_ALERT; never a true positive",
    "post_peak_policy": "alert outside every event window with no later event in the session -> POST_PEAK_ALERT; "
                        "never a true positive",
    "matching": "chronological one-to-one: the primary first alert can match only the event window that contains "
                "it (earliest unmatched); one alert never catches two events; other events of the session stay "
                "missed in the primary metric. Sensitivity: each activation in time order matches the earliest "
                "unmatched event whose window contains it; further activations in a matched window are "
                "IN_EVENT_DUPLICATE",
    "lead_definition": "(entry - event_low) / (event_high - event_low) on the matched swing; entry = open of first bar "
                       "starting at/after visible time; clipped to [0, 1] for safety only",
    "lead_target": LEAD_TARGET,
    "precision_definition": "primary: asset-sessions whose first alert is IN_EVENT / alerted asset-sessions "
                            "(sensitivity: IN_EVENT activations incl. duplicates / all activations)",
    "fpr_definition": "non-event sessions (no qualifying swing) with an alert / non-event sessions",
    "recall_raw_definition": "matched events / all events",
    "recall_evaluable_definition": "matched evaluable events / evaluable events",
    "provider_delay_independent": True,
    "label_horizon": "same session only",
}


@dataclass(frozen=True)
class Swing:
    low_bar: int
    peak_bar: int
    low: float
    high: float
    start_ns: int
    peak_ns: int
    runup: float
    primary: bool
    event_class: str

    @property
    def evaluable(self) -> bool:
        return self.event_class == INTRADAY_EVALUABLE

    def as_dict(self) -> dict:
        return {**asdict(self), "evaluable": self.evaluable}


def _largest(highs: np.ndarray, lows: np.ndarray, a: int, b: int) -> tuple[int, int, float] | None:
    if b < a:
        return None
    pl = np.minimum.accumulate(lows[a:b + 1])
    ratio = highs[a:b + 1] / pl
    j = int(np.argmax(ratio))
    i = int(np.argmax(lows[a:a + j + 1] == pl[j]))
    return a + i, a + j, float(ratio[j] - 1)


def find_swings(highs: np.ndarray, lows: np.ndarray, threshold: float = EVENT_THRESHOLD) -> list[tuple[int, int, float]]:
    """(dip barı, tepe barı, yükseliş) — kronolojik; ilk eleman değil, `primary` en büyük orana sahip olandır."""
    highs, lows = np.asarray(highs, dtype=float), np.asarray(lows, dtype=float)
    out, stack = [], [(0, len(highs) - 1)]
    while stack:
        a, b = stack.pop()
        got = _largest(highs, lows, a, b)
        if got is None or got[2] < threshold:
            continue
        i, j, r = got
        out.append(got)
        stack.extend([(a, i - 1), (j + 1, b)])
    return sorted(out)


def classify_event(low_bar: int, peak_bar: int, peak_ns: int, first_obs_ns: int) -> str:
    if peak_ns <= first_obs_ns:
        return PRE_OBSERVATION
    if peak_bar == low_bar:
        return INTRABAR
    return INTRADAY_EVALUABLE


def session_events(starts_ns: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                   threshold: float = EVENT_THRESHOLD) -> list[Swing]:
    """Tek seansın olayları (yalnız seans barları; zaman sıralı bar BAŞLANGIÇLARI, ns)."""
    starts_ns = np.asarray(starts_ns, dtype=np.int64)
    if not len(starts_ns):
        return []
    first_obs = int(starts_ns[0]) + BAR_NS
    swings = find_swings(highs, lows, threshold)
    if not swings:
        return []
    best = max(range(len(swings)), key=lambda k: (swings[k][2], -swings[k][1]))  # eşitlikte erken tepe
    out = []
    for k, (i, j, r) in enumerate(swings):
        out.append(Swing(i, j, float(lows[i]), float(highs[j]), int(starts_ns[i]), int(starts_ns[j]), r, k == best,
                         classify_event(i, j, int(starts_ns[j]), first_obs)))
    return out


def opening_gap(open_price: float, prev_close: float | None, threshold: float = EVENT_THRESHOLD) -> bool:
    return prev_close is not None and np.isfinite(prev_close) and prev_close > 0 and open_price / prev_close - 1 >= threshold


# ------------------------------------------------------------------ alarm ↔ olay
def onsets(mask: np.ndarray, seg_start: np.ndarray) -> np.ndarray:
    """Seans içi yükselen kenarlar (satırlar seans, zaman sıralı; `seg_start[i]` = seansın ilk satırı)."""
    mask = np.asarray(mask, dtype=bool)
    prev = np.concatenate([[False], mask[:-1]])
    first_row = np.arange(len(mask)) == seg_start
    return mask & (first_row | ~prev)


def first_only(mask: np.ndarray, sess: np.ndarray) -> np.ndarray:
    out = np.zeros(len(mask), dtype=bool)
    idx = np.flatnonzero(mask)
    if len(idx):
        _, pos = np.unique(sess[idx], return_index=True)
        out[idx[pos]] = True
    return out


def match_alerts(alert_ns: list[int], events: list[Swing]) -> tuple[list[str], list[int | None]]:
    """(alarm sınıfları, olay başına eşleşen alarm indeksi). Alarmlar zaman sıralı."""
    order = sorted(range(len(events)), key=lambda k: events[k].start_ns)
    matched: list[int | None] = [None] * len(events)
    classes = []
    for a, t in enumerate(alert_ns):
        inside = [k for k in order if events[k].start_ns <= t <= events[k].peak_ns]
        free = [k for k in inside if matched[k] is None]
        if free:
            matched[free[0]] = a
            classes.append(IN_EVENT)
        elif inside:
            classes.append(IN_EVENT_DUPLICATE)
        elif not events:
            classes.append(NO_EVENT)
        elif any(events[k].start_ns > t for k in order):
            classes.append(PRE_EVENT)
        else:
            classes.append(POST_PEAK)
    return classes, matched


def lead_v2(entry: float, event: Swing) -> float | None:
    span = event.high - event.low
    if entry is None or not np.isfinite(entry) or not span > 0:
        return None
    return float(min(1.0, max(0.0, (entry - event.low) / span)))


def evaluate(alert_mask: np.ndarray, sess: np.ndarray, seg_start: np.ndarray, t_ns: np.ndarray, entry: np.ndarray,
             events: list[list[Swing]], unit: str = FIRST_ALERT, mfe_close: np.ndarray | None = None,
             x: float = 0.03) -> dict:
    """Satır dizileri (seans, zaman sıralı) + seans başına olay listeleri → V2 metrikleri ve olay/alarm kayıtları.

    `t_ns` = alarmın GÖRÜNÜR zamanı (gecikme senaryosuna göre); `events` gecikmeden bağımsızdır."""
    if unit not in (FIRST_ALERT, ALERT_ONSET):
        raise ValueError(f"bilinmeyen alarm birimi: {unit}")
    alerts = onsets(alert_mask, seg_start) if unit == ALERT_ONSET else first_only(alert_mask, sess)
    a_idx = np.flatnonzero(alerts)
    by_sess: dict[int, list[int]] = {}
    for i in a_idx:
        by_sess.setdefault(int(sess[i]), []).append(int(i))
    n_sess = len(events)
    cls_count = dict.fromkeys(ALERT_CLASSES, 0)
    ev_records, alert_records = [], []
    for s in range(n_sess):
        rows = by_sess.get(s, [])
        classes, matched = match_alerts([int(t_ns[i]) for i in rows], events[s])
        for i, c in zip(rows, classes):
            cls_count[c] += 1
            alert_records.append({"sess": s, "row": i, "class": c})
        for k, ev in enumerate(events[s]):
            m = matched[k]
            row = rows[m] if m is not None else None
            ev_records.append({"sess": s, "k": k, "evaluable": ev.evaluable, "event_class": ev.event_class,
                               "primary": ev.primary, "caught": row is not None, "row": row,
                               "lead": lead_v2(float(entry[row]), ev) if row is not None else None})
    n_alerts = len(a_idx)
    n_in = cls_count[IN_EVENT] + cls_count[IN_EVENT_DUPLICATE]
    evaluable = [e for e in ev_records if e["evaluable"]]
    non_event = [s for s in range(n_sess) if not events[s]]
    fp_sess = sum(1 for s in non_event if by_sess.get(s))
    leads = [e["lead"] for e in ev_records if e["caught"] and e["lead"] is not None]
    first_rows = [rows[0] for rows in by_sess.values()]
    mins = [(int(t_ns[i]) // MIN_NS + 180) % 1440 for i in first_rows]  # UTC → İstanbul (+3)
    hits = (np.nan_to_num(mfe_close[a_idx], nan=-1) >= x) if mfe_close is not None and n_alerts else None

    def rate(k, n):
        return k / n if n else None
    caught_raw = sum(e["caught"] for e in ev_records)
    caught_ev = sum(e["caught"] for e in evaluable)
    return {
        "alert_unit": unit,
        "sessions": n_sess, "event_sessions": n_sess - len(non_event), "non_event_sessions": len(non_event),
        "event_count_raw": len(ev_records), "event_count_evaluable": len(evaluable),
        "alerts": n_alerts, "alert_sessions": len(by_sess), "alert_classes": cls_count,
        "precision_v2": rate(n_in, n_alerts),
        "recall_raw_v2": rate(caught_raw, len(ev_records)),
        "recall_evaluable_v2": rate(caught_ev, len(evaluable)),
        "caught_raw": caught_raw, "caught_evaluable": caught_ev,
        "early_recall_evaluable_v2": rate(sum(e["caught"] and e["lead"] is not None and e["lead"] <= LEAD_TARGET
                                              for e in evaluable), len(evaluable)),
        "FPR_v2": rate(fp_sess, len(non_event)), "specificity_v2": (1 - fp_sess / len(non_event)) if non_event else None,
        "false_positive_sessions": fp_sess,
        "median_lead_v2": float(np.median(leads)) if leads else None,
        "median_first_alert_minute": float(np.median(mins)) if mins else None,
        "pre_event_alert_rate": rate(cls_count[PRE_EVENT], n_alerts),
        "post_peak_alert_rate": rate(cls_count[POST_PEAK], n_alerts),
        "no_event_alert_rate": rate(cls_count[NO_EVENT], n_alerts),
        "mfe_precision_continuity": float(hits.mean()) if hits is not None else None,
        "_events": ev_records, "_alerts": alert_records,
    }
