"""BIST100 (XU100) endeksinin tamamını Firestore assets koleksiyonuna ekler.

Sembol listesi getmidas.com'dan (18.08.2026) alındı, şirket isimleri Yahoo
Finance'in (yfinance) kendi verisinden (ticker.info) çekildi. Eklemeden önce
100 sembolün TAMAMI gerçek yfinance geçmiş veri çağrısıyla doğrulandı — hiçbiri
uydurma değil (ana doküman kural 11-12).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.asset import Asset
from app.repositories.asset_repository import AssetRepository

# symbol -> şirket adı (yfinance ticker.info'dan)
BIST100 = {
    "AEFES": "Anadolu Efes Biracilik ve Malt Sanayii Anonim Sirketi",
    "AKBNK": "Akbank T.A.S.",
    "AKSA": "Aksa Akrilik Kimya Sanayii A.S.",
    "AKSEN": "Aksa Enerji Üretim A.S.",
    "ALARK": "Alarko Holding A.S.",
    "ALTNY": "ALTINAY SAVUNMA",
    "ANSGR": "Anadolu Anonim Türk Sigorta Sirketi",
    "ARCLK": "Arçelik Anonim Sirketi",
    "ASELS": "ASELSAN Elektronik Sanayi ve Ticaret Anonim Sirketi",
    "ASTOR": "Astor Enerji A.S.",
    "BALSU": "BALSU GIDA",
    "BERA": "Bera Holding A.S.",
    "BIMAS": "BIM Birlesik Magazalar A.S.",
    "BRSAN": "Borusan Birlesik Boru Fabrikalari Sanayi ve Ticaret A.S.",
    "BRYAT": "Borusan Yatirim ve Pazarlama A.S.",
    "BSOKE": "Batisöke Söke Çimento Sanayii T.A.S.",
    "BTCIM": "Batiçim Bati Anadolu Çimento Sanayii Anonim Sirketi",
    "CANTE": "Çan2 Termik A.S.",
    "CCOLA": "Coca-Cola Içecek Anonim Sirketi",
    "CIMSA": "Çimsa Çimento Sanayi ve Ticaret A.S.",
    "CVKMD": "CVK Maden Isletmeleri Sanayi ve Ticaret Anonim Sirketi",
    "CWENE": "CW Enerji Mühendislik Ticaret ve Sanayi Anonim Sirketi",
    "DAPGM": "DAP Gayrimenkul Gelistirme A.S.",
    "DOAS": "Dogus Otomotiv Servis ve Ticaret A.S.",
    "DOHOL": "Dogan Sirketler Grubu Holding A.S.",
    "DSTKF": "DESTEK FINANS FAKTORING",
    "ECILC": "EIS Eczacibasi Ilaç, Sinai ve Finansal Yatirimlar Sanayi ve Ticaret A.S.",
    "EFOR": "Efor Yatirim Sanayi Ticaret Anonim Sirketi",
    "EKGYO": "Emlak Konut Gayrimenkul Yatirim Ortakligi A.S.",
    "ENERY": "Enerya Enerji Anonim Sirketi",
    "ENJSA": "Enerjisa Enerji A.S.",
    "ENKAI": "Enka Insaat ve Sanayi A.S.",
    "EREGL": "Eregli Demir ve Çelik Fabrikalari T.A.S.",
    "ESEN": "Esenboga Elektrik Üretim A.S.",
    "EUPWR": "Europower Enerji ve Otomasyon Teknolojileri Sanayi Ticaret Anonim Sirketi",
    "EUREN": "Europen Endustri Insaat Sanayi ve Ticaret A.S.",
    "FENER": "Fenerbahçe Futbol A.S.",
    "FROTO": "Ford Otomotiv Sanayi A.S.",
    "GARAN": "Turkiye Garanti Bankasi A.S.",
    "GENIL": "Gen Ilac Ve Saglik Urunleri Sanayi Ve Ticaret Anonim Sirketi",
    "GESAN": "Girisim Elektrik Sanayi Taahhüt ve Ticaret A.S.",
    "GLRMK": "Gulermak Aglr Sanayi Insaat ve Taahhut A.S.",
    "GRSEL": "Gür-Sel Turizm Tasimacilik ve Servis Ticaret A.S.",
    "GRTHO": "GRAINTURK Holding A.S.",
    "GSRAY": "Galatasaray Sportif Sinai ve Ticari Yatirimlar A.S.",
    "GUBRF": "Gübre Fabrikalari Türk Anonim Sirketi",
    "HALKB": "Türkiye Halk Bankasi A.S.",
    "HEKTS": "Hektas Ticaret T.A.S.",
    "IEYHO": "Isiklar Enerji ve Yapi Holding A.S.",
    "ISCTR": "Türkiye Is Bankasi A.S.",
    "ISMEN": "Is Yatirim Menkul Degerler Anonim Sirketi",
    "IZENR": "IZDEMIR Enerji Elektrik Uretim A.S.",
    "KCHOL": "Koç Holding A.S.",
    "KLRHO": "Kiler Holding Anonim Sirketi",
    "KRDMD": "Kardemir Karabük Demir Çelik Sanayi Ve Ticaret A.S.",
    "KTLEV": "Katilimevim Tasarruf Finansman Anonim Sirketi",
    "KUYAS": "Kuyas Yatirim A.S.",
    "MAGEN": "Margün Enerji Üretim Sanayi ve Ticaret A.S.",
    "MAVI": "Mavi Giyim Sanayi ve Ticaret A.S.",
    "MGROS": "Migros Ticaret A.S.",
    "MIATK": "MIA Teknoloji Anonim Sirketi",
    "MPARK": "MLP Saglik Hizmetleri A.S.",
    "OBAMS": "OBA MAKARNACILIK",
    "ODAS": "Odas Elektrik Üretim Sanayi Ticaret A.S.",
    "ODINE": "ODINE TEKNOLOJI",
    "OTKAR": "Otokar Otomotiv ve Savunma Sanayi A.S.",
    "OYAKC": "OYAK Çimento Fabrikalari A.S.",
    "PAHOL": "PASIFIK HOLDING",
    "PASEU": "Pasifik Eurasia Lojistik Dis Ticaret A.S.",
    "PATEK": "Pasifik Teknoloji A.S.",
    "PETKM": "Petkim Petrokimya Holding Anonim Sirketi",
    "PGSUS": "Pegasus Hava Tasimaciligi Anonim Sirketi",
    "PSGYO": "Pasifik Gayrimenkul Yatirim Ortakligi A.S.",
    "QUAGR": "QUA Granite Hayal Yapi ve Ürünleri Sanayi Ticaret A.S.",
    "RALYH": "Ral Yatirim Holding A.S.",
    "REEDR": "Reeder Teknoloji Sanayi ve Ticaret Anonim Sirketi",
    "SAHOL": "Haci Ömer Sabanci Holding A.S.",
    "SARKY": "Sarkuysan Elektrolitik Bakir Sanayi ve Ticaret A.S.",
    "SASA": "Sasa Polyester Sanayi A.S.",
    "SISE": "Türkiye Sise Ve Cam Fabrikalari A.S.",
    "SKBNK": "Sekerbank T.A.S.",
    "SOKM": "Sok Marketler Ticaret A.S.",
    "TAVHL": "TAV Havalimanlari Holding A.S.",
    "TCELL": "Turkcell Iletisim Hizmetleri A.S.",
    "THYAO": "Türk Hava Yollari Anonim Ortakligi",
    "TKFEN": "Tekfen Holding Anonim Sirketi",
    "TOASO": "Tofas Türk Otomobil Fabrikasi Anonim Sirketi",
    "TRALT": "Turk Altin Isletmeleri A.S.",
    "TRENJ": "Ipek Dogal Enerji Kaynaklari Arastirma ve Üretim A.S.",
    "TRMET": "TR Anadolu Metal Madencilik Isletmeleri A.S.",
    "TSKB": "Türkiye Sinai Kalkinma Bankasi A.S.",
    "TTKOM": "Türk Telekomünikasyon Anonim Sirketi",
    "TUKAS": "Tukas Gida Sanayi ve Ticaret A.S.",
    "TUPRS": "Türkiye Petrol Rafinerileri A.S.",
    "TURSG": "Türkiye Sigorta A.S.",
    "ULKER": "Ülker Bisküvi Sanayi A.S.",
    "VAKBN": "Türkiye Vakiflar Bankasi Türk Anonim Ortakligi",
    "VESTL": "Vestel Elektronik Sanayi ve Ticaret Anonim Sirketi",
    "YKBNK": "Yapi ve Kredi Bankasi A.S.",
    "ZOREN": "Zorlu Enerji Elektrik Üretim A.S.",
}

if __name__ == "__main__":
    repo = AssetRepository()
    for symbol, name in BIST100.items():
        repo.upsert(Asset(symbol=symbol, name=name, market="BIST", asset_type="STOCK", currency="TRY"))
        print(f"Seeded {symbol} - {name}")
    print(f"\nToplam {len(BIST100)} varlık eklendi/güncellendi.")
