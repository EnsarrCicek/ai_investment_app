"""BSOKE/FENER tarih kesiti örnekleri + güncellenmiş yöntem notu (ağsız; önceki çıktılar korunur).

Kullanım (backend dizininden): python -m app.research.official_bist.build_as_of_views <çıktı_klasörü>
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from app.research.official_bist.rights_adjustment import RightsEvent, price_view_as_of, theoretical_price

BACKEND = Path(__file__).resolve().parents[3]
RAW = BACKEND / "app/research/official_bist/runs/bsoke_fener_20260929_v2"
SRC = BACKEND / "app/research/official_bist/runs/rights_adjustment_20260929/sources"
KNOWLEDGE = {  # yalnızca KAP gönderim zamanı; verinin o gün bizde bulunduğu anlamına GELMEZ
    "https://www.kap.org.tr/tr/Bildirim/1363968": "KAP gönderim 2024-12-09 12:58:56 (güncelleme bildirimi; hak kullanımından önce). Yayım zamanıdır, yerel arşivin o gün var olduğunu göstermez.",
    "https://www.kap.org.tr/tr/Bildirim/1452776": "KAP gönderim 2025-06-27 16:22:03 (hak kullanımından önceki son seansta, 16:30 öncesi). Yayım zamanıdır, yerel arşivin o gün var olduğunu göstermez.",
}
AS_OF = {"BSOKE": ["2024-12-09", "2024-12-10"], "FENER": ["2025-06-27", "2025-06-30"]}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(out: Path) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    ca = {r["symbol"]: r for r in csv.DictReader((RAW / "corporate_actions.csv").open(encoding="utf-8"))}
    views, table = {}, []
    for sym, dates in AS_OF.items():
        rows = list(csv.DictReader((RAW / f"{sym}_official_daily.csv").open(encoding="utf-8")))
        e = ca[sym]
        ev = RightsEvent(sym, date.fromisoformat(e["rights_start"]), Decimal(e["ratio_pct"]) / 100, Decimal(e["subscription_price_try"]), e["kap"])
        for d in dates:
            v = price_view_as_of(rows, [ev], date.fromisoformat(d), KNOWLEDGE)
            views[f"{sym}@{d}"] = v
            last_pre = next(r for r in v["rows"] if r["trade_date"] == dates[0])
            table.append({"symbol": sym, "as_of": d, "rows_in_view": len(v["rows"]), "last_row": v["rows"][-1]["trade_date"],
                          "applied_events": [a["rights_start"] for a in v["applied_events"]],
                          "dk": v["applied_events"][0]["dk"][:10] if v["applied_events"] else "1 (olay uygulanmadı)",
                          f"{dates[0]}_raw_close": last_pre["raw_close"],
                          f"{dates[0]}_derived_close": str(Decimal(last_pre["derived_close"]).quantize(Decimal("0.0001"))),
                          "scale_raw_over_derived": str((Decimal(last_pre["raw_close"]) / Decimal(last_pre["derived_close"])).quantize(Decimal("0.000001")))})
    (out / "as_of_views.json").write_text(json.dumps(views, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "as_of_table.json").write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")

    # Güncellenmiş yöntem notu (önceki method.json DEĞİŞTİRİLMEDİ)
    comparisons = {}
    for sym, fk, n2 in (("BSOKE", Decimal("61.65"), Decimal(3)), ("FENER", Decimal("48.52"), Decimal(4))):
        ft, _ = theoretical_price(fk, n2, Decimal("1.00"))
        comparisons[sym] = {"Fk": str(fk), "n1": "0", "n2": str(n2), "T": "0", "R": "1.00",
                            "Ft_research_unrounded": str(ft),
                            "Ft_official_precision_3dp_half_up": str(ft.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
                            "DK_research_unrounded": str(ft / fk)}
    note = {
        "supersedes_statement": "Önceki method.json'daki '2015/116 prosedürüne erişilemedi' bilgisi güncellendi: belge doğrudan adresten erişildi.",
        "source": {"url": "https://www.borsaistanbul.com/data/Genelge/2015-116.pdf", "sha256": sha(SRC / "2015-116.pdf"),
                   "access_log": str((SRC / "access_log.tsv").relative_to(BACKEND)),
                   "read_method": "Metin katmanı yok (taranmış); sayfa görüntüleri (FlateDecode+DCT) çıkarılıp görsel olarak okundu: 2015-116_p1..p5.jpg",
                   "document": "Borsa İstanbul Duyuru 2015/116, onay 24.11.2015, 'Özsermaye Hallerinde Payların Teorik/Referans Fiyatlarının Belirlenmesi'; "
                               "BISTECH Yeni Pay Alım Satım Sistemi'nin devreye gireceği tarihte geçerli; 04.01.2013 tarihli 415 sayılı Genelge'yi iptal eder."},
        "verified_content": {
            "5.1_formula": "Ft = (Fk + n2·R − T) / (1 + n1 + n2);  Fr = [Ft − R] × n2  (belge içi 3/4, PDF fiziksel s.4)",
            "2.5_definitions": "Ft teorik fiyat; Fr rüçhan referans fiyatı; Fk özsermaye hali öncesi SON KAPANIŞ fiyatı; n1 bedelsiz oran; n2 rüçhan oranı; T brüt temettü; R 1 TL nominal payın rüçhan kullanma fiyatı",
            "5.1_exception": "Payın 'haklar üzerinde' son kapanışı R'nin altındaysa veya temettü/bedelsiz sonrası teorik fiyat R'nin altına düşüyorsa n2 = 0 alınır",
            "2.6_precision": "Ft, Fr, Fk: 3 hane; n1, n2, T: 7 hane; R: 2 hane",
            "2.2_reference_price": "Referans fiyat fiyat limitlerine esas teşkil etmez (tanım)"},
        "comparison_with_existing": {"same_formula_for_bedelli": True,
                                     "note": "Mevcut hesap n1 = 0, T = 0 ile aynı formülü ve aynı Fk (son kapanış) tanımını kullanıyor; hesaplar DEĞİŞTİRİLMEDİ. "
                                             "2012/2013 genelgesindeki ağırlıklı ortalama (Fa) tanımı 2015/116 ile iptal edilen metne aittir.",
                                     "events": comparisons,
                                     "precision_note": "Resmî hassasiyet Ft için 3 hanedir (yuvarlama yönü belgede belirtilmedi; burada yalnızca gösterim için half-up). "
                                                       "Araştırma dönüşümü yuvarlanmamış DK kullanır; baz fiyat ayrıca fiyat adımına yuvarlanır ve bu dönüşümde kullanılmaz."},
        "scope_limits": ["Bu belgenin bulunması sonraki tüm değişikliklerin kontrol edildiği anlamına gelmez.",
                         "Geçmiş OHLC dönüşümü araştırma dönüşümüdür; BIST'in resmî düzeltilmiş serisi değildir."],
        "corrected_claim": ("Önceki 'Yahoo doğru katsayıyı yanlış uyguladı' ifadesi düzeltildi: kayıtlı Yahoo serisinde, resmî formülle aynı katsayıya eşit "
                            "bir ölçek deseninin yalnızca kırılma başlangıcından hak kullanımına kadar bulunduğu gösterildi; sağlayıcının bunu hangi "
                            "işlemle oluşturduğu kanıtlanmadı."),
        "outputs": {"as_of_views": "as_of_views.json", "as_of_table": "as_of_table.json"},
    }
    (out / "method_update.json").write_text(json.dumps(note, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"table": table, "comparison": comparisons}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
