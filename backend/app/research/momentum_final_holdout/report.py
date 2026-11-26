"""Final holdout — kuru çalıştırma / duman testi metinleri (performans metriği İÇERMEZ)."""

from __future__ import annotations

import json
from collections import Counter

from app.research.momentum_final_holdout import protocol as pr


def dry_run_text(state: dict, gate: dict) -> str:
    out = {"status": gate["status"], "missing_conditions": gate["missing"],
           "future_holdout_full_sessions": gate["future_holdout_full_sessions"],
           "required_full_sessions": gate["required_full_sessions"],
           "estimated_missing_full_sessions": gate["missing_full_sessions_count"],
           "holdout_full_session_dates": state["holdout_sessions"],
           "holdout_short_sessions": state["short_sessions"],
           "archive_integrity": state["archive_integrity"],
           "raw_files": {"requests": state["raw_requests"], "missing": state["raw_missing"],
                         "invalid": state["raw_invalid"], "fingerprint": state["raw_fingerprint"]},
           "label_v2_sha256": state["label_v2_sha256"], "amendment_chain_valid": state["amendment_chain_valid"],
           "protocol_manifest_sha256": gate["manifest_sha256"],
           "holdout_outcomes": "UNREAD (no bars/labels/events/alerts loaded)"}
    return json.dumps(out, indent=1, ensure_ascii=False)


def smoke_text(inp, nd) -> str:
    """Yalnız yapısal sayımlar (pilot seansları); PASS/FAIL ve performans yok."""
    classes = Counter(ev.event_class for evs in inp.events for ev in evs)
    return json.dumps({"label": "SMOKE / PILOT SESSIONS ONLY — no performance metrics",
                       "asset_sessions": len(inp.sessions), "rows": int(len(inp.sess)),
                       "session_dates": sorted({d for _, d in inp.sessions}),
                       "event_classes": dict(classes), "mask_keys": sorted(inp.masks),
                       "mask_lengths_match": all(len(v) == len(inp.sess) for v in inp.masks.values()),
                       "visible_time_finite": bool((inp.t_ns > 0).all()),
                       "foreks_first_fetch_ns": nd.first_fetch_ns,
                       "news_windows": list(pr.NEWS_WINDOWS_MIN)}, indent=1, default=str)
