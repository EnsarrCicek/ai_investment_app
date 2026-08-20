"""Fon önerisi açıklama metni üretimi — AŞAMA 60.

Kullanıcı isteği: "neden almamı önerdiğini belirt." LLM çağrısı YAPILMAZ
(haber duygu analizinin aksine, burada tamamen sayısal/deterministik veriden
şablonla üretilen bir metin yeterli ve daha güvenilir/ucuzdur — hiçbir
"halüsinasyon" riski yok) — getiri rakamları, risk sınıfı ve sıralamadaki
konumu birleştirilip okunabilir bir Türkçe cümleye dönüştürülür.
"""

from app.engines.funds.risk import RISK_LABELS_TR


def _return_phrase(label: str, value: float | None) -> str | None:
    if value is None:
        return None
    return f"{label}: %{value:+.1f}"


def build_explanation(
    return_1m_pct: float | None,
    return_3m_pct: float | None,
    return_6m_pct: float | None,
    return_1y_pct: float | None,
    risk_level: str | None,
    rank: int,
    total_count: int,
) -> str:
    return_parts = [
        p
        for p in (
            _return_phrase("1 ay", return_1m_pct),
            _return_phrase("3 ay", return_3m_pct),
            _return_phrase("6 ay", return_6m_pct),
            _return_phrase("1 yıl", return_1y_pct),
        )
        if p is not None
    ]

    sentences = []
    if return_parts:
        sentences.append(f"Getiri ({', '.join(return_parts)}).")

    sentences.append(f"Analiz edilen {total_count} fon arasında {rank}. sırada.")

    if risk_level is not None:
        risk_label = RISK_LABELS_TR.get(risk_level, risk_level)
        sentences.append(f"Risk seviyesi: {risk_label}.")
    else:
        sentences.append("Risk seviyesi hesaplanamadı (portföy dağılım verisi eksik).")

    return " ".join(sentences)
