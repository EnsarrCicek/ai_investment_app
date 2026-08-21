from app.utils.turkish_text import tr_upper

# AŞAMA 64: kullanıcı isteği "kim demiş, ne demiş, biraz daha detaylı olsun" —
# yfinance'in analist konsensüsü (engines/analysts/consensus.py) SAYIYI verir
# ama İSİM vermez; BIST için `upgrades_downgrades` de veri döndürmüyor (bkz.
# AŞAMA 63). Gerçek haber başlıkları ise sık sık bankanın/aracı kurumun adını
# doğrudan içeriyor (ör. "HSBC: favori THYAO..."). Bu yüzden İSİM UYDURMAK
# yerine, bilinen banka/aracı kurum adlarının GERÇEK başlık/özet metninde
# GEÇTİĞİ durumları deterministik biçimde tespit ediyoruz — bulunamazsa None
# döner, hiçbir şey icat edilmez.
KNOWN_ANALYST_FIRMS = [
    "İş Yatırım",
    "Ak Yatırım",
    "Yapı Kredi Yatırım",
    "Garanti BBVA Yatırım",
    "QNB Finans Yatırım",
    "Deniz Yatırım",
    "Tacirler Yatırım",
    "Gedik Yatırım",
    "Ünlü & Co",
    "Oyak Yatırım",
    "Vakıf Yatırım",
    "Halk Yatırım",
    "Şeker Yatırım",
    "Global Menkul",
    "Integral Yatırım",
    "A1 Capital",
    "Marbaş Menkul",
    "Ata Yatırım",
    "Info Yatırım",
    "Vera Capital",
    "Bulls Menkul",
    "Phillip Capital",
    "Piramit Menkul",
    "Ziraat Yatırım",
    "HSBC",
    "JPMorgan",
    "JP Morgan",
    "Goldman Sachs",
    "Morgan Stanley",
    "Citi",
    "UBS",
    "Bank of America",
    "BofA",
    "Deutsche Bank",
    "Barclays",
    "Credit Suisse",
    "Renaissance Capital",
    "Wood & Company",
]

_KNOWN_FIRMS_UPPER = [(firm, tr_upper(firm)) for firm in KNOWN_ANALYST_FIRMS]


def extract_analyst_firm(text: str) -> str | None:
    haystack = tr_upper(text)
    for original, upper in _KNOWN_FIRMS_UPPER:
        if upper in haystack:
            return original
    return None
