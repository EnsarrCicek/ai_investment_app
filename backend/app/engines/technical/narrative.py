"""Kural tabanlı (LLM YOK) teknik anlatı — kullanıcı isteği: "grafiklerde nasıl
dirençler var, nasıl çizgiler çizip AL diyorsun, bu direnç var onu kırdı o
yüzden alman lazım yükselecek gibisinden açıkla." support_resistance.py ve
breakout.py ZATEN bu hesaplamayı (zone/kırılım/teyit/retest) yapıyor — bu
modül yalnızca o sayısal sonucu okunabilir bir Türkçe paragrafa çevirir,
hiçbir yeni sinyal ÜRETMEZ.
"""


def _fmt_price(value: float) -> str:
    return f"{value:.2f}"


def _zone_desc(zone: dict, label: str) -> str:
    # HATA 11N/11O (07.09.2026): `touch_count`, bölgeyi oluşturan swing pivot
    # SAYISIDIR (formation pivotu dahil) -- fiyatın bu seviyeyi bağımsız
    # olarak kaç kez "test ettiğinin" ölçümü DEĞİLDİR. Bu yüzden "test
    # edilmiş" yerine yapısal, davranışsal bir iddia taşımayan "N swing
    # pivotinden oluşan" ifadesi kullanılır.
    return (
        f"{_fmt_price(zone['low'])}–{_fmt_price(zone['high'])} TL bandındaki, "
        f"{zone['touch_count']} swing pivotinden oluşan {label}"
    )


def build_narrative(
    nearest_support: dict | None,
    nearest_resistance: dict | None,
    breakout: dict | None,
) -> str:
    if breakout is not None:
        return _breakout_narrative(breakout)
    return _no_breakout_narrative(nearest_support, nearest_resistance)


def _breakout_narrative(breakout: dict) -> str:
    zone = breakout["zone"]
    direction = breakout["direction"]
    confirmed = breakout["confirmed"]
    retest_held = breakout["retest_held"]
    atr_mult = breakout["breakout_atr"]

    zone_label = "direnci" if zone["type"] == "RESISTANCE" else "desteği"
    verb = "yukarı yönlü kırdı" if direction == "BULLISH" else "aşağı yönlü kırdı"

    parts = [f"Fiyat, {_zone_desc(zone, zone_label)} ATR'nin {atr_mult:.2f} katı büyüklüğünde {verb}."]

    if confirmed is True:
        parts.append(
            "Bu kırılım sonraki barlarda teyit edildi — fiyat seviyenin diğer tarafında kalmaya devam etti."
        )
        if retest_held is True:
            role = "destek" if direction == "BULLISH" else "direnç"
            parts.append(
                f"Ayrıca fiyat kırılan seviyeye geri dönüp yeni {role} rolünü test etti ve seviye tutuldu "
                "— bu, kırılımın gücünü doğrulayan ek bir sinyal."
            )
        elif retest_held is False:
            parts.append("Ancak retest sırasında seviye tutulmadı; bu, kırılımın gücü konusunda şüphe yaratıyor.")

        if direction == "BULLISH":
            parts.append(
                "Genel kural: kırılan bir direnç seviyesi genelde yeni bir destek haline gelir — fiyatın bu "
                "seviyenin üzerinde tutunması, yükselişin devam etme ihtimalini artırır."
            )
        else:
            parts.append(
                "Genel kural: kırılan bir destek seviyesi genelde yeni bir direnç haline gelir — fiyatın bu "
                "seviyenin altında kalması, düşüşün devam etme ihtimalini artırır."
            )
    elif confirmed is False:
        parts.append(
            "Ne var ki bu kırılım YANLIŞ (false breakout) çıktı — fiyat kısa süre içinde eski bölgenin içine "
            "geri döndü, bu yüzden bu kırılıma güvenilmemeli."
        )
    else:
        parts.append(
            "Bu kırılımın gerçek mi yoksa yanlış (false breakout) mi olduğu henüz teyit edilmedi — birkaç "
            "gün daha fiyatın seviyenin diğer tarafında kalıp kalmadığına bakmak gerekiyor."
        )

    return " ".join(parts)


def _no_breakout_narrative(nearest_support: dict | None, nearest_resistance: dict | None) -> str:
    parts: list[str] = []
    if nearest_resistance is not None:
        parts.append(
            f"Üstte en yakın {_zone_desc(nearest_resistance, 'direnç')} bulunuyor — fiyat buraya yaklaşırsa "
            "satış baskısı görülebilir."
        )
    if nearest_support is not None:
        parts.append(
            f"Altta en yakın {_zone_desc(nearest_support, 'destek')} bulunuyor — fiyat buraya gerilerse alım "
            "ilgisi görülebilir."
        )
    if not parts:
        return "Şu an belirgin bir destek/direnç bölgesi tespit edilemedi (yeterli swing noktası yok)."
    return " ".join(parts)
