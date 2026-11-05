"""Matriks sağlayıcı YER TUTUCUSU (yalnız araştırma). Resmi teknik doküman ve kimlik bilgisi gelene kadar hiçbir
bağlantı yöntemi çalışmaz (`MatriksConfigurationRequired`). Uç nokta, REST yolu, MQTT konusu, alan adı UYDURULMAZ.
"""

from app.research.momentum_sources.matriks.config import MatriksConfig, MatriksConfigurationRequired

PROVIDER = "matriks"
__all__ = ["PROVIDER", "MatriksConfig", "MatriksConfigurationRequired"]
