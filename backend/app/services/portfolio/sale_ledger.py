"""Kısmi/tam satış muhasebesi — ağırlıklı ortalama maliyet, kesin ondalık (Decimal), değişmez defter.

Ağ/depo bağımsız saf fonksiyonlar; Firestore işlemi `PortfolioLedgerRepository.execute_sale` içinde bu fonksiyonları
çağırır. Vergi/hukuki maliyet yöntemi iddiası DEĞİLDİR; uygulama içi deterministik portföy muhasebesidir.

Defter modeli:
* Alış lotları (`portfolio_positions`) satışta DEĞİŞTİRİLMEZ; satış ayrı ve değişmez bir `PortfolioTransaction` kaydıdır.
* Satış kaydı, satış anındaki lot kimliklerini (`ledger_lot_ids`) taşır. Bir satış yalnız lot kimliklerinin TAMAMI hâlâ
  mevcutsa geçerli pozisyona uygulanır. Tam satış lotları siler (mevcut `/close` sözleşmesi); bu yüzden kapatılıp yeniden
  açılan pozisyon (yeni lot kimlikleri) eski satışlardan etkilenmez. Düzenleme (`replace_for_asset`) de lotları yeniden
  yazdığı için kullanıcının yeni tanımı eski satışları geçersiz kılar. `ledger_lot_ids` taşımayan eski kayıtlar
  (eski `/close`) hiçbir pozisyona uygulanmaz.
* Kalan adet/maliyet = alışlar − uygulanan satışların satılan adet/maliyeti.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext

from app.models.portfolio_position import PortfolioPosition, merged_currency
from app.models.portfolio_transaction import PortfolioTransaction

DISPOSAL_METHOD = "WEIGHTED_AVERAGE"
PRECISION = 34  # Decimal bağlam hassasiyeti; ara sonuçlarda yuvarlama yok


class SaleError(ValueError):
    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code, self.status, self.message = code, status, message


def dec(value) -> Decimal:
    """float/str/int -> Decimal; float, ikili kayan noktanın açılımı değil kullanıcının girdiği kısa gösterimle (repr)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise SaleError("INVALID_NUMBER", 422, f"geçersiz sayı: {value!r}")
    d = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))
    if not d.is_finite():
        raise SaleError("INVALID_NUMBER", 422, f"sonlu olmayan sayı: {value!r}")
    return d


def weighted_average_sale(total_quantity, total_cost, quantity_to_sell, sell_price) -> dict[str, Decimal]:
    """Ağırlıklı ortalama satış hesabı (saf). Satılan maliyet, yuvarlanmış ortalama ile DEĞİL
    `satılan × toplam_maliyet / toplam_adet` olarak hesaplanır; ara sonuç yuvarlanmaz."""
    tq, tc, q, p = dec(total_quantity), dec(total_cost), dec(quantity_to_sell), dec(sell_price)
    if tq <= 0:
        raise SaleError("NO_AVAILABLE_QUANTITY", 404, "Satılabilir adet yok.")
    if q <= 0:
        raise SaleError("INVALID_QUANTITY", 422, "Satış adedi pozitif olmalı.")
    if p <= 0:
        raise SaleError("INVALID_SELL_PRICE", 422, "Satış fiyatı pozitif olmalı.")
    if q > tq:
        raise SaleError("QUANTITY_EXCEEDS_AVAILABLE", 422, "Satış adedi mevcut adetten fazla.")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        disposed = q * tc / tq
        proceeds = q * p
        return {
            "average_cost_at_sale": tc / tq,
            "sold_quantity": q,
            "disposed_cost_basis": disposed,
            "sale_proceeds": proceeds,
            "realized_pnl": proceeds - disposed,
            "remaining_quantity": tq - q,
            "remaining_cost_basis": tc - disposed,
        }


def applicable_sales(lots: list[tuple[str, PortfolioPosition]],
                     sales: list[tuple[str, PortfolioTransaction]]) -> list[tuple[str, PortfolioTransaction]]:
    lot_ids = {lot_id for lot_id, _ in lots}
    return [(sid, s) for sid, s in sales if s.ledger_lot_ids and set(s.ledger_lot_ids) <= lot_ids]


def ledger_totals(lots: list[tuple[str, PortfolioPosition]],
                  sales: list[tuple[str, PortfolioTransaction]]) -> tuple[Decimal, Decimal, list[str]]:
    """(kalan adet, kalan maliyet, uygulanan satış kimlikleri) — tam hassasiyet."""
    applied = applicable_sales(lots, sales)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        quantity = sum((dec(p.quantity) for _, p in lots), Decimal(0))
        cost = sum((dec(p.quantity) * dec(p.buy_price) for _, p in lots), Decimal(0))
        for _, s in applied:
            quantity -= dec(s.quantity)
            cost -= dec(s.disposed_cost_basis)
    return quantity, cost, sorted(sid for sid, _ in applied)


def remaining_position(user_id: str, asset: str, lots: list[tuple[str, PortfolioPosition]],
                       sales: list[tuple[str, PortfolioTransaction]]) -> tuple[PortfolioPosition | None, list[str]]:
    """Kanonik açık pozisyonun TEK birleşik kaydı (salt okuma, depoya yazılmaz). Ortalama maliyet kesin kalan
    maliyet / kalan adet (ara yuvarlama yok; float'a yalnız sözleşme sınırında). Kapalıysa (adet <= 0) None."""
    if not lots:
        return None, []
    qty, cost, sale_ids = ledger_totals(lots, sales)
    if qty <= 0:
        return None, sale_ids
    with localcontext() as ctx:
        ctx.prec = PRECISION
        avg = cost / qty
    positions = [p for _, p in lots]
    return PortfolioPosition(user_id=user_id, asset=asset, buy_price=float(avg), quantity=float(qty),
                             buy_date=min(p.buy_date for p in positions), created_at=max(p.created_at for p in positions),
                             currency=merged_currency(positions)), sale_ids


def remaining_review_lots(lots: list[tuple[str, PortfolioPosition]],
                          sales: list[tuple[str, PortfolioTransaction]]) -> list[PortfolioPosition]:
    """`position_review` girdisi için kanonik kalan durumun lot temsili (salt okuma, depoya yazılmaz).

    Satış yoksa gerçek lotlar aynen. Satış varsa ağırlıklı ortalama yönteminin oransal temsili: her lotun adedi
    `adet × kalan_adet / toplam_alış_adedi`, birim maliyeti `kalan_maliyet / kalan_adet` (kesin, ara yuvarlama yok).
    Toplam adet = kalan adet, toplam maliyet = kalan maliyet; lot tarihleri korunur (en erken tarih kurumsal işlem
    kapsamının başlangıcı, en geç tarih 'değerleme seansından sonra alış' kapısı için)."""
    qty, cost, sale_ids = ledger_totals(lots, sales)
    if not sale_ids:
        return [p for _, p in lots]
    if qty <= 0:
        return []
    with localcontext() as ctx:
        ctx.prec = PRECISION
        bought = sum((dec(p.quantity) for _, p in lots), Decimal(0))
        avg = cost / qty
        return [p.model_copy(update={"quantity": float(dec(p.quantity) * qty / bought), "buy_price": float(avg)})
                for _, p in lots]


def resolve_currency(position_currency: str | None, request_currency: str | None) -> str | None:
    """İşlem birimi pozisyondan gelir. Pozisyon birimi bilinmiyorsa istekten benimsenmez; farklıysa 422 (döviz çevrimi yok)."""
    if position_currency is None:
        return None
    if request_currency is not None and request_currency != position_currency:
        raise SaleError("CURRENCY_MISMATCH", 422, "Satış para birimi pozisyonun kayıtlı para birimiyle uyuşmuyor.")
    return position_currency


@dataclass(frozen=True)
class SalePlan:
    transaction: PortfolioTransaction
    full: bool
    lot_ids: list[str]


def plan_sale(user_id: str, asset: str, lots: list[tuple[str, PortfolioPosition]],
              sales: list[tuple[str, PortfolioTransaction]], *, quantity, sell_price, sell_date: datetime | None,
              expected_version: str | None, request_currency: str | None, now: datetime,
              corporate_actions_verified: bool = False) -> SalePlan:
    """Satış planı (saf). `quantity=None` -> kalan adedin tamamı. `expected_version=None` -> sürüm kontrolü yok
    (yalnız eski `/close` uyumu için; yeni `/sell` her zaman sürüm ister)."""
    from app.services.portfolio.limit_check import position_version
    from app.services.portfolio.pnl_calculator import position_basis_verification

    if not lots:
        raise SaleError("POSITION_NOT_FOUND", 404, f"'{asset}' için açık bir pozisyon bulunamadı")
    total_qty, total_cost, sale_ids = ledger_totals(lots, sales)
    version = position_version(lots, sale_ids)
    if expected_version is not None and expected_version != version:
        raise SaleError("POSITION_CHANGED", 409, "Pozisyon, satış ekranı açıldıktan sonra değişmiş. Yenileyip tekrar deneyin.")
    if total_qty <= 0:
        raise SaleError("NO_AVAILABLE_QUANTITY", 404, "Satılabilir adet yok.")
    currency = resolve_currency(merged_currency([p for _, p in lots]), request_currency)
    acc = weighted_average_sale(total_qty, total_cost, total_qty if quantity is None else quantity, sell_price)
    basis_verified, _ = position_basis_verification(corporate_actions_verified)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        pct = (acc["realized_pnl"] / acc["disposed_cost_basis"] * 100) if acc["disposed_cost_basis"] else Decimal(0)
    tx = PortfolioTransaction(
        user_id=user_id, asset=asset,
        quantity=float(acc["sold_quantity"]),
        buy_price=float(acc["average_cost_at_sale"]),
        buy_date=min(p.buy_date for _, p in lots),
        sell_price=float(dec(sell_price)),
        sell_date=sell_date or now,
        realized_pnl=float(acc["realized_pnl"].quantize(Decimal("0.01"))),
        realized_pnl_percent=float(pct.quantize(Decimal("0.01"))),
        created_at=now,
        currency=currency,
        disposal_method=DISPOSAL_METHOD,
        average_cost_at_sale=str(acc["average_cost_at_sale"]),
        disposed_cost_basis=str(acc["disposed_cost_basis"]),
        sale_proceeds=str(acc["sale_proceeds"]),
        realized_pnl_exact=str(acc["realized_pnl"]),
        remaining_quantity=str(acc["remaining_quantity"]),
        remaining_cost_basis=str(acc["remaining_cost_basis"]),
        position_version_before=version,
        basis_verified=basis_verified,
        ledger_lot_ids=sorted(lot_id for lot_id, _ in lots),
    )
    return SalePlan(transaction=tx, full=acc["remaining_quantity"] == 0, lot_ids=sorted(lot_id for lot_id, _ in lots))


def default_now() -> datetime:
    return datetime.now(timezone.utc)
