"""Cross-source event-level deduplication — HATA 15B.

HATA 15A denetimi şunu doğruladı: `NewsRawItem.external_id` yalnızca
sağlayıcıya özel bir MAKALE kimliğidir (Firestore doküman-ID dedup'ı için).
Aynı gerçek-dünya olayı Yahoo/Google/Foreks'ten AYRI `external_id`'lerle
gelebiliyor ve hiçbir yerde birleştirilmiyordu (`news_raw_repository.py`
docstring'i bunu zaten kabul ediyordu) — bu da EventIntelligenceEngine'in
son-10 skorlama penceresinde tek bir olayın birden çok slot işgal edip
haber skorunu orantısız etkilemesine yol açıyordu (HATA 15A bulgu #2).

Bilinçli olarak İKİ AYRI kavram tutuluyor (karıştırılmıyor):

  1. Makale kimliği (`external_id` / `news_id`) — DEĞİŞMEDİ, ham veri
     provenance/idempotency için hâlâ tek kaynak.
  2. Mantıksal olay kümesi ("event cluster") — bu modülün ürettiği, HER
     ÇAĞRIDA YENİDEN HESAPLANAN (kalıcı/persist edilmeyen), asset-sınırlı,
     zaman-penceresi-sınırlı, deterministik bir kümeleme. Girdi sırasından
     (fetch order / Firestore iterasyon sırası) bağımsızdır çünkü kümeleme
     ÖNCE (published_at, event_id) ile deterministik sıralanmış girdi
     üzerinde çalışır.

Kasıtlı olarak kalıcı/tekil bir "event_id" ÜRETİLMİYOR (bkz. HATA 15A
bölüm 14 / HATA 15B bölüm 14): Jaccard benzerliği geçişli (transitive)
DEĞİLDİR — A~B ve B~C yakın-tekrar olsa da A~C olmayabilir; yeni bir
yakın-tekrar makale geldiğinde önceki kümelenme kompozisyonu teorik olarak
değişebilir. Bu modül bunu ÖRTMÜYOR: kümeleme her çağrıda mevcut girdi
kümesi üzerinden deterministik olarak yeniden hesaplanır ve bu, "kalıcı
event_id" iddiası yerine dürüst bir tasarım tercihi olarak belgeleniyor.

Dil sınırlaması: bu, yerel/deterministik bir token-Jaccard algoritmasıdır
(embedding/LLM çağrısı YOK — ticket kapsamı dışı). Aynı olayın FARKLI
DİLLERDE (ör. İngilizce Yahoo başlığı vs Türkçe Foreks başlığı) yazılmış
başlıkları birbirine ASLA eşleşmez — bu bilinen, belgelenmiş bir sınırdır,
gizlenmiyor.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Generic, TypeVar

# Unicode "word" karakteri (harf/rakam, alttire hariç) — Türkçe karakterler
# (ç,ğ,ı,ö,ş,ü ve â/î/û gibi düzeltme işaretli sesli harfler) dahil, elle
# sağlayıcı bazlı bir karakter kümesi listelemek yerine \w (UNICODE) tabanlı
# genel bir yaklaşım kullanılıyor — Foreks'teki eski dar regex'ten (yalnızca
# ASCII+çğıöşü) daha genel ve daha az kırılgan.
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Foreks'in mevcut intra-batch eşiği (bkz. foreks_news_provider.py) başlangıç
# noktası olarak kullanıldı. Cross-provider testlerle (negation/quarter/year
# ayrımı + gerçek near-duplicate örnekleri) YENİDEN doğrulandı, körlemesine
# global kopyalanmadı (bkz. test_event_dedup.py) — aynı eşiğin cross-provider
# durumda da doğru ayrıştığı kanıtlandı.
NEAR_DUPLICATE_THRESHOLD = 0.82

# Sağlayıcılar arası aynı olayın yeniden yayınlanma penceresi. Günlük analiz
# job'ı günde bir kez çalışıyor (AŞAMA 70) ve haber sağlayıcıları (Yahoo/
# Google/Foreks) aynı gerçek-dünya olayını genelde saatler içinde, en kötü
# ihtimalle ertesi gün yeniden yayınlıyor (canlı gözlem — bkz. HATA 15A
# denetimi, "Active news/event sources" bölümü). 48 saat: aynı günün akşamı
# veya ertesi gün tekrar yayınlanan kaynakları yakalarken, haftalar/aylar
# sonra benzer başlıklı AYRI bir olayı (ör. bir sonraki çeyrek kâr açıklaması,
# bkz. bölüm 29/31 testleri) yanlışlıkla birleştirmeyi önlüyor. Bu, gerçek
# haber sıklığına dayanan BİLİNÇLİ bir seçim — sessizce varsayılmadı.
DEDUP_WINDOW = timedelta(hours=48)


def normalize_title(title: str) -> str:
    """Deterministik başlık normalizasyonu.

    Unicode NFKC + casefold + noktalama temizleme + boşluk sıkıştırma.
    Finansal anlamı olan RAKAMLAR (çeyrek/yıl/tutar/yüzde) BİLİNÇLİ olarak
    korunuyor — aksi halde "2025 kâr" ile "2026 kâr" yanlışlıkla
    çakışabilirdi (bkz. HATA 15B bölüm 6/30 testleri).
    """
    text = unicodedata.normalize("NFKC", title or "").casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def title_tokens(title: str) -> set[str]:
    return set(_WORD_RE.findall(normalize_title(title)))


def jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    union = len(tokens_a | tokens_b)
    if union == 0:
        return 0.0
    return len(tokens_a & tokens_b) / union


def is_near_duplicate_title(
    title_a: str, title_b: str, threshold: float = NEAR_DUPLICATE_THRESHOLD
) -> bool:
    """Jaccard >= threshold — Jaccard==1.0 (tam normalize eşitlik) da bu
    tanımın bir alt kümesi, ayrı bir "exact duplicate" yolu YOK (bölüm 10
    testleri bunun aynı mekanizmadan geçtiğini doğruluyor)."""
    return jaccard_similarity(title_tokens(title_a), title_tokens(title_b)) >= threshold


T = TypeVar("T")


@dataclass(frozen=True)
class DedupEntry(Generic[T]):
    """Kümeleme girdisi. `event_id` = makale kimliği (external_id/news_id) —
    kümeleme SIRASI için deterministik tie-break amaçlı kullanılır, kümeleme
    KARARI için değil (o başlık+zaman+asset ile verilir)."""

    asset: str
    event_id: str
    title: str
    published_at: datetime
    has_body: bool
    payload: T


@dataclass
class EventCluster(Generic[T]):
    entries: list[DedupEntry[T]] = field(default_factory=list)

    @property
    def representative(self) -> DedupEntry[T]:
        """Deterministik temsilci seçimi (bölüm 13): gövde/özet verisi olan
        önce, sonra en eski yayın zamanı, sonra event_id tie-break — girdi
        sırasından (fetch order) TAMAMEN bağımsız, çünkü hepsi kümeye ait
        entry'lerin İÇSEL alanlarına dayanıyor."""
        return sorted(
            self.entries,
            key=lambda e: (not e.has_body, e.published_at, e.event_id),
        )[0]


def cluster_by_event(
    entries: list[DedupEntry[T]],
    *,
    window: timedelta = DEDUP_WINDOW,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> list[EventCluster[T]]:
    """Deterministik, fetch-order-bağımsız kümeleme.

    Bir entry, mevcut bir kümeye KATILIR ancak ve ancak:
      - aynı `asset` (bölüm 8 — farklı varlıklar ASLA birleşmez),
      - kümenin ilk (en eski) üyesine göre `published_at` farkı <= window
        (bölüm 9/31 — sınırlı zaman penceresi, sınır DAHİL),
      - kümedeki EN AZ BİR üyeyle başlık near-duplicate (bölüm 10/11).

    İşlem sırası (published_at, event_id) ile sabitlenir — bu yüzden kümeleme
    SONUCU girdi listesinin orijinal sırasından bağımsızdır (bölüm 27/14).
    """
    ordered = sorted(entries, key=lambda e: (e.published_at, e.event_id))
    clusters: list[EventCluster[T]] = []
    for entry in ordered:
        target: EventCluster[T] | None = None
        for cluster in clusters:
            anchor = cluster.entries[0]
            if anchor.asset != entry.asset:
                continue
            if abs(entry.published_at - anchor.published_at) > window:
                continue
            if any(
                is_near_duplicate_title(entry.title, member.title, threshold)
                for member in cluster.entries
            ):
                target = cluster
                break
        if target is not None:
            target.entries.append(entry)
        else:
            clusters.append(EventCluster(entries=[entry]))
    return clusters


def select_non_representatives(cluster: EventCluster[T]) -> list[DedupEntry[T]]:
    rep = cluster.representative
    return [e for e in cluster.entries if e.event_id != rep.event_id]
