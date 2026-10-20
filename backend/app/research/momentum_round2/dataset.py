"""Momentum Round 2 veri kümesi ve zaman tabanlı (walk-forward) bölme.

Round 1 holdout'u (28.09–15.10, 50 varlık) GÖRÜLMÜŞ veridir: Round 2 seçiminde KULLANILMAZ, yalnız "research
feedback" olarak ikincil raporlanır. Yahoo 5 dk verisi ~60 gün tutulduğu için Round 1 holdout'undan sonra yeni seans
yoktur; bu yüzden Round 2'nin dokunulmamış final dilimi HEM zaman HEM varlık olarak yenidir:

* Seçim (walk-forward): Round 1 evreninin 50 varlığı × Round 1 kalibrasyon + doğrulama seansları (30.07–25.09).
* Final dokunulmamış dilim: Round 1'de HİÇ kullanılmamış varlıklar (`UNTOUCHED_ASSETS`) × en son seanslar
  (Round 1 holdout tarihleri). Bu varlıklar seçimde hiçbir aşamada okunmaz.
* KTLEV hiçbir kümede yoktur; yalnız final örnek olaydır.
* Rastgele bölme YOK: tüm katlar geçmiş → gelecek.
"""

from __future__ import annotations

from datetime import date

from app.research.momentum_calibration import dataset as r1

RUNS = r1.RUNS.parent.parent / "momentum_round2" / "runs"
BENCHMARK = "XU100"
HOLDOUT_CASE = r1.HOLDOUT_CASE
REFERENCE_ASSETS = r1.CALIBRATION_ASSETS  # kesitsel (cross-sectional) referans paneli = Round 1 evreni

# Round 1'de kullanılmamış, sektör/likidite çeşitliliği olan BIST payları (önceden sabitlendi; sonuç görülmeden).
# KOZAL, KOZAA, IPEKE listedeydi; Yahoo'da 5 dk verisi olmadığı için (sonuçtan ÖNCE, yalnız veri yokluğu) çıkarıldı.
UNTOUCHED_ASSETS: tuple[str, ...] = (
    "ENKAI", "TAVHL", "TTRAK", "DOAS", "ODAS", "SMRTG", "EUPWR",
    "GESAN", "YEOTK", "KONTR", "OYAKC", "MAVI", "AGHOL", "AKSA", "ALFAS", "BRSAN", "BRYAT",
    "CEMTS", "CLEBI", "ECILC", "EGEEN", "EKGYO", "GENIL", "GWIND", "ISMEN", "KARSN", "KORDS",
    "LOGO", "MPARK", "QUAGR", "SKBNK", "TABGD", "TKFEN", "TURSG", "VESBE", "AYGAZ", "ISGYO",
)

# Dokunulmamış final dilim (37 varlık × 28.09–15.10) 20.10.2026'da dondurulmuş aday a9f943dc… ile TÜKETİLDİ
# (sonuç FAIL). Artık yalnız "research feedback"tir: aday seçimi/eşik/sıralama/model seçimi için KULLANILAMAZ.
CONSUMED_FINAL = True
CONSUMED_FINAL_SHA = "a9f943dcb53c6ade6e2a30658ab547ab3bfe3930d5f5e93c2908db1a67cad881"

N_SELECTION_BLOCKS = 4  # seçim seansları 4 ardışık bloğa bölünür → 3 genişleyen walk-forward katı


def load(symbol: str):
    return r1.load(symbol)


def round1_split() -> dict[str, list[date]]:
    days = sorted(set().union(*(set(r1.complete_sessions(r1.load(s))) for s in REFERENCE_ASSETS)))
    return r1.split_sessions(days)


def selection_and_final(split: dict[str, list[date]] | None = None) -> tuple[list[date], list[date]]:
    """(seçim seansları, final dilim seansları). Final dilim = Round 1 holdout TARİHLERİ (yeni varlıklarla)."""
    split = split or round1_split()
    return split["calibration"] + split["validation"], list(split["holdout"])


def walk_forward_folds(selection_days: list[date], n_blocks: int = N_SELECTION_BLOCKS) -> list[dict]:
    """Genişleyen pencere: kat k → eğitim = blok[0..k], doğrulama = blok[k+1]. Doğrulama her zaman eğitimden sonra."""
    days = sorted(selection_days)
    n = len(days)
    edges = [round(n * j / n_blocks) for j in range(n_blocks + 1)]
    blocks = [days[edges[j]:edges[j + 1]] for j in range(n_blocks)]
    folds = []
    for k in range(1, n_blocks):
        train = [d for b in blocks[:k] for d in b]
        folds.append({"fold": k, "train": train, "validate": blocks[k]})
    return folds
