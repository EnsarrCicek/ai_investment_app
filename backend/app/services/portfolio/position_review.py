"""Yerel, salt-okunur pozisyon değerleme ve kullanıcı risk sınırı değerlendirmesi.

Firestore, ağ, bildirim veya pozisyon yazımı YOKTUR; mevcut /portfolio uç noktaları,
`pnl_calculator` ve karar motoru DEĞİŞTİRİLMEZ. Otomatik AL/SAT kararı üretmez.

Girdiler (hepsi açık):
  * positions        : `PortfolioPosition` alanlarıyla lotlar (aynı hissenin lotları birleştirilir;
                       toplam maliyet = Σ adet × alış fiyatı, yuvarlanmadan).
  * price_records    : {symbol, session, close, price_basis, source?,
                        retrieved_at?, source_updated_at?, source_timestamp?}
      - session           : günlük barın SEANS TARİHİ etiketi (saat bilgisi taşımaz).
      - retrieved_at      : verinin girdiyi hazırlayan tarafça ALINDIĞI an.
      - source_updated_at : kaynağın bildirdiği güncelleme anı.
      - source_timestamp  : anlamı BİLİNMEYEN kaynak zaman damgası; yalnızca gösterilir,
                            tamamlanmışlığı kanıtlamaz veya çürütmez (gece yarısı bar
                            etiketi de, son işlem zamanı da olabilir).
  * evaluated_at     : saat dilimli değerlendirme zamanı.
  * corporate_action_checks (isteğe bağlı): {symbol: {checked_from, checked_through,
                       split_or_bonus_dates: [...], source?}}
  * limits (isteğe bağlı): {max_loss_pct, max_weight_pct}

Fiyat–pozisyon uyumu:
  Alış fiyatı kullanıcının girdiği işlem fiyatıdır; lot/maliyet bölünme veya bedelsiz
  sermaye artırımına göre uygulamada düzeltilmez. `BistProvider` yfinance düzeltmeli
  seriyi kullanır. Mevcut veri akışı fiyat, adet ve maliyet uyumunu KANITLAMAZ (bu, her
  güncel kâr/zararın yanlış olduğu anlamına gelmez). Kâr/zarar ancak
    (1) fiyat kaydı `price_basis == "RAW_UNADJUSTED"` olarak beyan edilmişse VE
    (2) en erken lot tarihinden değerleme seansına kadar bölünme/bedelsiz kontrolü
        beyan edilmiş ve bu aralıkta olay YOKSA
  hesaplanır. İkisi de GİRDİ BEYANIDIR; modül dış kaynaktan doğrulamaz. Aksi halde
  PRICE_BASIS_UNVERIFIED / CORPORATE_ACTIONS_UNVERIFIED / CORPORATE_ACTION_IN_HOLDING_PERIOD
  döner; kâr/zarar ve sınır sonucu üretilmez. Kurumsal işlem düzeltmesi YAPILMAZ.
  Hesaplanan değer fiyat bazlı gerçekleşmemiş farktır; komisyon, vergi ve nakit temettü
  dahil toplam net getiri DEĞİLDİR.

Değerleme seansı: saat dilimli `evaluated_at` üzerinden `latest_expected_completed_date` ve
BIST takvimine göre beklenen SON TAMAMLANMIŞ seans (18.00 + 30 dk). Takvimde olmayan yıl
tahminle tamamlanmaz (CALENDAR_UNSUPPORTED). `retrieved_at` veya `source_updated_at`
`evaluated_at`'ten sonraysa gözlem kullanılmaz (OBSERVED_AFTER_EVALUATION). `retrieved_at`
o seansın kapanış + kesinleşme payından önceyse bar tamamlanmamıştır (INCOMPLETE_BAR).
`retrieved_at` yoksa tamamlanmışlık yalnızca takvim sözleşmesine dayanır ve bu çıktıda
belirtilir. Eski/eksik/sonlu olmayan/geçersiz fiyat sıfır sayılmaz; son bilinen geçerli
fiyat yalnızca bilgi olarak (STALE) gösterilir.

Ağırlık: yalnızca AÇIK HİSSE POZİSYONLARI içindeki ağırlıktır (nakit takibi yok; "toplam
varlık ağırlığı" DEĞİLDİR). Bir pozisyon bile değerlenemezse ağırlıklar ve yoğunlaşma
BELIRSIZ; kalan hisseler %100'e normalize edilmez, yalnızca bilinen ara toplam verilir.

Sınır karşılaştırması: ölçüler 6 ondalığa yuvarlanır; eşitlik aşım DEĞİLDİR (SINIR_ICINDE).

Kullanım: python -m app.services.portfolio.position_review <girdi.json> [--out <çıktı.json>]
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from app.engines.technical.session_timing import ISTANBUL_TZ, SESSION_CLOSE
from app.models.portfolio_position import PortfolioPosition
from app.services.market_data.completed_bars import DAILY_BAR_FINALIZATION_DELAY_MINUTES, latest_expected_completed_date
from app.services.market_data.trading_calendar import expected_trading_sessions

REVIEW_VERSION = "position-review-v1"
MEASURE_DECIMALS = 6
CALENDAR_LOOKBACK_DAYS = 20
RAW_BASIS = "RAW_UNADJUSTED"
DECLARATION = "GIRDI_BEYANI_MODUL_DIS_KAYNAKTAN_DOGRULAMADI"

# Pozisyon değerleme durumları
VALUED = "DEGERLENDI"
CALENDAR_UNSUPPORTED = "CALENDAR_UNSUPPORTED"
INVALID_POSITION = "INVALID_POSITION"
BUY_AFTER_VALUATION_SESSION = "BUY_AFTER_VALUATION_SESSION"
MISSING_PRICE = "MISSING_PRICE"
STALE_PRICE = "STALE_PRICE"
INVALID_PRICE = "INVALID_PRICE"
INCOMPLETE_BAR = "INCOMPLETE_BAR"
OBSERVED_AFTER_EVALUATION = "OBSERVED_AFTER_EVALUATION"
CONFLICTING_PRICE_RECORDS = "CONFLICTING_PRICE_RECORDS"
PRICE_BASIS_UNVERIFIED = "PRICE_BASIS_UNVERIFIED"
CORPORATE_ACTIONS_UNVERIFIED = "CORPORATE_ACTIONS_UNVERIFIED"
CORPORATE_ACTION_IN_HOLDING_PERIOD = "CORPORATE_ACTION_IN_HOLDING_PERIOD"

# Sınır durumları
LIMIT_NOT_DEFINED = "SINIR_TANIMLI_DEGIL"
LIMIT_NOT_EVALUATED = "DEGERLENDIRILEMEDI"
LIMIT_WITHIN = "SINIR_ICINDE"
LIMIT_EXCEEDED = "SINIR_ASILDI"

WEIGHTS_COMPLETE = "TAM"
WEIGHTS_UNDETERMINED = "BELIRSIZ"


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class _Price:
    session: date
    close: float | None
    basis: str | None
    source: str | None
    source_timestamp: datetime | None  # anlamı bilinmiyor; yalnızca gösterilir
    retrieved_at: datetime | None
    source_updated_at: datetime | None
    finite_positive: bool


def _parse_dt(value, field: str) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        raise InputError(f"{field} saat dilimi içermeli: {value!r}")
    return dt


def _parse_date(value, field: str) -> date:
    try:
        return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))
    except ValueError as exc:
        raise InputError(f"{field} geçersiz tarih: {value!r}") from exc


def _finite_positive(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def _round(x: float) -> float:
    return round(x, MEASURE_DECIMALS)


def valuation_session(evaluated_at: datetime) -> date | None:
    """Beklenen son tamamlanmış BIST seansı; takvim desteklemiyorsa None (tahmin yok)."""
    last_day = latest_expected_completed_date(evaluated_at)
    sessions = expected_trading_sessions(last_day - timedelta(days=CALENDAR_LOOKBACK_DAYS), last_day)
    if not sessions:
        return None
    return sessions[-1]


def _bar_final_after(session: date) -> datetime:
    close = datetime.combine(session, SESSION_CLOSE, tzinfo=ISTANBUL_TZ)
    return close + timedelta(minutes=DAILY_BAR_FINALIZATION_DELAY_MINUTES)


def _parse_price(rec: dict) -> tuple[str, _Price]:
    symbol = str(rec["symbol"]).upper()
    close = rec.get("close")
    def opt_dt(field):
        value = rec.get(field)
        return _parse_dt(value, f"{symbol}.{field}") if value is not None else None

    return symbol, _Price(
        session=_parse_date(rec["session"], f"{symbol}.session"),
        close=float(close) if isinstance(close, (int, float)) and not isinstance(close, bool) else None,
        basis=rec.get("price_basis"),
        source=rec.get("source"),
        source_timestamp=opt_dt("source_timestamp"),
        retrieved_at=opt_dt("retrieved_at"),
        source_updated_at=opt_dt("source_updated_at"),
        finite_positive=_finite_positive(close),
    )


def _price_view(p: _Price) -> dict:
    return {"session": p.session.isoformat(), "close": p.close if p.finite_positive else None,
            "price_basis": p.basis, "source": p.source,
            "retrieved_at": p.retrieved_at.isoformat() if p.retrieved_at else None,
            "source_updated_at": p.source_updated_at.isoformat() if p.source_updated_at else None,
            "source_timestamp_meaning_unknown": p.source_timestamp.isoformat() if p.source_timestamp else None,
            "bar_completion_evidence": ("ALINMA_ZAMANI_KESINLESME_PAYINDAN_SONRA" if p.retrieved_at
                                        else "YALNIZCA_TAKVIM_SOZLESMESI_ALINMA_ZAMANI_YOK")}


def _select_price(records: list[_Price], session: date,
                  evaluated_at: datetime) -> tuple[_Price | None, str | None, dict | None, list[str]]:
    """(kullanılacak kayıt, hata durumu, son bilinen geçerli eski fiyat, notlar).

    Tamamlanmışlık seans tarihinden (takvim + evaluated_at) ve varsa `retrieved_at`'ten
    belirlenir; anlamı bilinmeyen `source_timestamp` karara katılmaz."""
    notes = []
    complete = []
    for p in records:
        day = p.session.isoformat()
        if p.session > session:
            notes.append(f"FUTURE_OR_INCOMPLETE_SESSION_IGNORED:{day}")
            continue
        if any(t is not None and t > evaluated_at for t in (p.retrieved_at, p.source_updated_at)):
            notes.append(f"{OBSERVED_AFTER_EVALUATION}:{day}")
            continue
        if p.retrieved_at is not None and p.retrieved_at < _bar_final_after(p.session):
            notes.append(f"RETRIEVED_BEFORE_BAR_FINAL:{day}")
            continue
        if p.source_timestamp is not None:
            notes.append(f"SOURCE_TIMESTAMP_MEANING_UNKNOWN_NOT_USED:{day}")
        if p.retrieved_at is None:
            notes.append(f"RETRIEVAL_TIME_MISSING_COMPLETION_BY_CALENDAR_ONLY:{day}")
        complete.append(p)
    older_valid = sorted((p for p in complete if p.session < session and p.finite_positive), key=lambda p: p.session)
    last_known = _price_view(older_valid[-1]) if older_valid else None
    at_session = [p for p in complete if p.session == session]
    if not at_session:
        if f"RETRIEVED_BEFORE_BAR_FINAL:{session.isoformat()}" in notes:
            return None, INCOMPLETE_BAR, last_known, notes
        if f"{OBSERVED_AFTER_EVALUATION}:{session.isoformat()}" in notes:
            return None, OBSERVED_AFTER_EVALUATION, last_known, notes
        return None, (STALE_PRICE if last_known else MISSING_PRICE), last_known, notes
    if len({(p.close, p.basis) for p in at_session}) > 1:
        return None, CONFLICTING_PRICE_RECORDS, last_known, notes
    chosen = at_session[0]
    if not chosen.finite_positive:
        return None, INVALID_PRICE, last_known, notes
    return chosen, None, last_known, notes


def _corporate_action_status(check: dict | None, start: date, session: date) -> tuple[str | None, dict | None]:
    if not check:
        return CORPORATE_ACTIONS_UNVERIFIED, None
    frm = _parse_date(check["checked_from"], "checked_from")
    thru = _parse_date(check["checked_through"], "checked_through")
    events = sorted(_parse_date(d, "split_or_bonus_dates") for d in check.get("split_or_bonus_dates", []))
    view = {"checked_from": frm.isoformat(), "checked_through": thru.isoformat(),
            "required_from": start.isoformat(), "required_through": session.isoformat(),
            "split_or_bonus_dates": [d.isoformat() for d in events], "source": check.get("source"),
            "evidence": DECLARATION}
    in_period = [d for d in events if start < d <= session]
    if in_period:
        return CORPORATE_ACTION_IN_HOLDING_PERIOD, view
    if frm > start or thru < session:
        return CORPORATE_ACTIONS_UNVERIFIED, view
    return None, view


def _limit(value: float | None, limit: float | None) -> str:
    if limit is None:
        return LIMIT_NOT_DEFINED
    if value is None:
        return LIMIT_NOT_EVALUATED
    return LIMIT_EXCEEDED if value > limit else LIMIT_WITHIN


def _parse_limits(raw: dict | None) -> dict:
    out = {"max_loss_pct": None, "max_weight_pct": None}
    for key in out:
        value = (raw or {}).get(key)
        if value is None:
            continue
        if not _finite_positive(value) or value > 100:
            raise InputError(f"{key} (0, 100] aralığında sonlu bir sayı olmalı: {value!r}")
        out[key] = float(value)
    return out


def review(payload: dict) -> dict:
    """Saf fonksiyon: girdiyi değiştirmez, dış kaynağa erişmez."""
    evaluated_at = _parse_dt(payload["evaluated_at"], "evaluated_at")
    limits = _parse_limits(payload.get("limits"))
    lots = [PortfolioPosition.model_validate(p) for p in payload.get("positions", [])]
    prices: dict[str, list[_Price]] = {}
    for rec in payload.get("price_records", []):
        symbol, p = _parse_price(rec)
        prices.setdefault(symbol, []).append(p)
    checks = {str(k).upper(): v for k, v in (payload.get("corporate_action_checks") or {}).items()}

    session = valuation_session(evaluated_at)
    report = {
        "review_version": REVIEW_VERSION,
        "evaluated_at": evaluated_at.isoformat(),
        "expected_valuation_session": session.isoformat() if session else None,
        "calendar_status": "SUPPORTED" if session else CALENDAR_UNSUPPORTED,
        "limits": limits,
        "notes": ["Otomatik AL/SAT kararı değildir.",
                  "Ağırlık yalnızca açık hisse pozisyonları içindedir; nakit takibi yok.",
                  "Kâr/zarar fiyat bazlı gerçekleşmemiş farktır; komisyon, vergi ve nakit temettü dahil "
                  "toplam net getiri değildir.",
                  "price_basis ve kurumsal işlem kontrolü girdiyi sağlayanın beyanıdır; modül bunları dış "
                  "kaynaktan doğrulamaz. Çıktı doğrulanmış gerçek portföy değildir."],
    }

    by_symbol: dict[str, list[PortfolioPosition]] = {}
    for lot in lots:
        by_symbol.setdefault(lot.asset.upper(), []).append(lot)

    positions = []
    for symbol in sorted(by_symbol):
        group = by_symbol[symbol]
        valid_lots = all(_finite_positive(l.quantity) and _finite_positive(l.buy_price) for l in group)
        quantity = sum(l.quantity for l in group) if valid_lots else None
        total_cost = sum(l.quantity * l.buy_price for l in group) if valid_lots else None
        first_buy = min(l.buy_date.astimezone(ISTANBUL_TZ).date() if l.buy_date.tzinfo else l.buy_date.date() for l in group)
        last_buy = max(l.buy_date.astimezone(ISTANBUL_TZ).date() if l.buy_date.tzinfo else l.buy_date.date() for l in group)
        row = {"symbol": symbol, "lot_count": len(group), "quantity": quantity, "total_cost": total_cost,
               "first_buy_date": first_buy.isoformat(), "expected_session": report["expected_valuation_session"],
               "price_used": None, "last_known_price_stale": None, "price_notes": [],
               "corporate_action_check": None, "price_basis_evidence": DECLARATION, "status": None, "data_sufficiency": "YETERSIZ",
               "price_basis_status": "DOGRULANAMADI", "market_value": None, "unrealized_pnl": None,
               "unrealized_pnl_pct": None, "weight_in_open_stock_positions_pct": None,
               "limit_checks": {}}
        if session is None:
            row["status"] = CALENDAR_UNSUPPORTED
        elif not valid_lots:
            row["status"] = INVALID_POSITION
        else:
            chosen, error, last_known, notes = _select_price(prices.get(symbol, []), session, evaluated_at)
            row["last_known_price_stale"] = last_known if error else None
            row["price_notes"] = notes
            if error:
                row["status"] = error
            else:
                row["price_used"] = _price_view(chosen)
                row["data_sufficiency"] = "YETERLI"
                ca_error, ca_view = _corporate_action_status(checks.get(symbol), first_buy, session)
                row["corporate_action_check"] = ca_view
                if last_buy > session:
                    row["status"] = BUY_AFTER_VALUATION_SESSION
                elif chosen.basis != RAW_BASIS:
                    row["status"] = PRICE_BASIS_UNVERIFIED
                elif ca_error:
                    row["status"] = ca_error
                    if ca_error == CORPORATE_ACTION_IN_HOLDING_PERIOD:
                        row["price_basis_status"] = "BEYANA_GORE_UYUMSUZ"
                else:
                    row["status"] = VALUED
                    row["price_basis_status"] = "BEYANA_GORE_UYUMLU"
                    mv = quantity * chosen.close
                    row["market_value"] = _round(mv)
                    row["unrealized_pnl"] = _round(mv - total_cost)
                    row["unrealized_pnl_pct"] = _round((mv - total_cost) / total_cost * 100)
        positions.append(row)

    valued = [r for r in positions if r["status"] == VALUED]
    complete = bool(positions) and len(valued) == len(positions)
    known_subtotal = _round(sum(r["market_value"] for r in valued)) if valued else 0.0
    concentration = {"status": WEIGHTS_COMPLETE if complete else WEIGHTS_UNDETERMINED,
                     "open_stock_positions": len(positions), "valued_positions": len(valued),
                     "known_market_value_subtotal": known_subtotal,
                     "total_open_stock_market_value": known_subtotal if complete else None,
                     "herfindahl_index": None}
    if complete:
        for r in positions:
            r["weight_in_open_stock_positions_pct"] = _round(r["market_value"] / known_subtotal * 100)
        concentration["herfindahl_index"] = _round(sum((r["market_value"] / known_subtotal) ** 2 for r in positions))
    for r in positions:
        loss = -r["unrealized_pnl_pct"] if r["unrealized_pnl_pct"] is not None else None
        r["limit_checks"] = {
            "max_loss_pct": {"limit": limits["max_loss_pct"], "loss_pct_vs_cost": loss,
                             "status": _limit(loss, limits["max_loss_pct"])},
            "max_weight_pct": {"limit": limits["max_weight_pct"], "weight_pct": r["weight_in_open_stock_positions_pct"],
                               "status": _limit(r["weight_in_open_stock_positions_pct"], limits["max_weight_pct"])},
        }
    report["positions"] = positions
    report["open_stock_concentration"] = concentration
    return report


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 3) or (len(argv) == 3 and argv[1] != "--out"):
        print("Kullanım: python -m app.services.portfolio.position_review <girdi.json> [--out <çıktı.json>]", file=sys.stderr)
        return 2
    payload = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    try:
        result = review(payload)
    except InputError as exc:
        print(f"GIRDI_HATASI: {exc}", file=sys.stderr)
        return 2
    if "label" in payload:
        result["input_label"] = payload["label"]
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if len(argv) == 3:
        Path(argv[2]).write_text(text, encoding="utf-8")
        print(argv[2])
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
