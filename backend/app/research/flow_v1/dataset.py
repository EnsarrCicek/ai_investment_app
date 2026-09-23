"""FLOW 1B dondurulmuş veri seti: tek seferlik çekim (freeze), hash doğrulamalı
yükleme ve takvim/bütünlük/süreklilik ön işlemesi.

İki ayrı sorumluluk:
- `freeze_dataset()` — AĞ KULLANIR (BistProvider/Yahoo). Yalnızca bir kez,
  elle çalıştırılır: `python -m app.research.flow_v1.dataset --freeze`.
- `load_verified_dataset()` / `preprocess_symbol()` — ağ YOK. Her sembolün
  ham satırlarının `content_sha256`'sı manifest ile yeniden doğrulanır;
  uyuşmazlıkta hata fırlatılır (sessiz onarım yok).

Ham satırlar Yahoo'nun döndürdüğü hâliyle (normalizasyon ÖNCESİ) dondurulur;
tüm ön işleme deterministik olarak yeniden üretilebilir.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.research.canonical_hash import content_sha256
from app.services.market_data.completed_bars import filter_completed_daily_bars, latest_expected_completed_date
from app.services.market_data.trading_calendar import expected_trading_sessions, normalize_bist_daily_sessions

FLOW_V1_DIR = Path(__file__).resolve().parent
DATA_DIR = FLOW_V1_DIR / "data"
FROZEN_DATA_FILE = DATA_DIR / "frozen_ohlcv.json.gz"
DATASET_MANIFEST_FILE = DATA_DIR / "dataset_manifest.json"
PROTOCOL_FILE = FLOW_V1_DIR.parent / "resources" / "flow_v1_protocol_v1.json"
TECHNICAL_V1_PROTOCOL_FILE = FLOW_V1_DIR.parent / "resources" / "technical_v1_protocol_v1.json"

BENCHMARK_SYMBOL = "XU100"
REQUESTED_START = "2021-01-01"
PROVIDER_ID = "yahoo_finance"
ADJUSTMENT_MODE = "yfinance_history_default_auto_adjust_true"
OHLCV = ["Open", "High", "Low", "Close", "Volume"]


class DatasetIntegrityError(ValueError):
    """Dondurulmuş veri, manifest'teki hash ile eşleşmiyor."""


class FrozenDatasetMissingError(FileNotFoundError):
    """Yerel dondurulmuş ham veri yok. Ham Yahoo snapshot'ları git'te
    TUTULMAZ (FLOW 1C veri hijyeni) — analiz asla sessizce yeniden
    çekmez; önce açıkça freeze komutu çalıştırılmalıdır."""


def load_protocol() -> tuple[dict, str]:
    protocol = json.loads(PROTOCOL_FILE.read_text(encoding="utf-8"))
    return protocol, content_sha256(protocol)


def load_frozen_universe() -> tuple[list[str], str]:
    """Technical V1 protokolündeki dondurulmuş 100 sembol + o protokolün
    kendi kimlik hash'i (FLOW protokolündeki değerle karşılaştırılır)."""
    tech_protocol = json.loads(TECHNICAL_V1_PROTOCOL_FILE.read_text(encoding="utf-8"))
    symbols = list(tech_protocol["universe"]["frozen_symbol_list"])
    return symbols, content_sha256(tech_protocol)


def _rows_from_frame(df: pd.DataFrame) -> list[list]:
    """Kanonik satır listesi: [iso_date, open, high, low, close, volume].
    NaN JSON-güvenli değildir -> None olarak saklanır (ve öyle geri okunur)."""
    rows = []
    for ts, row in df.iterrows():
        values = []
        for col in OHLCV:
            v = row[col]
            values.append(None if pd.isna(v) else float(v))
        rows.append([ts.date().isoformat(), *values])
    return rows


def symbol_payload(symbol: str, rows: list[list]) -> dict:
    return {"symbol": symbol, "columns": ["date", *OHLCV], "rows": rows}


def rows_to_frame(rows: list[list]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["date", *OHLCV])
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("date"))).tz_localize("Europe/Istanbul")
    return frame.astype(float)


def freeze_dataset(provider=None, now: datetime | None = None) -> dict:
    """AĞ KULLANIR. Evreni + XU100'ü BİR KEZ çeker ve dondurur."""
    import yfinance

    from app.services.market_data.bist_provider import BistProvider

    provider = provider or BistProvider()
    now = now or datetime.now(timezone.utc)
    end_date = latest_expected_completed_date(now)
    end_exclusive = (end_date + timedelta(days=1)).isoformat()
    symbols, tech_protocol_sha = load_frozen_universe()

    frozen: dict[str, dict] = {}
    entries: dict[str, dict] = {}
    for symbol in [*symbols, BENCHMARK_SYMBOL]:
        retrieved_at = datetime.now(timezone.utc).isoformat()
        entry = {
            "symbol": symbol,
            "yahoo_ticker": f"{symbol}.IS",
            "requested_start": REQUESTED_START,
            "requested_end_exclusive": end_exclusive,
            "provider_id": PROVIDER_ID,
            "provider_class": type(provider).__name__,
            "adjustment_mode": ADJUSTMENT_MODE,
            "retrieved_at_utc": retrieved_at,
        }
        try:
            df = provider.get_history(symbol, start=REQUESTED_START, end=end_exclusive, interval="1d")
            rows = _rows_from_frame(df)
            payload = symbol_payload(symbol, rows)
            entry.update(
                {
                    "status": "OK",
                    "first_raw_date": rows[0][0] if rows else None,
                    "last_raw_date": rows[-1][0] if rows else None,
                    "raw_bar_count": len(rows),
                    "content_sha256": content_sha256(payload),
                }
            )
            frozen[symbol] = payload
        except Exception as exc:  # kayıt edilir, veri UYDURULMAZ
            entry.update({"status": "FETCH_FAILED", "error": f"{type(exc).__name__}: {exc}"})
        entries[symbol] = entry
        print(f"[freeze] {symbol}: {entry['status']} {entry.get('raw_bar_count', '')}", file=sys.stderr)

    ok_hashes = {s: e["content_sha256"] for s, e in entries.items() if e["status"] == "OK"}
    manifest = {
        "manifest_schema_version": "1.0.0",
        "dataset_id": "FLOW_V1_FROZEN_OHLCV",
        "freeze_now_utc": now.isoformat(),
        "latest_expected_completed_date": end_date.isoformat(),
        "requested_start": REQUESTED_START,
        "requested_end_exclusive": end_exclusive,
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "provider_id": PROVIDER_ID,
        "adjustment_mode": ADJUSTMENT_MODE,
        "yfinance_version": yfinance.__version__,
        "pandas_version": pd.__version__,
        "universe_source_protocol_sha256": tech_protocol_sha,
        "symbols": entries,
        "dataset_sha256": content_sha256(ok_hashes),
        "hash_primitive": "app.research.canonical_hash.content_sha256",
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)
    FROZEN_DATA_FILE.write_bytes(buf.getvalue())
    DATASET_MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def load_verified_dataset(
    data_file: Path = FROZEN_DATA_FILE, manifest_file: Path = DATASET_MANIFEST_FILE
) -> tuple[dict[str, pd.DataFrame], dict]:
    """AĞ YOK. Her sembolü manifest hash'ine karşı doğrular. Yerel ham veri
    yoksa açık bir hata fırlatır — Yahoo'dan yeniden çekmez (yeni bir
    snapshot farklı olabilir ve manifest hash'iyle eşleşmez)."""
    if not manifest_file.exists():
        raise FrozenDatasetMissingError(f"Dataset manifest bulunamadı: {manifest_file}")
    if not data_file.exists():
        raise FrozenDatasetMissingError(
            f"Yerel dondurulmuş ham veri yok: {data_file}. Ham Yahoo verisi git'te tutulmaz. "
            "Orijinal snapshot'ı (manifest'teki dataset_sha256) yerel yedekten geri yükleyin; "
            "ya da açıkça YENİ bir snapshot oluşturun: "
            "`python -m app.research.flow_v1.dataset --freeze --new-snapshot` (yeni manifest/hash "
            "üretir, git diff'te görünür; önceki sonuçlar yalnızca orijinal snapshot ile yeniden üretilebilir)."
        )
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    frozen = json.loads(gzip.decompress(data_file.read_bytes()).decode("utf-8"))
    return verify_frozen(frozen, manifest), manifest


def verify_frozen(frozen: dict, manifest: dict) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    ok_hashes = {}
    for symbol, entry in manifest["symbols"].items():
        if entry["status"] != "OK":
            if symbol in frozen:
                raise DatasetIntegrityError(f"{symbol}: manifest FETCH_FAILED ama veri dosyasında mevcut")
            continue
        if symbol not in frozen:
            raise DatasetIntegrityError(f"{symbol}: veri dosyasında yok")
        payload = frozen[symbol]
        actual = content_sha256(payload)
        if actual != entry["content_sha256"]:
            raise DatasetIntegrityError(f"{symbol}: content_sha256 uyuşmazlığı ({actual} != {entry['content_sha256']})")
        ok_hashes[symbol] = actual
        frames[symbol] = rows_to_frame(payload["rows"])
    extra = set(frozen) - set(manifest["symbols"])
    if extra:
        raise DatasetIntegrityError(f"manifest'te olmayan semboller: {sorted(extra)}")
    if content_sha256(ok_hashes) != manifest["dataset_sha256"]:
        raise DatasetIntegrityError("dataset_sha256 uyuşmazlığı")
    return frames


# --------------------------------------------------------------------------
# Ön işleme
# --------------------------------------------------------------------------


@dataclass
class SymbolQuality:
    symbol: str
    raw_bars: int = 0
    dropped_incomplete_bars: int = 0
    dropped_non_session_bars: int = 0
    invalid_integrity_bars: int = 0
    missing_expected_sessions: int = 0
    zero_volume_sessions: int = 0
    high_equals_low_sessions: int = 0
    segments: int = 0
    segment_lengths: list[int] = field(default_factory=list)
    first_valid_session: str | None = None
    last_valid_session: str | None = None
    status: str = "OK"


def integrity_invalid_mask(df: pd.DataFrame) -> pd.Series:
    """`data_quality.check_raw_ohlcv_integrity` ile AYNI kurallar, satır bazında
    (o fonksiyon ilk ihlalde istisna fırlatır; burada her satır işaretlenir)."""
    numeric = df[OHLCV].astype(float)
    o, h, l, c, v = (numeric[col] for col in OHLCV)
    finite = pd.Series(np.isfinite(numeric.to_numpy()).all(axis=1), index=df.index)
    non_pos = finite & ((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0))
    neg_vol = finite & (v < 0)
    impossible = finite & ((h < l) | (h < o) | (h < c) | (l > o) | (l > c))
    return ~finite | non_pos | neg_vol | impossible


def split_into_segments(df: pd.DataFrame) -> list[pd.DataFrame]:
    """`df` (geçerli satırlar, tarih sıralı) -> beklenen işlem günleri
    açısından kesintisiz segmentler. Beklenen bir seans eksikse yeni segment
    başlar. Boşluk DOLDURULMAZ."""
    if df.empty:
        return []
    days = [ts.date() for ts in df.index]
    expected = expected_trading_sessions(days[0], days[-1])
    if expected is None:
        raise ValueError("trading calendar bu aralığı desteklemiyor")
    position = {d: i for i, d in enumerate(expected)}
    segments: list[pd.DataFrame] = []
    start = 0
    for i in range(1, len(days)):
        if days[i] not in position or days[i - 1] not in position:
            raise ValueError(f"beklenmeyen seans tarihi: {days[i]}")
        if position[days[i]] - position[days[i - 1]] != 1:
            segments.append(df.iloc[start:i])
            start = i
    segments.append(df.iloc[start:])
    return segments


def preprocess_symbol(symbol: str, raw: pd.DataFrame, now: datetime) -> tuple[list[pd.DataFrame], SymbolQuality]:
    q = SymbolQuality(symbol=symbol, raw_bars=len(raw))
    if raw.empty:
        q.status = "EMPTY"
        return [], q
    completed = filter_completed_daily_bars(raw, now=now)
    q.dropped_incomplete_bars = len(raw) - len(completed)
    normalized, result = normalize_bist_daily_sessions(completed, symbol=symbol, provider=PROVIDER_ID)
    q.dropped_non_session_bars = len(result.dropped_sessions)
    invalid = integrity_invalid_mask(normalized)
    q.invalid_integrity_bars = int(invalid.sum())
    valid = normalized[~invalid]
    if valid.empty:
        q.status = "NO_VALID_BARS"
        return [], q
    days = [ts.date() for ts in valid.index]
    expected = expected_trading_sessions(days[0], days[-1]) or []
    q.missing_expected_sessions = len(expected) - len(valid)
    q.zero_volume_sessions = int((valid["Volume"] == 0).sum())
    q.high_equals_low_sessions = int((valid["High"] == valid["Low"]).sum())
    segments = split_into_segments(valid)
    q.segments = len(segments)
    q.segment_lengths = [len(s) for s in segments]
    q.first_valid_session = days[0].isoformat()
    q.last_valid_session = days[-1].isoformat()
    return segments, q


def main() -> None:
    if "--freeze" not in sys.argv:
        print("Kullanım: python -m app.research.flow_v1.dataset --freeze  (AĞ KULLANIR, bir kez çalıştırılır)")
        return
    if FROZEN_DATA_FILE.exists():
        print(f"{FROZEN_DATA_FILE} zaten var — dondurulmuş veri ÜZERİNE YAZILMAZ.")
        return
    if DATASET_MANIFEST_FILE.exists() and "--new-snapshot" not in sys.argv:
        print(
            f"{DATASET_MANIFEST_FILE} (commit'li hash'ler) mevcut ama ham veri yok. Yeniden çekim FARKLI bir "
            "snapshot üretir ve manifest'i değiştirir. Bilinçli olarak yeni snapshot istiyorsanız "
            "--new-snapshot ekleyin."
        )
        return
    manifest = freeze_dataset()
    print(json.dumps({"dataset_sha256": manifest["dataset_sha256"], "end": manifest["latest_expected_completed_date"]}))


if __name__ == "__main__":
    main()
