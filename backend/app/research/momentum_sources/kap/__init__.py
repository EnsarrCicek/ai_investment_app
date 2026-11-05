"""Resmi KAP REST API hazırlığı (yalnız araştırma). Erişim abonelik/yetki gerektirir; resmi entegrasyon dokümanı ve
API anahtarı gelene kadar her bağlantı yöntemi `KapConfigurationRequired` ile kapalı kalır.

Uç nokta yolu, HTTP yöntemi, başlık/parametre adı, yanıt alanı UYDURULMAZ. Herkese açık kap.org.tr sitesi otomatik
toplayıcı olarak KULLANILMAZ (kazıma / tarayıcı çağrısı tersine mühendisliği yok).
"""

from app.research.momentum_sources.kap.config import KapConfig, KapConfigurationRequired

PROVIDER = "kap_official"
__all__ = ["PROVIDER", "KapConfig", "KapConfigurationRequired"]
