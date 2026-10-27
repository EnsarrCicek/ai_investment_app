"""Momentum PILOT / FUTURE_HOLDOUT bölmesi ve holdout erişim koruması (YALNIZ araştırma; toplayıcıya dokunmaz).

Politika (sonuçlar okunmadan ÖNCE sabitlendi):
* PILOT_DEVELOPMENT = prospektif başlangıçtan (2026-10-22) itibaren GÖZLENEN ilk 5 FULL seans (tarih sırası).
* FUTURE_HOLDOUT = pilot kesim seansından SONRAKİ her FULL seans.
* FULL seans = toplayıcının kendi sınıflaması (`integrity.classify_sessions`: XU100 5m ilk bar ≤ 10:05, son bar
  ≥ 17:50). Hafta günü/tatil takvimi VARSAYILMAZ; eksik (ör. bugünkü, süren) seans FULL değildir.
* Bölme yalnız gösterge barlarının ZAMAN meta verisini okur (oturum tarihi, ilk/son bar saati, sayı); fiyat/hacim/
  etiket/olay/alarm OKUNMAZ.

Manifest birikimli ama geri alınamaz: pilot listesi yalnız SONUNA ekleme ile büyür (önceki seanslar değişirse
hata); 5'e ulaşınca durum PILOT_COMPLETE, `pilot_cutoff_session` sabitlenir ve manifest bir daha değişmez. Her
sürüm kanonik JSON + SHA-256; önceki sürümler `manifest_history/` altında saklanır (silinmez).

Koruma: model geliştirme / pilot yükleyicileri, oturum tarihi erişim kesiminden (tamamlanmışsa pilot kesimi,
değilse son onaylı pilot seansı) SONRA olan bir seans İSTERSE veya bir satır GÖRÜRSE `HoldoutAccessError` fırlatır.
Gelecek satırlar sessizce süzülmez.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from app.research.momentum_collector import manifest as mm
from app.research.momentum_final import candidate as cd
from app.research.momentum_label_v2 import experiment as lx

HERE = Path(__file__).parent
MANIFEST_PATH = HERE / "pilot_manifest.json"
HISTORY_DIR = HERE / "manifest_history"
RUNS = HERE / "runs"

VERSION = "MOMENTUM_PILOT_SPLIT_V1"
LABEL_V2_SHA256 = "9b9602c18cf13e2bd7c5af8d171b479945be0cefa1ee28fc0cb0df8cba6e1d09"
PILOT_SESSION_COUNT = 5
PILOT_POLICY = "first_5_full_observed_sessions"
HOLDOUT_POLICY = "all_full_sessions_after_pilot_cutoff"
ACCUMULATING = "PILOT_ACCUMULATING"
COMPLETE = "PILOT_COMPLETE"
PRIMARY_SOURCE = "WINDOWS_PRIMARY"
MOBILE_SOURCE = "MOBILE_SHADOW"
PILOT_LABEL = "PILOT / DEVELOPMENT ONLY"
HOLDOUT_ERROR = "Future holdout is forbidden during pilot development"
FULL_SESSION_DEFINITION = ("collector integrity.classify_sessions: benchmark XU100 5m first bar <= 10:05 and last "
                           "bar >= 17:50 (Europe/Istanbul); session_date >= prospective_start_session; not a "
                           "consumed-final date; no weekday/holiday inference")


class PilotSplitError(RuntimeError):
    pass


class HoldoutAccessError(RuntimeError):
    pass


# ------------------------------------------------------------------ bölme (saf)
def observed_full_sessions(sessions: pd.DataFrame, start: str) -> list[str]:
    """`classify_sessions` çıktısından başlangıç ve sonrasındaki FULL seanslar (tarih sırası)."""
    if sessions.empty:
        return []
    full = sessions.loc[(sessions["session_class"] == "FULL") & (sessions["session_date"] >= start), "session_date"]
    return sorted(d for d in full if not mm.in_consumed_final(date.fromisoformat(d)))


def resolve_split(full_sessions: list[str], n: int = PILOT_SESSION_COUNT) -> dict:
    full = sorted(full_sessions)
    pilot = full[:n]
    complete = len(pilot) == n
    return {"pilot_sessions": pilot, "status": COMPLETE if complete else ACCUMULATING,
            "pilot_cutoff_session": pilot[-1] if complete else None,
            "holdout_sessions_observed": len(full) - len(pilot)}


def policy() -> dict:
    """Değişmez politika (SHA'sı her manifest sürümünde aynı)."""
    return {"version": VERSION, "pilot_policy": PILOT_POLICY, "pilot_session_count": PILOT_SESSION_COUNT,
            "holdout_policy": HOLDOUT_POLICY, "full_session_definition": FULL_SESSION_DEFINITION,
            "primary_data_source": PRIMARY_SOURCE, "mobile_data_role": f"{MOBILE_SOURCE} (quality comparison only; "
                                                                      "never replaces primary bars)",
            "label": lx.lv.LABEL_VERSION, "label_v2_sha256": LABEL_V2_SHA256,
            "alert_unit": lx.lv.FIRST_ALERT, "pilot_metric_label": PILOT_LABEL,
            "holdout_target_full_sessions": mm.MIN_FULL_SESSIONS,
            "holdout_access": "forbidden until ONE candidate is frozen after pilot completion; then used once"}


def build_manifest(full_sessions: list[str], study: dict, created_at: datetime,
                   previous_sha256: str | None = None) -> dict:
    c = study["config"]
    split = resolve_split(full_sessions)
    body = {**policy(), "policy_sha256": cd.sha256_of(policy()),
            "study_manifest_sha256": study["sha256"], "universe_sha256": c["universe_sha256"],
            "prospective_start_session": c["prospective_start_session"],
            "status": split["status"], "pilot_sessions": split["pilot_sessions"],
            "pilot_cutoff_session": split["pilot_cutoff_session"],
            "development_access_cutoff": split["pilot_sessions"][-1] if split["pilot_sessions"] else None,
            "previous_manifest_sha256": previous_sha256,
            "created_at": created_at.astimezone(timezone.utc).isoformat()}
    return {"manifest": body, "sha256": cd.sha256_of(body)}


def verify_manifest(m: dict) -> dict:
    b = m["manifest"]
    if cd.sha256_of(b) != m.get("sha256"):
        raise PilotSplitError("pilot manifesti bozulmuş (SHA uyuşmuyor)")
    if b["label_v2_sha256"] != LABEL_V2_SHA256 or b["policy_sha256"] != cd.sha256_of(policy()):
        raise PilotSplitError("pilot politikası / Label V2 SHA değişmiş")
    return m


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    if not path.exists():
        raise PilotSplitError("pilot manifesti yok (önce `split` aşaması)")
    return verify_manifest(json.loads(path.read_text(encoding="utf-8")))


def _write(path: Path, m: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, sort_keys=True, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def refresh_manifest(full_sessions: list[str], study: dict, now: datetime, path: Path = MANIFEST_PATH,
                     history: Path = HISTORY_DIR) -> tuple[dict, bool]:
    """(manifest, değişti mi). Pilot listesi yalnız sona eklemeyle büyür; tamamlanmış manifest değişmez."""
    if study["config"]["label_manifest_sha256"] != LABEL_V2_SHA256:
        raise PilotSplitError("çalışma manifesti farklı bir Label V2 SHA'sına bağlı")
    new_split = resolve_split(full_sessions)
    if not path.exists():
        m = build_manifest(full_sessions, study, now)
        _write(path, m)
        _write(history / f"pilot_manifest.{m['sha256']}.json", m)
        return m, True
    old = load_manifest(path)
    ob = old["manifest"]
    if ob["study_manifest_sha256"] != study["sha256"] or ob["universe_sha256"] != study["config"]["universe_sha256"]:
        raise PilotSplitError("çalışma manifesti / evren pilot manifestinden sonra değişmiş")
    if new_split["pilot_sessions"][:len(ob["pilot_sessions"])] != ob["pilot_sessions"]:
        raise PilotSplitError(f"gözlenen FULL seanslar kayıtlı pilot önekiyle çelişiyor: {ob['pilot_sessions']} → "
                              f"{new_split['pilot_sessions']}")
    if ob["status"] == COMPLETE or new_split["pilot_sessions"] == ob["pilot_sessions"]:
        return old, False
    m = build_manifest(full_sessions, study, now, previous_sha256=old["sha256"])
    _write(history / f"pilot_manifest.{m['sha256']}.json", m)
    _write(path, m)
    return m, True


# ------------------------------------------------------------------ holdout koruması
class HoldoutGuard:
    """Pilot / model geliştirme erişim koruması. Seans tarihleri 'YYYY-MM-DD' (İstanbul yerel seans günü)."""

    def __init__(self, manifest: dict):
        b = verify_manifest(manifest)["manifest"]
        self.cutoff: str | None = b["pilot_cutoff_session"] or b["development_access_cutoff"]
        self.pilot_sessions: list[str] = list(b["pilot_sessions"])
        self.complete = b["status"] == COMPLETE
        if self.cutoff is None:
            raise HoldoutAccessError("henüz onaylı pilot seansı yok; geliştirme verisi yok")

    def check_session(self, session_date: str) -> None:
        if str(session_date) > self.cutoff:
            raise HoldoutAccessError(f"{HOLDOUT_ERROR}: session {session_date} > cutoff {self.cutoff}")

    def check_sessions(self, sessions) -> None:
        for s in sessions:
            self.check_session(str(s))

    def check_frame(self, df: pd.DataFrame, col: str = "session_date") -> pd.DataFrame:
        """Okunan satırlarda kesim sonrası tarih varsa HATA (süzme yok)."""
        if len(df):
            self.check_session(str(df[col].max()))
        return df


def _in(n: int) -> str:
    return ",".join("?" * n)


def load_primary_bars(db, guard: HoldoutGuard, sessions: list[str], interval: str,
                      symbols: list[str] | None = None) -> pd.DataFrame:
    """WINDOWS PRIMARY FIRST_SEEN barları — yalnız açıkça istenen seanslar. İstenen seans kesimden sonraysa SORGU
    ÇALIŞMADAN hata; dönen satırlarda kesim sonrası tarih varsa yine hata."""
    guard.check_sessions(sessions)
    q = (f"SELECT symbol, interval, bar_start_ns, bar_end_ns, session_date, open, high, low, close, volume, "
         f"bar_hash, first_seen_ns, collection_mode, identity_check FROM bars WHERE interval=? AND "
         f"session_date IN ({_in(len(sessions))})")
    args: list = [interval, *sessions]
    if symbols is not None:
        q += f" AND symbol IN ({_in(len(symbols))})"
        args += list(symbols)
    df = pd.read_sql_query(q + " ORDER BY symbol, bar_start_ns", db, params=args)
    df["source"] = PRIMARY_SOURCE
    return guard.check_frame(df)


def load_primary_revisions(db, guard: HoldoutGuard, sessions: list[str], interval: str) -> pd.DataFrame:
    guard.check_sessions(sessions)
    df = pd.read_sql_query(
        f"SELECT r.symbol, r.interval, r.bar_start_ns, r.original_hash, r.new_hash, r.changed_fields, b.session_date "
        f"FROM bar_revision r JOIN bars b ON b.symbol=r.symbol AND b.interval=r.interval AND "
        f"b.bar_start_ns=r.bar_start_ns WHERE r.interval=? AND b.session_date IN ({_in(len(sessions))})",
        db, params=[interval, *sessions])
    return guard.check_frame(df)


def load_mobile_bars(db, guard: HoldoutGuard, sessions: list[str], interval: str) -> pd.DataFrame:
    """MOBILE_SHADOW dışa aktarımı (momentum_shadow.db). Yalnız kalite karşılaştırması; birincil barların yerine
    GEÇMEZ (ayrı `source` etiketi, birleştirme yok)."""
    guard.check_sessions(sessions)
    role = db.execute("SELECT DISTINCT collection_role FROM bars").fetchall()
    if role and {r[0] for r in role} != {MOBILE_SOURCE}:
        raise PilotSplitError("mobil dosya MOBILE_SHADOW rolünde değil")
    df = pd.read_sql_query(
        f"SELECT symbol, interval, bar_start_ns, session_date, open, high, low, close, volume, bar_hash, "
        f"first_seen_ns, identity_status AS identity_check, primary_validation_eligible FROM bars WHERE interval=? "
        f"AND session_date IN ({_in(len(sessions))}) ORDER BY symbol, bar_start_ns", db, params=[interval, *sessions])
    if len(df) and df["primary_validation_eligible"].any():
        raise PilotSplitError("mobil bar birincil doğrulamaya uygun işaretlenmiş")
    df["source"] = MOBILE_SOURCE
    return guard.check_frame(df)


def load_mobile_revisions(db, guard: HoldoutGuard, sessions: list[str], interval: str) -> pd.DataFrame:
    guard.check_sessions(sessions)
    df = pd.read_sql_query(
        f"SELECT r.symbol, r.interval, r.bar_start_ns, r.original_hash, r.new_hash, r.changed_fields, b.session_date "
        f"FROM bar_revisions r JOIN bars b ON b.symbol=r.symbol AND b.interval=r.interval AND "
        f"b.bar_start_ns=r.bar_start_ns WHERE r.interval=? AND b.session_date IN ({_in(len(sessions))})",
        db, params=[interval, *sessions])
    return guard.check_frame(df)
