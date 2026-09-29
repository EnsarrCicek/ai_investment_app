"""POSITION-EXIT-1 — yerel kâğıt çıkış simülasyonu (saf, ağsız, üretime bağlı DEĞİL).

Amaç: bir alış pozisyonu için önceden tanımlı çıkış kuralını (kâr hedefi, anapara geri
kazanımı, zarar sınırı, iz süren sınır, azami süre) TAMAMLANMIŞ günlük kapanışlarla
değerlendirip SATIŞ İSTEĞİ üretmek ve yalnızca AÇIKÇA verilen gerçekleşme raporlarıyla
miktar/nakit/maliyeti güncellemek. Kârlı satış veya gerçekleşme garantisi YOKTUR; mekanizmanın
çalışması yatırım başarısının kanıtı değildir.

Sözleşme özeti
--------------
* Politikalar (aynı giriş için):
    A_FULL_AT_TARGET     : kapanış >= hedef -> kalan tüm miktar için satış isteği.
    B_RECOVER_PRINCIPAL  : kapanış >= hedef -> tahmini net tahsilatla başlangıç anaparasını
                           karşılayan EN KÜÇÜK tam lot miktarı için istek. Anaparanın geri
                           kazanıldığına yalnızca gerçekleşme raporlarının net tahsilatıyla karar
                           verilir; geri kazanılana kadar hedef koşulu sürdükçe açık kalan eksik
                           için yeniden istek üretilebilir.
    C_HALF_THEN_TRAIL    : kapanış >= hedef -> BAŞLANGIÇ adedinin %50'si, lot katına AŞAĞI
                           yuvarlanarak BİR KEZ istenir (0 lot çıkarsa satış yok, gerekçe
                           C_HALF_BELOW_ONE_LOT). Hedef görüldüğü seans iz süren sınır etkinleşir.
* Değerlendirme yalnızca T kapanışıyla (T < gelecekteki hiçbir veri kullanılmaz). T'de çıkan
  istek T'de gerçekleşmiş sayılmaz: rapor seansı > istek seansı olmalıdır.
* İstek miktar/nakit değiştirmez. Aktif (kapanmamış) istek varken ÇAKIŞAN yeni istek üretilmez;
  aynı seansta tetiklenen tüm gerekçeler tek istekte birlikte tutulur.
* Risk değerlendirmesi aktif istek nedeniyle ATLANMAZ. Tam çıkış gerekçesi (STOP_LOSS,
  TRAILING_STOP, MAX_HOLD) ÇIKIŞ NİYETİ olarak kaydedilir ve pozisyon kapanana kadar geçerli
  kalır. Aktif istek kalan tüm miktarı kapsamıyorsa (ör. kısmi kâr alma) o istek için İPTAL
  TALEBİ kaydedilir; iptal talebi iptal onayı DEĞİLDİR. Eski istek ancak raporla kapandığında
  (tam dolum, `final`, veya `type: CANCEL_CONFIRMED`) kalan GÜNCEL adet için tam çıkış isteği
  oluşturulur; iptal beklenirken gelen dolumlar önce hesaba katılır. Kalan adet 0 ise istek yok.
  Aktif istek zaten kalan tüm miktar için tam çıkışsa yeni gerekçeler yalnızca eklenir.
* Öncelik: STOP_LOSS > TRAILING_STOP > MAX_HOLD > TARGET. İlk üçü kalan TÜM miktar içindir.
* Zarar sınırı = giriş fiyatı × (1 − stop_loss_pct/100); hedeften bağımsızdır.
* İz süren sınır = (girişten sonraki tamamlanmış kapanışların en yükseği) × (1 − trailing_pct/100);
  en yüksek değer yalnızca artabildiği için sınır gevşemez.
* Azami süre = girişten sonra geçen BEKLENEN BIST seansı sayısı (takvim günü değil).
* Değerlendirme giriş seansından SONRAKİ seanslarda başlar (giriş anı bilinmediğinden).
* Eksik/durdurulmuş/geçersiz bar -> VERI_EKSIK: istek üretilmez, bu "TUT" veya "risk yok"
  anlamına gelmez.
* Masraf (TEMSİLİ model; gerçek kurum tarifesi bilinmiyor): rapor komisyon veriyorsa GERÇEK.
  Vermiyorsa komisyon İSTEK BAŞINA kümülatif hesaplanır: istek üzerindeki toplam komisyon =
  max(asgari, oran × istekteki kümülatif brüt), kuruşa yuvarlanır; her dolum yalnızca daha
  önce yüklenenden kalan farkı öder (parçalı dolumlarda asgari komisyon tekrar yüklenmez).
  VARSAYIM olarak işaretlenir. Kayma varsayımı yalnızca B'nin miktar PLANLAMASINDA kullanılır;
  gerçekleşme raporundaki fiyata ayrıca kayma UYGULANMAZ. Vergi hesaba katılmaz.
* Maliyet: ortalama maliyet (alış bedeli + alış masrafı) / başlangıç adedi; satılan miktara
  oransal maliyet düşülür. Gerçekleşen kâr = net satış tahsilatı − satılan miktarın maliyeti.
  Anapara geri kazanımı = kümülatif NET satış tahsilatı >= başlangıç anaparası. Bu, kalan
  hisselerin maliyetinin sıfır olduğu veya pozisyonun risksiz olduğu anlamına GELMEZ.
* Satış tahsilatı kayıtsal tutardır; takas/banka bakiyesi takip edilmez.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.services.market_data.trading_calendar import expected_trading_sessions

POLICIES = ("A_FULL_AT_TARGET", "B_RECOVER_PRINCIPAL", "C_HALF_THEN_TRAIL")
STOP_LOSS, TRAILING_STOP, MAX_HOLD, TARGET = "STOP_LOSS", "TRAILING_STOP", "MAX_HOLD", "TARGET"
PRIORITY = (STOP_LOSS, TRAILING_STOP, MAX_HOLD, TARGET)
KURUS = Decimal("0.01")
HUNDRED = Decimal(100)


class ScenarioError(ValueError):
    pass


def D(x, field_name: str) -> Decimal:
    if isinstance(x, bool) or not isinstance(x, (int, float, str, Decimal)):
        raise ScenarioError(f"{field_name} sayı olmalı: {x!r}")
    if isinstance(x, float) and not math.isfinite(x):
        raise ScenarioError(f"{field_name} sonlu olmalı: {x!r}")
    value = Decimal(str(x))
    if not value.is_finite():
        raise ScenarioError(f"{field_name} sonlu olmalı: {x!r}")
    return value


def _money(x: Decimal) -> str:
    return str(x.quantize(KURUS, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Params:
    policy: str
    target_pct: Decimal
    stop_loss_pct: Decimal
    trailing_pct: Decimal | None
    max_holding_sessions: int
    lot_size: int
    commission_rate_pct: Decimal
    min_commission: Decimal
    slippage_pct_assumption: Decimal

    @staticmethod
    def parse(policy: str, raw: dict) -> "Params":
        if policy not in POLICIES:
            raise ScenarioError(f"bilinmeyen politika: {policy}")
        required = ["target_pct", "stop_loss_pct", "max_holding_sessions", "lot_size", "fees"]
        if policy == "C_HALF_THEN_TRAIL":
            required.append("trailing_pct")
        missing = [k for k in required if raw.get(k) is None]
        fees = raw.get("fees") or {}
        missing += [f"fees.{k}" for k in ("commission_rate_pct", "min_commission", "slippage_pct_assumption") if fees.get(k) is None]
        if missing:
            raise ScenarioError(f"eksik parametre (uydurulmaz): {missing}")
        p = Params(
            policy=policy,
            target_pct=D(raw["target_pct"], "target_pct"),
            stop_loss_pct=D(raw["stop_loss_pct"], "stop_loss_pct"),
            trailing_pct=D(raw["trailing_pct"], "trailing_pct") if policy == "C_HALF_THEN_TRAIL" else None,
            max_holding_sessions=raw["max_holding_sessions"],
            lot_size=raw["lot_size"],
            commission_rate_pct=D(fees["commission_rate_pct"], "commission_rate_pct"),
            min_commission=D(fees["min_commission"], "min_commission"),
            slippage_pct_assumption=D(fees["slippage_pct_assumption"], "slippage_pct_assumption"),
        )
        for name in ("target_pct", "stop_loss_pct"):
            if not Decimal(0) < getattr(p, name) < HUNDRED:
                raise ScenarioError(f"{name} (0, 100) aralığında olmalı")
        if p.trailing_pct is not None and not Decimal(0) < p.trailing_pct < HUNDRED:
            raise ScenarioError("trailing_pct (0, 100) aralığında olmalı")
        for name in ("max_holding_sessions", "lot_size"):
            v = getattr(p, name)
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ScenarioError(f"{name} pozitif tam sayı olmalı")
        if p.commission_rate_pct < 0 or p.min_commission < 0 or not Decimal(0) <= p.slippage_pct_assumption < HUNDRED:
            raise ScenarioError("masraf/kayma varsayımları negatif olamaz")
        return p

    def commission(self, gross: Decimal) -> Decimal:
        return max(self.min_commission, gross * self.commission_rate_pct / HUNDRED).quantize(KURUS, rounding=ROUND_HALF_UP)


@dataclass
class Request:
    request_id: str
    session: date
    quantity: int
    reasons: list[str]
    primary_reason: str
    reference_close: Decimal
    planning_note: str | None = None
    filled_quantity: int = 0
    closed: bool = False
    reports: list[str] = field(default_factory=list)
    full_exit: bool = False
    cancel_requested_session: date | None = None
    cancel_confirmed: bool = False
    gross_total: Decimal = Decimal(0)
    commission_charged: Decimal = Decimal(0)
    later_reasons: list[str] = field(default_factory=list)

    def open_quantity(self) -> int:
        return 0 if self.closed else self.quantity - self.filled_quantity

    def status(self) -> str:
        if self.filled_quantity == self.quantity:
            return "FILLED"
        if self.cancel_confirmed:
            return "CANCELLED" if self.filled_quantity == 0 else "PARTIALLY_FILLED_CANCELLED"
        if not self.closed:
            base = "PENDING" if self.filled_quantity == 0 else "PARTIALLY_FILLED_OPEN"
            return base + ("_CANCEL_REQUESTED" if self.cancel_requested_session else "")
        return "NOT_FILLED_CLOSED" if self.filled_quantity == 0 else "PARTIALLY_FILLED_CLOSED"

    def view(self) -> dict:
        return {"request_id": self.request_id, "session": self.session.isoformat(), "quantity": self.quantity,
                "primary_reason": self.primary_reason, "reasons": self.reasons,
                "reference_close": str(self.reference_close), "planning_note": self.planning_note,
                "filled_quantity": self.filled_quantity, "status": self.status(), "reports": self.reports,
                "full_exit": self.full_exit, "later_reasons": self.later_reasons,
                "cancel_requested_session": self.cancel_requested_session.isoformat() if self.cancel_requested_session else None,
                "commission_charged": _money(self.commission_charged)}


def _bar_map(bars: list[dict]) -> tuple[dict[date, Decimal | None], list[str]]:
    out, notes = {}, []
    for b in bars:
        day = date.fromisoformat(b["session"])
        if day in out:
            raise ScenarioError(f"yinelenen bar: {day}")
        close = b.get("close")
        valid = (not b.get("halted")) and close is not None and not isinstance(close, bool) \
            and isinstance(close, (int, float, str)) and Decimal(str(close)).is_finite() and Decimal(str(close)) > 0
        out[day] = Decimal(str(close)) if valid else None
        if not valid:
            notes.append(f"BAR_UNUSABLE:{day.isoformat()}")
    return out, notes


def simulate(scenario: dict, policy: str, executions: list[dict]) -> dict:
    """Saf fonksiyon: girdileri değiştirmez."""
    p = Params.parse(policy, scenario.get("params") or {})
    entry = scenario["entry"]
    entry_session = date.fromisoformat(entry["session"])
    qty0 = entry["quantity"]
    if isinstance(qty0, bool) or not isinstance(qty0, int) or qty0 <= 0 or qty0 % p.lot_size:
        raise ScenarioError("giriş miktarı lot katı pozitif tam sayı olmalı")
    entry_price = D(entry["price"], "entry.price")
    if entry.get("fees") is None or entry.get("fees_basis") not in ("ACTUAL", "ASSUMED"):
        raise ScenarioError("entry.fees ve entry.fees_basis (ACTUAL|ASSUMED) açıkça verilmeli")
    entry_fees = D(entry["fees"], "entry.fees")
    if entry_price <= 0 or entry_fees < 0:
        raise ScenarioError("giriş fiyatı pozitif, masraf negatif olmayan olmalı")

    principal = qty0 * entry_price + entry_fees
    target_level = entry_price * (1 + p.target_pct / HUNDRED)
    stop_level = entry_price * (1 - p.stop_loss_pct / HUNDRED)

    bars, bar_notes = _bar_map(scenario.get("bars", []))
    reports = sorted(executions, key=lambda r: date.fromisoformat(r["session"]))
    last_day = max([*bars.keys(), *(date.fromisoformat(r["session"]) for r in reports), entry_session])
    calendar = expected_trading_sessions(entry_session, last_day)
    if calendar is None:
        raise ScenarioError("takvim bu yılları desteklemiyor (tahmin yapılmaz)")
    if entry_session not in calendar:
        raise ScenarioError("giriş seansı beklenen BIST seansı değil")
    sessions = [d for d in calendar if d > entry_session]
    for d in bars:
        if d not in calendar:
            bar_notes.append(f"BAR_NOT_EXPECTED_SESSION_IGNORED:{d.isoformat()}")

    remaining_qty, remaining_cost = qty0, principal
    net_proceeds = realized = Decimal(0)
    fee_basis = {entry["fees_basis"]}
    recovered_session = None
    peak: Decimal | None = None
    trailing_active = False
    c_half_done = False
    requests: list[Request] = []
    processed_reports: dict[str, dict] = {}
    report_log, timeline = [], []
    last_close = None
    exit_intent: dict | None = None
    full_exit_reasons = (STOP_LOSS, TRAILING_STOP, MAX_HOLD)

    def open_request():
        return next((r for r in requests if not r.closed and r.filled_quantity < r.quantity), None)

    def new_request(day, quantity, ordered, ref_close, full_exit, planning_note=None):
        req = Request(request_id=f"{policy}-R{len(requests) + 1}", session=day, quantity=quantity, reasons=list(ordered),
                      primary_reason=ordered[0], reference_close=ref_close, planning_note=planning_note, full_exit=full_exit)
        requests.append(req)
        # Aynı seansta bu isteğe atıf yapan rapor istekten ÖNCE işlendi -> ileriye bakma.
        for log in report_log:
            if (log.get("request_id") == req.request_id and log["session"] == day.isoformat()
                    and log["result"] == "REJECTED_UNKNOWN_OR_CLOSED_REQUEST"):
                log["result"] = "REJECTED_LOOKAHEAD"
        return req

    for day in sessions:
        events = {"session": day.isoformat()}
        # 1) Bu seansta gerçekleşme raporları (istekten SONRAKİ seanslar).
        applied = []
        for rep in (r for r in reports if date.fromisoformat(r["session"]) == day):
            rid = rep["report_id"]
            if rid in processed_reports:
                same = processed_reports[rid] == rep
                report_log.append({"report_id": rid, "session": day.isoformat(),
                                   "result": "IGNORED_DUPLICATE" if same else "REJECTED_CONFLICTING_DUPLICATE"})
                continue
            req = next((r for r in requests if r.request_id == rep.get("request_id")), None)
            qty = rep.get("filled_quantity")
            rtype = rep.get("type", "FILL")
            result = None
            if rtype not in ("FILL", "CANCEL_CONFIRMED"):
                result = "REJECTED_INVALID_TYPE"
            elif req is None or req.closed or req.filled_quantity == req.quantity:
                result = "REJECTED_UNKNOWN_OR_CLOSED_REQUEST"
            elif day <= req.session:
                result = "REJECTED_LOOKAHEAD"
            elif rtype == "CANCEL_CONFIRMED":
                processed_reports[rid] = rep
                req.closed = req.cancel_confirmed = True
                req.reports.append(rid)
                log = {"report_id": rid, "request_id": req.request_id, "session": day.isoformat(),
                       "result": "APPLIED_CANCEL_CONFIRMED", "unfilled_cancelled": req.quantity - req.filled_quantity}
                report_log.append(log)
                applied.append(log)
                continue
            elif isinstance(qty, bool) or not isinstance(qty, int) or qty < 0 or qty % p.lot_size:
                result = "REJECTED_INVALID_QUANTITY"
            elif req.filled_quantity + qty > req.quantity or qty > remaining_qty:
                result = "REJECTED_OVERFILL"
            elif qty > 0 and not (isinstance(rep.get("price"), (int, float, str)) and not isinstance(rep.get("price"), bool)
                                  and Decimal(str(rep["price"])).is_finite() and Decimal(str(rep["price"])) > 0):
                result = "REJECTED_INVALID_PRICE"
            if result:
                report_log.append({"report_id": rid, "request_id": rep.get("request_id"), "session": day.isoformat(), "result": result})
                processed_reports[rid] = rep
                continue
            processed_reports[rid] = rep
            entry_log = {"report_id": rid, "request_id": req.request_id, "session": day.isoformat(),
                         "filled_quantity": qty, "final": bool(rep.get("final")), "result": "APPLIED"}
            if qty > 0:
                price = Decimal(str(rep["price"]))
                gross = qty * price
                req.gross_total += gross
                if rep.get("commission") is not None:
                    commission, basis = D(rep["commission"], "commission"), "ACTUAL"
                else:  # istek başına kümülatif; asgari komisyon parçalı dolumda tekrarlanmaz
                    commission, basis = max(Decimal(0), p.commission(req.gross_total) - req.commission_charged), "ASSUMED"
                req.commission_charged += commission
                fee_basis.add(basis)
                net = gross - commission
                allocated = remaining_cost * qty / remaining_qty
                remaining_cost -= allocated
                remaining_qty -= qty
                net_proceeds += net
                realized += net - allocated
                req.filled_quantity += qty
                if recovered_session is None and net_proceeds >= principal:
                    recovered_session = day
                entry_log |= {"price": str(price), "gross": _money(gross), "commission": _money(commission),
                              "commission_basis": basis, "net_proceeds": _money(net),
                              "allocated_cost": _money(allocated), "realized_pnl": _money(net - allocated)}
            req.reports.append(rid)
            if rep.get("final") or req.filled_quantity == req.quantity:
                req.closed = True
            report_log.append(entry_log)
            applied.append(entry_log)
        events["fills"] = applied

        # 1b) Kayıtlı tam çıkış niyeti: çakışan istek kalmadıysa GÜNCEL kalan adet için istek.
        if exit_intent is not None and remaining_qty > 0 and open_request() is None:
            req = new_request(day, remaining_qty, exit_intent["reasons"], last_close, True)
            exit_intent["request_ids"].append(req.request_id)
            events["request_from_exit_intent"] = req.request_id

        # 2) T kapanışı değerlendirmesi.
        held = len([d for d in sessions if d <= day])
        close = bars.get(day)
        if remaining_qty == 0:
            events["evaluation"] = "POZISYON_KAPALI"
        elif close is None:
            events["evaluation"] = "VERI_EKSIK"  # TUT veya risk yok DEĞİL
        else:
            last_close = close
            peak = close if peak is None else max(peak, close)
            reasons = []
            notes = []
            if close <= stop_level:
                reasons.append(STOP_LOSS)
            trail_level = peak * (1 - p.trailing_pct / HUNDRED) if (trailing_active and p.trailing_pct) else None
            if trail_level is not None and close <= trail_level:
                reasons.append(TRAILING_STOP)
            if held >= p.max_holding_sessions:
                reasons.append(MAX_HOLD)
            target_qty = None
            if close >= target_level:
                if policy == "A_FULL_AT_TARGET":
                    reasons.append(TARGET)
                    target_qty = remaining_qty
                elif policy == "B_RECOVER_PRINCIPAL" and recovered_session is None:
                    shortfall = principal - net_proceeds
                    est_price = close * (1 - p.slippage_pct_assumption / HUNDRED)
                    q = next((q for q in range(p.lot_size, remaining_qty + 1, p.lot_size)
                              if q * est_price - p.commission(q * est_price) >= shortfall), None)
                    if q is None:
                        notes.append("B_RECOVERY_NOT_REACHABLE_WITH_REMAINING_QUANTITY")
                    else:
                        reasons.append(TARGET)
                        target_qty = q
                        notes.append(f"B_PLAN: eksik {_money(shortfall)} için tahmini fiyat {est_price} ile en küçük tam lot {q}")
                elif policy == "C_HALF_THEN_TRAIL" and not c_half_done:
                    c_half_done = True
                    trailing_active = True
                    half = (qty0 // 2) // p.lot_size * p.lot_size
                    half = min(half, remaining_qty)
                    if half == 0:
                        notes.append("C_HALF_BELOW_ONE_LOT: yarım lot uydurulmaz; satış yok, iz süren sınır tüm miktar için etkin")
                    else:
                        reasons.append(TARGET)
                        target_qty = half
            events |= {"evaluation": "DEGERLENDI", "close": str(close), "held_sessions": held,
                       "stop_level": str(stop_level), "target_level": str(target_level),
                       "trailing_level": str(trail_level) if trail_level is not None else None,
                       "triggered": [r for r in PRIORITY if r in reasons], "notes": notes}
            if reasons:
                ordered = [r for r in PRIORITY if r in reasons]
                active = open_request()
                if ordered[0] in full_exit_reasons:
                    full = [r for r in ordered if r in full_exit_reasons]
                    if exit_intent is None:
                        exit_intent = {"session": day.isoformat(), "reasons": full, "request_ids": []}
                        events["exit_intent"] = "RECORDED"
                    else:
                        exit_intent["reasons"] = [r for r in PRIORITY if r in set(exit_intent["reasons"]) | set(full)]
                        events["exit_intent"] = "UPDATED"
                    if active is None:
                        req = new_request(day, remaining_qty, ordered, close, True)
                        exit_intent["request_ids"].append(req.request_id)
                        events["request"] = req.request_id
                    elif active.full_exit and active.open_quantity() == remaining_qty:
                        active.later_reasons += [f"{day.isoformat()}:{r}" for r in ordered]
                        events["request"] = f"ACTIVE_FULL_EXIT_REASONS_ADDED:{active.request_id}"
                    else:
                        if active.cancel_requested_session is None:
                            active.cancel_requested_session = day
                        events["request"] = f"CANCEL_REQUESTED_WAITING_CONFIRMATION:{active.request_id}"
                elif active is not None:
                    events["request"] = f"SUPPRESSED_PENDING:{active.request_id}"
                else:
                    req = new_request(day, target_qty, ordered, close, target_qty == remaining_qty,
                                      "; ".join(n for n in notes if n.startswith("B_PLAN")) or None)
                    events["request"] = req.request_id
        active = open_request()
        events["state"] = {"remaining_quantity": remaining_qty, "remaining_cost": _money(remaining_cost),
                           "active_request": active.request_id if active else None,
                           "active_request_open_quantity": active.open_quantity() if active else 0,
                           "active_request_status": active.status() if active else None,
                           "cumulative_net_sale_proceeds": _money(net_proceeds), "realized_pnl": _money(realized),
                           "exit_intent_reasons": list(exit_intent["reasons"]) if exit_intent else None}
        timeline.append(events)

    for rep in reports:
        if date.fromisoformat(rep["session"]) not in sessions:
            report_log.append({"report_id": rep["report_id"], "request_id": rep.get("request_id"), "session": rep["session"],
                               "result": "REJECTED_NOT_EXPECTED_SESSION_AFTER_ENTRY"})
    if remaining_qty == 0:
        unrealized = Decimal(0)
    else:
        unrealized = (remaining_qty * last_close - remaining_cost) if last_close is not None else None
    assumed = "ASSUMED" in fee_basis
    return {
        "policy": policy,
        "data_origin": scenario.get("data_origin"),
        "params": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in p.__dict__.items()},
        "entry": {"session": entry_session.isoformat(), "quantity": qty0, "price": str(entry_price),
                  "fees": _money(entry_fees), "fees_basis": entry["fees_basis"]},
        "initial_principal": _money(principal),
        "levels": {"target": str(target_level), "stop_loss": str(stop_level)},
        "requests": [r.view() for r in requests],
        "reports": report_log,
        "timeline": timeline,
        "bar_notes": bar_notes,
        "summary": {
            "sold_quantity": qty0 - remaining_qty,
            "remaining_quantity": remaining_qty,
            "remaining_cost": _money(remaining_cost),
            "cumulative_net_sale_proceeds": _money(net_proceeds),
            "principal_recovered": recovered_session is not None,
            "principal_recovered_session": recovered_session.isoformat() if recovered_session else None,
            "realized_pnl": _money(realized),
            "last_valid_close": str(last_close) if last_close is not None else None,
            "unrealized_pnl_before_exit_fees": _money(unrealized) if unrealized is not None else None,
            "open_request": open_request().request_id if open_request() else None,
            "exit_intent": exit_intent,
            "fee_basis": "VARSAYIMA_DAYALI" if assumed else "GERCEK",
            "notes": ["Satış tahsilatı kayıtsal tutardır; takas/banka bakiyesi takip edilmez.",
                      "Anapara geri kazanımı kalan hisselerin maliyetinin sıfır olduğu veya risksiz olduğu anlamına gelmez.",
                      "Vergi hesaba katılmadı."] + (["Net sonuçlar varsayılan masraflara dayanır; kesin değildir."] if assumed else []),
        },
        "_exact": {"principal": principal, "remaining_cost": remaining_cost, "net_proceeds": net_proceeds, "realized": realized},
    }
