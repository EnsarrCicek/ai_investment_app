"""EventIntelligence bütçe defteri — mutabakat düzeltmesi (yalnızca operatör CLI).

Endpoint yoktur. Varsayılan dry-run'dır (yazma yok); yazma yalnızca `--apply`
ile yapılır. Araç yalnızca POZİTİF bir tutarı `committed_usd`'ye ekler:
bütçe limiti, `reserved_usd`, açık/belirsiz rezervasyonlar ve mevcut kullanım
kayıtları değişmez. Düzeltme toplamı limiti aşarsa sonraki ücretli çağrılar
mevcut rezervasyon kapısıyla engellenir.

Düzeltme tutarı OTOMATİK TÜRETİLMEZ. Operatör farkı şöyle belirler:
  1. Sağlayıcı kullanım raporundan, belirtilen dönem ve kapsam (proje/anahtar/
     model) için tutarı alır.
  2. Aynı dönem ve kapsam için defterde zaten sayılanı çıkarır: `token_usage_logs`
     (tohum veya uzlaştırılmış kullanım) ve o döneme ait hâlâ tutulan
     RESERVED/UNCERTAIN rezervasyonlar.
  3. Kalan pozitif farkı girer; fark yoksa ya da negatifse düzeltme yapılmaz.
  Rapor dönemleri, kapsamı, gecikmeli kesinleşme ve yerel fiyat tahmini farklı
  olabileceğinden bu kesin fatura eşitliği DEĞİLDİR; ihtiyatlı bir yaklaşımdır.

Tutar ölçekli ondalık olarak işlenir (mikro-USD; 6 ondalıktan fazla hassasiyet
reddedilir, yuvarlama yapılmaz). Gerekçe ve rapor referansı yalnızca kayda
yazılır; çıktıya uzunluk ve içerik özeti (sha256) dışında basılmaz.

Kullanım:
  python -m app.engines.event_intelligence.budget_adjustment \\
      --project ai-investment-app-2026 --adjustment-id opening-2026-10 \\
      --amount-usd 0.1234 --reason "..." --provider-report-ref "..." \\
      --period-start 2026-08-01T00:00:00Z --period-end 2026-10-01T00:00:00Z \\
      --scope "openai project X, key Y, model gpt-5.6-luna"   [--apply]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

_MICRO = Decimal("0.000001")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_TEXT = 1000


class AdjustmentInputError(ValueError):
    pass


def parse_amount_micro_usd(raw: str) -> int:
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise AdjustmentInputError("tutar bir ondalık sayı olmalı") from exc
    if not value.is_finite() or value <= 0:
        raise AdjustmentInputError("tutar pozitif ve sonlu olmalı")
    if value != value.quantize(_MICRO):
        raise AdjustmentInputError("tutar en fazla 6 ondalık basamak içerebilir")
    return int(value / _MICRO)


def _parse_instant(raw: str, field: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdjustmentInputError(f"{field} ISO-8601 olmalı") from exc
    if value.tzinfo is None:
        raise AdjustmentInputError(f"{field} saat dilimi içermeli")
    return value


def _text(raw: str, field: str) -> str:
    value = (raw or "").strip()
    if not value or len(value) > _MAX_TEXT:
        raise AdjustmentInputError(f"{field} boş olamaz ve {_MAX_TEXT} karakteri aşamaz")
    return value


def build_adjustment_record(
    *, project_id, adjustment_id, amount_usd, reason, provider_report_ref, period_start, period_end, scope
) -> tuple[dict, str, int]:
    if not _ID_PATTERN.match(adjustment_id or ""):
        raise AdjustmentInputError("düzeltme kimliği [A-Za-z0-9._-]{1,128} olmalı")
    micro = parse_amount_micro_usd(amount_usd)
    start = _parse_instant(period_start, "period-start")
    end = _parse_instant(period_end, "period-end")
    if end <= start:
        raise AdjustmentInputError("period-end period-start'tan sonra olmalı")
    record = {
        "project_id": _text(project_id, "project"),
        "adjustment_id": adjustment_id,
        "amount_micro_usd": micro,
        "reason": _text(reason, "reason"),
        "provider_report_ref": _text(provider_report_ref, "provider-report-ref"),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "scope": _text(scope, "scope"),
    }
    content_sha256 = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {**record, "amount_usd": micro / 1_000_000}, content_sha256, micro


def run_cli(argv: list[str] | None = None) -> int:
    return _run_cli(argv)


def _run_cli(argv=None, *, firestore_client_factory=None, repository_factory=None, budget_usd=None, out=None) -> int:
    import argparse
    import os

    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m app.engines.event_intelligence.budget_adjustment")
    parser.add_argument("--project", required=True)
    parser.add_argument("--adjustment-id", required=True)
    parser.add_argument("--amount-usd", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--provider-report-ref", required=True)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--apply", action="store_true", help="yaz (varsayılan: dry-run)")
    args = parser.parse_args(argv)

    def emit(payload: dict, code: int) -> int:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        return code

    try:
        record, content_sha256, micro = build_adjustment_record(
            project_id=args.project, adjustment_id=args.adjustment_id, amount_usd=args.amount_usd,
            reason=args.reason, provider_report_ref=args.provider_report_ref,
            period_start=args.period_start, period_end=args.period_end, scope=args.scope,
        )
    except AdjustmentInputError as exc:
        return emit({"status": "INVALID_INPUT", "error": str(exc)}, 2)

    # Hedef proje üç kaynakta tutarlı olmalı; config'in sessiz varsayılanı kabul edilmez.
    if os.environ.get("FIREBASE_PROJECT_ID") != args.project:
        return emit({"status": "PROJECT_MISMATCH", "error": "FIREBASE_PROJECT_ID açıkça --project ile aynı olmalı"}, 2)
    if firestore_client_factory is None:
        from app.core.firebase import get_firestore_client

        firestore_client_factory = get_firestore_client
    db = firestore_client_factory()
    if getattr(db, "project", None) != args.project:
        return emit({"status": "PROJECT_MISMATCH", "error": "Firestore istemcisinin projesi --project ile aynı değil"}, 2)
    if repository_factory is None:
        from app.repositories.event_intelligence_budget_repository import FirestoreBudgetLedgerRepository

        repository_factory = FirestoreBudgetLedgerRepository
    if budget_usd is None:
        from app.core.config import EVENT_INTELLIGENCE_BUDGET_USD

        budget_usd = EVENT_INTELLIGENCE_BUDGET_USD
    repo = repository_factory(db=db)

    summary = {
        "adjustment_id": args.adjustment_id,
        "amount_usd": record["amount_usd"],
        "period_start": record["period_start"],
        "period_end": record["period_end"],
        "scope_length": len(record["scope"]),
        "reason_length": len(record["reason"]),
        "provider_report_ref_length": len(record["provider_report_ref"]),
        "content_sha256": content_sha256,
        "budget_usd": budget_usd,
    }
    preview = repo.preview_adjustment(args.adjustment_id, content_sha256)
    if preview["status"] == "CONFLICT":
        return emit({**summary, "status": "CONFLICT", "error": "aynı kimlik farklı içerikle kayıtlı"}, 2)
    after = preview["committed_usd"] + (record["amount_usd"] if preview["status"] == "WOULD_APPLY" else 0.0)
    summary.update(
        ledger_exists=preview["ledger_exists"],
        committed_usd_before=preview["committed_usd"],
        committed_usd_after=after,
        reserved_usd=preview["reserved_usd"],
        remaining_usd_after=budget_usd - after - preview["reserved_usd"],
    )
    if not args.apply:
        return emit({**summary, "status": "DRY_RUN", "would": preview["status"]}, 0)

    from app.repositories.event_intelligence_budget_repository import AdjustmentConflictError

    try:
        outcome = repo.apply_adjustment(args.adjustment_id, micro / 1_000_000, record, content_sha256)
    except AdjustmentConflictError:
        return emit({**summary, "status": "CONFLICT", "error": "aynı kimlik farklı içerikle kayıtlı"}, 2)
    except Exception as exc:  # noqa: BLE001 — yazılmadı; aynı komut güvenle tekrarlanabilir
        return emit({**summary, "status": "WRITE_FAILED", "error": type(exc).__name__}, 1)
    return emit({**summary, "status": outcome}, 0)


if __name__ == "__main__":
    raise SystemExit(run_cli())
