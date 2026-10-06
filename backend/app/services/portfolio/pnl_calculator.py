from app.models.portfolio_position import PortfolioPosition
from app.services.market_data.base import MarketDataProvider
from app.models.market_data import MarketData
from app.services.market_data.bist_provenance_provider import ProvenanceBistProvider
from app.services.portfolio.position_review import RAW_BASIS


def position_basis_verification(corporate_actions_verified: bool = False) -> tuple[bool, str | None]:
    """(position_basis_verified, position_basis_unverified_reason).

    True = kayıtlı adet ve alış maliyeti tabanı, en erken lot tarihinden değerleme seansına kadar adet/maliyet etkili
    kurumsal işlemler açısından doğrulanmıştır. Üretimde kurumsal işlem kapsamı olmadığı için her zaman False."""
    if not corporate_actions_verified:
        return False, "CORPORATE_ACTIONS_UNVERIFIED"
    return True, None


def pnl_verification(position_currency: str | None, latest: MarketData,
                     corporate_actions_verified: bool = False) -> tuple[bool, str | None]:
    """(pnl_basis_verified, pnl_unverified_reason).

    True = maliyet ve değerleme fiyatı aynı güvenilir fiyat temelinde karşılaştırılabilir ve gerekli kurumsal işlem
    etkileri doğrulanmıştır. False = sayısal hesap yapılmış olabilir ama yatırım sonucu olarak doğrulanmış değildir.
    İlk sağlanmayan koşul gerekçe olarak döner (deterministik sıra). Üretimde kurumsal işlem doğrulaması YOK."""
    if latest.identity_check != "MATCH":
        return False, "PRICE_IDENTITY_UNVERIFIED"
    if position_currency is None:
        return False, "POSITION_CURRENCY_UNKNOWN"
    if latest.currency is None:
        return False, "PRICE_CURRENCY_UNKNOWN"
    if position_currency != latest.currency:
        return False, "CURRENCY_MISMATCH"
    if latest.price_basis != RAW_BASIS:
        return False, "PRICE_BASIS_UNVERIFIED"
    basis_ok, basis_reason = position_basis_verification(corporate_actions_verified)
    if not basis_ok:  # doğrulanmış K/Z, doğrulanmamış adet/maliyet tabanı üzerinden üretilemez
        return False, basis_reason
    return True, None


def calculate_pnl(position: PortfolioPosition, provider: MarketDataProvider | None = None,
                  corporate_actions_verified: bool = False) -> dict:
    """Hesap formülleri değişmedi. `corporate_actions_verified` yalnız doğrulanmış bir kaynak bağlandığında True
    olabilir; bugün hiçbir üretim çağıranı bunu vermiyor."""
    provider = provider or ProvenanceBistProvider()
    latest = provider.get_latest(position.asset)
    current_price = latest.close

    invested_amount = round(position.quantity * position.buy_price, 2)
    current_value = round(position.quantity * current_price, 2)
    profit_loss = round(current_value - invested_amount, 2)
    return_percent = round((profit_loss / invested_amount) * 100, 2) if invested_amount else 0.0

    return {
        "current_price": current_price,
        "invested_amount": invested_amount,
        "current_value": current_value,
        "profit_loss": profit_loss,
        "return_percent": return_percent,
        # Güncel fiyatın kaynağı (aynı sağlayıcı yanıtı); kayıtlı pozisyon para birimiyle KARIŞTIRILMAZ.
        "current_price_currency": latest.currency,
        "current_price_exchange": latest.exchange,
        "current_price_identity_check": latest.identity_check,
        "current_price_basis": latest.price_basis,
        **dict(zip(("pnl_basis_verified", "pnl_unverified_reason"),
                   pnl_verification(position.currency, latest, corporate_actions_verified))),
        # Adet/maliyet tabanı doğrulaması; current_value (adet × güncel fiyat) bu olmadan doğrulanmış sayılamaz.
        **dict(zip(("position_basis_verified", "position_basis_unverified_reason"),
                   position_basis_verification(corporate_actions_verified))),
    }


def calculate_realized_pnl(quantity: float, buy_price: float, sell_price: float) -> dict:
    """Bir pozisyon kapatıldığında (satıldığında) gerçekleşen kâr/zararı hesaplar.

    AŞAMA 47: kullanıcı bir pozisyonu sildiğinde önceden hiçbir kayıt
    tutulmuyordu (geçmiş tamamen kayboluyordu). Artık "sil" işlemi bir satış
    fiyatı istiyor ve bu fonksiyonla hesaplanan sonuç PortfolioTransaction
    olarak kalıcı şekilde saklanıyor.
    """
    realized_pnl = round((sell_price - buy_price) * quantity, 2)
    invested_amount = buy_price * quantity
    realized_pnl_percent = round((realized_pnl / invested_amount) * 100, 2) if invested_amount else 0.0
    return {"realized_pnl": realized_pnl, "realized_pnl_percent": realized_pnl_percent}
