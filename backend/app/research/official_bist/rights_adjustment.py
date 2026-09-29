"""Bedelli sermaye artırımı için ARAŞTIRMA fiyat dönüşümü (saf; ağsız; üretime bağlı DEĞİL).

Birincil kaynak (yöntem): Borsa İstanbul "Paya Dayalı Vadeli İşlem ve Opsiyon Sözleşmelerinde Özsermaye
Halleri Uyarlamalarına İlişkin Esaslar" genelgesi (gn414yeni.pdf):
    Ft = (Fk + n2 × R) / (1 + n2)        (bedelli; n1 = 0, T = 0)
    Fk = payların özsermaye hali öncesi son kapanış fiyatı; n2 = rüçhan hakkı kullanma oranı;
    R  = 1 TL nominal değerli payın rüçhan hakkı kullanma fiyatı; DK = Ft / Fk.
    Genelgedeki örnek: Fk 6,00, %100 bedelli, R 1 -> Ft 3,50; DK VİOP fiyatlarına çarpan olarak uygulanır.
Uygulama tarihi: rüçhan hakkı kullanım başlangıcı (BIST endeks kural seti 2025; bültende o seans
"OZSERMAYE HALI" = 01). Kayıt/ödeme tarihi düzeltme tarihi olarak KULLANILMAZ.

AYRIM: Ft resmî teorik fiyat tanımıdır. Aşağıdaki geçmiş OHLC dönüşümü (hak kullanımından ÖNCEKİ
seansların OHLC'sini DK ile çarpmak) bir ARAŞTIRMA dönüşümüdür; "BIST'in resmî düzeltilmiş serisi"
DEĞİLDİR. Spot piyasa genelgesi (gn2013415, 2012) teorik fiyatta ağırlıklı ortalama fiyatı (Fa)
tanımlar; o belgedeki formül görsel olduğu için okunamadı — bu dönüşüm VİOP genelgesindeki Fk
(kapanış) tanımını kullanır.

Sınırlar: hacim/adet dönüştürülmez; rüçhan hakkı değeri, 1 TL ek ödeme veya rüçhan satışı modellenmez;
türetilmiş seri yatırımcının gerçekleşmiş getirisi DEĞİLDİR.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.market_data.trading_calendar import expected_trading_sessions

SERIES_KIND = "RESEARCH_RIGHTS_ADJUSTED_NOT_OFFICIAL"
PRICE_FIELDS = ("open", "high", "low", "close")


class AdjustmentError(ValueError):
    pass


@dataclass(frozen=True)
class RightsEvent:
    symbol: str
    rights_start: date
    n2: Decimal          # oran (ör. %300 -> 3)
    subscription_price: Decimal  # R
    source: str


def theoretical_price(fk: Decimal, n2: Decimal, r: Decimal) -> tuple[Decimal, bool]:
    """(Ft, rüçhan hesaba dahil mi). Fk < R ise rüçhan hesaba katılmaz (Ft = Fk), bkz. spot genelge 5.1(c)
    ve endeks kural seti 5.2(b)(ii) — bu durumda DK = 1."""
    if fk <= 0 or n2 < 0 or r < 0:
        raise AdjustmentError("Fk > 0, n2 >= 0, R >= 0 olmalı")
    if fk < r:
        return fk, False
    return (fk + n2 * r) / (1 + n2), True


def adjust_rows(rows: list[dict], event: RightsEvent) -> dict:
    """rows: resmî ham CSV satırları (metin değerleri). Girdi DEĞİŞTİRİLMEZ; yeni satırlar döner."""
    if any("series_kind" in r for r in rows):
        raise AdjustmentError("girdi zaten türetilmiş bir seri (çift düzeltme engellendi)")
    if len({r["trade_date"] for r in rows}) != len(rows):
        raise AdjustmentError("tarih tekrarı")
    ordered = sorted(rows, key=lambda r: r["trade_date"])
    before = [r for r in ordered if date.fromisoformat(r["trade_date"]) < event.rights_start]
    if not before:
        raise AdjustmentError("hak kullanımından önceki seans yok")
    fk_row = before[-1]
    fk_day = date.fromisoformat(fk_row["trade_date"])
    sessions = expected_trading_sessions(fk_day, event.rights_start)
    if sessions != [fk_day, event.rights_start]:
        raise AdjustmentError("Fk satırı hak kullanımından hemen önceki beklenen seans değil (eksik seans)")
    fk = Decimal(fk_row["close"])
    ft, rights_included = theoretical_price(fk, event.n2, event.subscription_price)
    dk = ft / fk
    out = []
    for r in ordered:
        pre = date.fromisoformat(r["trade_date"]) < event.rights_start
        factor = dk if pre else Decimal(1)
        new = {"trade_date": r["trade_date"], "series_kind": SERIES_KIND,
               "segment": "PRE_RIGHTS_ADJUSTED" if pre else "RIGHTS_START_OR_AFTER_RAW",
               "factor_applied": str(factor)}
        for f in PRICE_FIELDS:
            new[f"raw_{f}"] = r[f]
            new[f"derived_{f}"] = str(Decimal(r[f]) * factor)
        new["total_traded_quantity_raw"] = r["total_traded_quantity_raw"]  # kaynak anlamıyla, dönüştürülmedi
        out.append(new)
    return {"rows": out, "fk_session": fk_row["trade_date"], "fk": str(fk), "ft": str(ft),
            "ft_rounded_2dp": str(ft.quantize(Decimal("0.01"))), "dk": str(dk), "rights_included": rights_included,
            "rights_start": event.rights_start.isoformat(), "n2": str(event.n2), "R": str(event.subscription_price)}


def ohlc_consistent(row: dict, prefix: str) -> bool:
    o, h, l, c = (Decimal(row[f"{prefix}{f}"]) for f in PRICE_FIELDS)
    return l <= o <= h and l <= c <= h and min(o, h, l, c) > 0


# ---------------------------------------------------------------------------------------------
# Değerlendirme tarihine (as_of_session) göre fiyat görünümü
# ---------------------------------------------------------------------------------------------

def price_view_as_of(rows: list[dict], events: list[RightsEvent], as_of_session: date,
                     event_knowledge: dict[str, str] | None = None) -> dict:
    """Saf, ağsız tarih kesiti.
    * T'den sonraki satırlar çıktıya girmez ve hiçbir hesapta okunmaz (girdi önce T'ye kırpılır).
    * rights_start > T olan olaylar uygulanmaz ve çıktıda yer almaz.
    * rights_start <= T olan olaylar, yalnızca T'ye kadarki kapanışlarla (Fk = hak kullanımından hemen
      önceki seans) mevcut `adjust_rows` ile hesaplanır; birden çok olayda katsayılar çarpılır.
    * Hacim/adet dönüştürülmez; lot/nakit/rüçhan muhasebesi yapılmaz.
    Bu görünüm analiz için tarih kesitidir; türetilmiş fiyatı gelecekteki emir gerçekleşme fiyatına aktarma
    yetkisi vermez. Girdiler bugün edinilmiş verilerdir; 'o gün elimizde bulunan veri arşivi' DEĞİLDİR."""
    if any("series_kind" in r for r in rows):
        raise AdjustmentError("girdi zaten türetilmiş bir seri (çift düzeltme engellendi)")
    iso = as_of_session.isoformat()
    visible = sorted((r for r in rows if r["trade_date"] <= iso), key=lambda r: r["trade_date"])
    if not visible:
        raise AdjustmentError("T'ye kadar satır yok")
    applied = []
    factors = {r["trade_date"]: Decimal(1) for r in visible}
    for ev in sorted((e for e in events if e.rights_start <= as_of_session), key=lambda e: e.rights_start):
        res = adjust_rows(visible, ev)
        dk = Decimal(res["dk"])
        for r in visible:
            if date.fromisoformat(r["trade_date"]) < ev.rights_start:
                factors[r["trade_date"]] *= dk
        applied.append({"symbol": ev.symbol, "rights_start": res["rights_start"], "fk_session": res["fk_session"],
                        "fk": res["fk"], "ft": res["ft"], "dk": res["dk"], "rights_included": res["rights_included"],
                        "source": ev.source,
                        "knowledge_at_as_of": (event_knowledge or {}).get(ev.source,
                                               "DOĞRULANMADI: olayın T tarihinde duyurulmuş/erişilebilir olduğu bu girdilerle kanıtlanmadı")})
    out_rows = []
    for r in visible:
        f = factors[r["trade_date"]]
        row = {"trade_date": r["trade_date"], "factor_applied": str(f)}
        for p in PRICE_FIELDS:
            row[f"raw_{p}"] = r[p]
            row[f"derived_{p}"] = str(Decimal(r[p]) * f)
        row["total_traded_quantity_raw"] = r["total_traded_quantity_raw"]
        out_rows.append(row)
    return {"as_of_session": iso, "series_kind": SERIES_KIND, "rows": out_rows, "applied_events": applied,
            "notes": ["T sonrası satırlar ve T sonrası yürürlüğe giren olaylar kullanılmadı.",
                      "Girdiler bugün edinilen resmî bülten ve KAP kanıtlarıdır; tarihsel erişilebilirlik ayrıca doğrulanmadı.",
                      "Türetilmiş fiyat emir gerçekleşme fiyatı değildir; hacim ve rüçhan/nakit muhasebesi yoktur."]}
