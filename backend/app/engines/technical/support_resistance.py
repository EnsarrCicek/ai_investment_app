"""Destek/Direnç bölgeleri — swing point'lerden ATR-normalize edilmiş zone'lar
(TECHNICAL_ANALYSIS_RESEARCH1.md — rapor madde 7, adım 4).

Vurgulanan ilke: S/R tek bir çizgi değil, ATR'ye göre normalize edilmiş bir
"bölge"dir — fiyatın birebir aynı seviyeye denk gelmesini beklemek gerçekçi
değildir; bunun yerine birbirine yakın (ATR'nin bir katı kadar) swing
point'ler aynı bölgede kümelenir. `touch_count`, bölge cluster'ındaki swing
pivot SAYISIDIR (formation pivotu dahil) — fiyatın seviyeyi bağımsız olarak
kaç kez test ettiğinin ölçümü DEĞİLDİR ve tek başına "daha güçlü" anlamına
GELMEZ (HATA 11N audit'i, 07.09.2026: bu ilişki yöne bağlı ve zone genişliği
ile confounded bulundu — bkz. TEKNIK_ANALIZ_METODOLOJISI.md §3.3).

Girdi olarak market_structure.find_swing_points()'in ürettiği SwingPoint
listesini alır — bu modül kendi başına swing tespiti yapmaz (tek sorumluluk).
Henüz TechnicalAnalysisEngine'e bağlanmadı (bkz. o modülün docstring'i).
"""

from dataclasses import dataclass

from app.engines.technical.market_structure import SwingPoint, SwingType


@dataclass
class SRZone:
    type: str  # "SUPPORT" veya "RESISTANCE"
    low: float
    high: float
    touch_count: int
    last_touch_index: int

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


def build_zones(points: list[SwingPoint], atr: float, zone_width_atr: float = 0.5) -> list[SRZone]:
    """Swing low'ları SUPPORT, swing high'ları RESISTANCE adayı olarak kümeler.

    Kümeleme: aynı tipteki swing point'ler fiyata göre sıralanır, ardışık iki
    point arasındaki fark `zone_width_atr * atr`'den büyükse yeni bir zone
    başlatılır (tek-geçişli/greedy kümeleme — mükemmel k-means/DBSCAN değil,
    ama deterministik ve hızlı; `zone_width_atr` backtest ile kalibre
    edilebilir bir parametredir, evrensel bir sabit değil).
    """
    if atr <= 0:
        return []

    zones: list[SRZone] = []
    for swing_type, zone_type in ((SwingType.LOW, "SUPPORT"), (SwingType.HIGH, "RESISTANCE")):
        same_type = sorted((p for p in points if p.type == swing_type), key=lambda p: p.price)
        cluster: list[SwingPoint] = []
        for p in same_type:
            if cluster and (p.price - cluster[-1].price) > zone_width_atr * atr:
                zones.append(_zone_from_cluster(cluster, zone_type))
                cluster = []
            cluster.append(p)
        if cluster:
            zones.append(_zone_from_cluster(cluster, zone_type))

    zones.sort(key=lambda z: z.mid)
    return zones


def _zone_from_cluster(cluster: list[SwingPoint], zone_type: str) -> SRZone:
    prices = [p.price for p in cluster]
    return SRZone(
        type=zone_type,
        low=min(prices),
        high=max(prices),
        touch_count=len(cluster),
        last_touch_index=max(p.index for p in cluster),
    )


def is_display_role_invalid(zone: SRZone, price: float) -> bool:
    """HATA 11J: fiyat (son tamamlanmış günlük kapanış) zone'un KENDİ mevcut
    sınırının (low/high) yanlış tarafındaysa True — yani zone artık kendi
    orijinal rolünü (destek/direnç) tutarlı biçimde yansıtmıyor. Yalnızca
    MEVCUT geometri: tarihsel breakout event'i, lineage, ATR toleransı veya
    canlı/intraday fiyat KULLANILMAZ (bkz. HATA 11D-11I audit serisi — bu tam
    olarak o serinin önerdiği minimum, geometry-only kural). Fiyat zone
    bandının İÇİNDEYSE veya tam sınırdaysa (>=/<=) geçersiz SAYILMAZ.
    """
    if zone.type == "SUPPORT":
        return price < zone.low
    return price > zone.high


def nearest_zone(
    zones: list[SRZone], price: float, zone_type: str | None = None, active_only: bool = False
) -> SRZone | None:
    """Verilen fiyata (mid'e göre) en yakın zone'u döner; opsiyonel olarak
    tipe göre filtreler. `active_only=True` (HATA 11J), `is_display_role_
    invalid()` ile mevcut fiyatın yanlış tarafında kalan zone'ları adaylardan
    ÇIKARIR -- varsayılan `False` mevcut/genel (yapısal-en-yakın) davranışı
    DEĞİŞTİRMEDEN korur (bkz. test_support_resistance.py'nin genel testleri).
    """
    candidates = [z for z in zones if zone_type is None or z.type == zone_type]
    if active_only:
        candidates = [z for z in candidates if not is_display_role_invalid(z, price)]
    if not candidates:
        return None
    return min(candidates, key=lambda z: abs(z.mid - price))
