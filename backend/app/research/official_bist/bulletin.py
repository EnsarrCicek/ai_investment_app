"""Borsa İstanbul Pay Piyasası günlük bülteni (thbYYYYMMDD1.zip) ayrıştırıcısı — yerel araştırma.

Kapsam: işlem günündeki RESMÎ fiyatların kaydı. Kurumsal işlem boyunca karşılaştırılabilir teknik
analiz serisi veya rüçhan/ek ödeme dahil ekonomik getiri DEĞİLDİR. Hiçbir değer düzeltilmez,
doldurulmaz veya taşınmaz.

Eşleme bültenin kendi iki satırlık başlığından yapılır (Türkçe + İngilizce birlikte doğrulanır);
sütun konumuna güvenilmez. Kaynak metin değerleri korunur.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# çıktı alanı -> (Türkçe başlık, İngilizce başlık); boşluklar normalize edilerek karşılaştırılır
FIELDS = {
    "trade_date": ("TARIH", "TRADE DATE"),
    "instrument_code": ("ISLEM KODU", "INSTRUMENT SERIES CODE"),
    "instrument_name": ("BULTEN ADI", "INSTRUMENT NAME"),
    "open": ("ACILIS FIYATI", "OPENING PRICE"),
    "high": ("EN YUKSEK FIYAT", "HIGHEST PRICE"),
    "low": ("EN DUSUK FIYAT", "LOWEST PRICE"),
    "close": ("KAPANIS FIYATI", "CLOSING PRICE"),
    "previous_last_price": ("ONCEKI KAPANIS FIYATI", "PREVIOUS LAST PRICE"),
    "total_traded_value_raw": ("TOPLAM ISLEM HACMI", "TOTAL TRADED VALUE"),
    "total_traded_quantity_raw": ("TOPLAM ISLEM ADEDI", "TOTAL TRADED VOLUME"),
}
NUMERIC = ("open", "high", "low", "close", "previous_last_price", "total_traded_value_raw", "total_traded_quantity_raw")


class BulletinError(ValueError):
    pass


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lstrip("﻿")).upper()


def parse_number(text: str | None) -> Decimal | None:
    """Kaynak sayı metni -> Decimal. Boş -> None (uydurulmaz).
    '290.75' / '6095182799.25' (nokta ondalık); '290,75' (virgül ondalık);
    '1.234,56' (nokta binlik + virgül ondalık); '1,234.56' (virgül binlik + nokta ondalık).
    Belirsiz biçim (ör. '1.234' veya '1,234' tek ayırıcılı binlik) nokta/virgül ondalık kabul edilir ve
    tek ayırıcı durumu çağırana `ambiguous` olarak bildirilmez; bu bültende binlik ayırıcı gözlenmedi."""
    if text is None:
        return None
    s = text.strip()
    if s == "":
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise BulletinError(f"sayı ayrıştırılamadı: {text!r}") from exc
    if not value.is_finite():
        raise BulletinError(f"sonlu olmayan sayı: {text!r}")
    return value


@dataclass(frozen=True)
class ParsedRow:
    fields: dict            # çıktı alanı -> Decimal | str | None
    raw: dict               # çıktı alanı -> kaynak metin
    missing_fields: tuple   # kaynakta boş/eksik olanlar


def header_map(tr_header: list[str], en_header: list[str]) -> dict[str, int]:
    tr = [_norm(h) for h in tr_header]
    en = [_norm(h) for h in en_header]
    out = {}
    for field, (tr_name, en_name) in FIELDS.items():
        idx = [i for i in range(min(len(tr), len(en))) if tr[i] == tr_name and en[i] == en_name]
        if len(idx) != 1:
            raise BulletinError(f"başlık eşlenemedi: {field} ({tr_name} / {en_name}) -> {len(idx)} eşleşme")
        out[field] = idx[0]
    return out


def parse_bulletin_text(text: str, instrument_code: str, expected_date: str) -> ParsedRow | None:
    """Bülten metninden tek enstrüman satırı. Satır yoksa None. Tarih/kod tekrarı veya
    beklenmeyen tarih -> BulletinError."""
    lines = text.lstrip("﻿").splitlines()
    if len(lines) < 3:
        raise BulletinError("bülten başlık/veri satırı içermiyor")
    hmap = header_map(lines[0].split(";"), lines[1].split(";"))
    matches = []
    dates = set()
    for line in lines[2:]:
        if not line.strip():
            continue
        cells = line.split(";")
        dates.add(cells[hmap["trade_date"]].strip())
        if cells[hmap["instrument_code"]].strip() == instrument_code:
            matches.append(cells)
    if dates != {expected_date}:
        raise BulletinError(f"bülten işlem tarihi beklenenden farklı: {sorted(dates)} != {expected_date}")
    if not matches:
        return None
    if len(matches) > 1:
        raise BulletinError(f"{instrument_code} için {len(matches)} satır (tekrar)")
    cells = matches[0]
    raw = {f: (cells[i] if i < len(cells) else "") for f, i in hmap.items()}
    fields = {}
    for f, v in raw.items():
        fields[f] = parse_number(v) if f in NUMERIC else (v.strip() or None)
    missing = tuple(f for f, v in fields.items() if v is None)
    return ParsedRow(fields=fields, raw=raw, missing_fields=missing)


def read_bulletin_zip(data: bytes) -> tuple[str, str]:
    """(iç dosya adı, UTF-8 metin). Tek dosya beklenir."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        if len(names) != 1:
            raise BulletinError(f"zip içinde {len(names)} dosya")
        return names[0], zf.read(names[0]).decode("utf-8")


def ohlc_issues(fields: dict) -> list[str]:
    o, h, l, c = (fields.get(k) for k in ("open", "high", "low", "close"))
    if None in (o, h, l, c):
        return ["OHLC_MISSING"]
    issues = []
    if not (l <= o <= h):
        issues.append("OPEN_OUTSIDE_LOW_HIGH")
    if not (l <= c <= h):
        issues.append("CLOSE_OUTSIDE_LOW_HIGH")
    if min(o, h, l, c) <= 0:
        issues.append("NON_POSITIVE_PRICE")
    return issues
