# Python'un standart str.upper()'ı Türkçe küçük "i"yi ASCII "I"ye çeviriyor,
# oysa Türkçe metinler noktalı büyük "İ" kullanır — bu yüzden case-insensitive
# karşılaştırmalar (ör. "hisse" araması) sessizce başarısız olabiliyor (bkz.
# KURULUM_GUNLUGU.md AŞAMA 60, funds.py arama hatası). Önce Türkçe küçük
# harfleri doğru büyük karşılıklarına çevirip SONRA standart upper() çağrılır.
_TR_LOWER_TO_UPPER = str.maketrans({"i": "İ", "ı": "I"})


def tr_upper(text: str) -> str:
    return text.translate(_TR_LOWER_TO_UPPER).upper()
