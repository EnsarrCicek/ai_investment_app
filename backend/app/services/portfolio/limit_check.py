"""Kullanıcı tanımlı kâr/zarar sınırı — elle çalıştırılan, salt-okunur kontrol.

Değerlendirme `position_review.review` ile yapılır (tamamlanmış seans, fiyat zamanı, fiyat temeli ve kurumsal
işlem kapıları orada; burada KOPYALANMAZ). Bu modül yalnızca:
  * doğrulanmış kullanıcının lotlarını depodan okur (istemci fiyat/maliyet/doğrulama bayrağı GÖNDEREMEZ),
  * pozisyon sürümünü (lot belge kimliklerinden) hesaplar; istemcinin sınırı kaydettiği sürümle uyuşmazsa
    değerlendirme yapılmaz (kapanıp yeniden açılan/düzenlenen pozisyona eski sınır sessizce uygulanmaz),
  * mevcut fiyat sağlayıcısından günlük barları okur ve kaynağın GERÇEK özelliklerini beyan eder.

Mevcut `BistProvider` yfinance'in varsayılan düzeltilmiş (auto_adjust) serisini döndürür ve kurumsal işlem
kontrolü sağlamaz. Bu yüzden fiyat temeli RAW olarak etiketlenmez ve kurumsal işlem kontrolü boş geçilir; sonuç
bu veriyle engel kodudur. Karar motoru çağrılmaz, bildirim gönderilmez, hiçbir şey yazılmaz.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models.portfolio_position import PortfolioPosition
from app.services.market_data.bist_provenance_provider import ProviderIdentityError
from app.services.portfolio import position_review as pr
from app.services.portfolio.corporate_action_verifier import (
    acquisition_evidence,
    position_review_check,
    verify_corporate_actions,
)
from app.services.portfolio.sale_ledger import ledger_totals, remaining_review_lots

PROVIDER_PRICE_BASIS = "PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST"
HISTORY_PERIOD = "1mo"

STATE_NO_LIMITS = "SINIR_TANIMLI_DEGIL"
STATE_WITHIN = "SINIR_ICINDE"
STATE_EXCEEDED = "SINIR_ASILDI"
STATE_NOT_EVALUATED = "DEGERLENDIRILEMEDI"

POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
POSITION_CHANGED = "POSITION_CHANGED"
PRICE_FETCH_FAILED = "PRICE_FETCH_FAILED"
PRICE_IDENTITY_MISMATCH = "PRICE_IDENTITY_MISMATCH"
PRICE_IDENTITY_UNVERIFIED = "PRICE_IDENTITY_UNVERIFIED"

# Kimlik kapısı bu durumlardan ÖNCE değerlendirilir (takvim/fiyat/pozisyon hataları kimlikten önce raporlanır;
# fiyat temeli ve kurumsal işlem kapıları ile değerlendirme kimlik doğrulanmadan sonuç veremez).
IDENTITY_GATED_STATUSES = {pr.VALUED, pr.PRICE_BASIS_UNVERIFIED, pr.CORPORATE_ACTIONS_UNVERIFIED,
                           pr.CORPORATE_ACTION_IN_HOLDING_PERIOD}

BLOCK_MESSAGES = {
    pr.PRICE_BASIS_UNVERIFIED: "Fiyat ve alış maliyetinin aynı temelde olduğu doğrulanamadı "
                               "(veri kaynağı düzeltilmiş fiyat serisi veriyor).",
    pr.CORPORATE_ACTIONS_UNVERIFIED: "Elde tutma döneminde bölünme/bedelsiz gibi kurumsal işlem olmadığı doğrulanamadı.",
    pr.CORPORATE_ACTION_IN_HOLDING_PERIOD: "Elde tutma döneminde kurumsal işlem var; maliyet ile fiyat karşılaştırılamaz.",
    pr.STALE_PRICE: "Son tamamlanmış seansın kapanış fiyatı bulunamadı (yalnız daha eski fiyat var).",
    pr.MISSING_PRICE: "Kapanış fiyatı bulunamadı.",
    pr.INVALID_PRICE: "Kapanış fiyatı geçersiz.",
    pr.INCOMPLETE_BAR: "Son seansın kapanışı henüz kesinleşmedi.",
    pr.OBSERVED_AFTER_EVALUATION: "Fiyat kaydı değerlendirme anından sonra alınmış görünüyor.",
    pr.CONFLICTING_PRICE_RECORDS: "Aynı seans için çelişen fiyat kayıtları var.",
    pr.CALENDAR_UNSUPPORTED: "İşlem takvimi bu tarih için tanımlı değil.",
    pr.INVALID_POSITION: "Pozisyonun adet veya alış fiyatı geçersiz.",
    pr.BUY_AFTER_VALUATION_SESSION: "Alış tarihi son tamamlanmış seanstan sonra.",
    POSITION_NOT_FOUND: "Bu varlık için açık pozisyon bulunamadı.",
    POSITION_CHANGED: "Pozisyon, sınırlar kaydedildikten sonra değişmiş. Sınırları yeniden onaylayın.",
    PRICE_FETCH_FAILED: "Fiyat verisi alınamadı.",
    PRICE_IDENTITY_MISMATCH: "Fiyat verisinin sembol/borsa/para birimi kimliği beklenenle uyuşmuyor; veri kullanılmadı.",
    PRICE_IDENTITY_UNVERIFIED: "Fiyat verisinin sembol/borsa/para birimi kimliği sağlayıcı yanıtında eksik; "
                               "değerlendirme yapılmadı.",
}

NOTES = [
    "Elle çalıştırılan kontrol; otomatik takip ve telefon bildirimi bu sürümde yoktur.",
    "AL/SAT tavsiyesi değildir; otomatik satış yapılmaz.",
    "Oran fiyat bazlı gerçekleşmemiş farktır; komisyon, vergi ve temettü dahil değildir (net kazanç değildir).",
]


def _lot_key(lot_id: str, lot: PortfolioPosition) -> str:
    when = lot.buy_date.astimezone(timezone.utc).isoformat() if lot.buy_date.tzinfo else lot.buy_date.isoformat()
    return f"{lot_id}|{lot.asset.upper()}|{float(lot.quantity)!r}|{float(lot.buy_price)!r}|{when}"


def position_version(lots: list[tuple[str, PortfolioPosition]], sale_ids: list[str] | tuple = ()) -> str:
    """Pozisyon sürümü: her lotun belge kimliği + miktar + alış fiyatı + alış tarihi; lot sırasından bağımsız.

    Uygulama yolları içerikte değişiklikte zaten yeni belge yazar (`replace_for_asset` = sil + ekle; kapatma lotları
    siler; yeni lot rastgele kimlik alır). İçerik alanları, aynı belgenin yerinde değiştirilmesine (ör. yönetici
    SDK'sı/konsol) karşı da sürümün değişmesi için dahil edilir.

    `sale_ids`: pozisyona uygulanan kısmi satış kayıtları (bkz. `sale_ledger`). Satış yoksa sürüm öncekiyle aynıdır;
    varsa her satış sürümü değiştirir (bayat satış ekranı/sınır ayarı korunması)."""
    key = ";".join(sorted(_lot_key(i, p) for i, p in lots))
    if sale_ids:
        key += "|sales:" + ",".join(sorted(sale_ids))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _price_records(history, retrieved_at: datetime, source: str, basis: str) -> list[dict]:
    records = []
    for ts, row in history.iterrows():
        day = ts.tz_convert(ISTANBUL_TZ).date() if ts.tzinfo else ts.date()
        records.append({"symbol": None, "session": day.isoformat(), "close": float(row["Close"]),
                        "price_basis": basis, "source": source, "retrieved_at": retrieved_at})
    return records


def _base(asset: str, version: str | None, limits: dict) -> dict:
    return {"asset": asset, "position_version": version, "limits": limits, "state": None, "block_code": None,
            "block_message": None, "evaluated_at": None, "expected_session": None, "price_used": None,
            "checks": None, "price_provenance": None, "corporate_action_verification": None, "notes": NOTES}


def _blocked(out: dict, code: str) -> dict:
    out.update(state=STATE_NOT_EVALUATED, block_code=code, block_message=BLOCK_MESSAGES.get(code, code))
    return out


def check_limits(user_id: str, asset: str, client_version: str, limits: dict, portfolio_repo, provider,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 price_basis: str = PROVIDER_PRICE_BASIS, corporate_action_check: dict | None = None,
                 ledger_repo=None, corporate_action_provider=None) -> dict:
    """limits: {"profit_target_pct": float|None, "max_loss_pct": float|None}. Sınır doğrulaması position_review'da
    (geçersizse pr.InputError). `price_basis`/`corporate_action_check` yalnız sunucu tarafı kaynak beyanıdır; API
    uç noktası bunları istemciden ALMAZ ve mevcut sağlayıcı için varsayılanlar (düzeltilmiş, kontrol yok) kullanılır.

    `ledger_repo` (satış defteri): kısmi satışlar kanonik `ledger_totals` ile düşülür; sürüm `/positions` ve `/sell`
    ile aynı algoritmadır (lotlar + uygulanan satış kimlikleri) ve review'e kalan adet/kesin kalan maliyet gider.
    Verilmezse satış yok sayılır (yalnız satış defteri olmayan testler; API her zaman verir).

    Kurumsal işlem kapısı: `corporate_action_check` (yalnız testlerin sunucu tarafı beyanı) verilmemişse kanonik
    `verify_corporate_actions` sonucu (en erken lot alışı → değerleme seansı) `position_review` girdisine çevrilir;
    satış ve açık K/Z ile aynı algoritma. Kapı sırası (kimlik → fiyat temeli → kurumsal işlem) değişmez."""
    asset = asset.upper()
    pr._parse_limits(limits)  # erken doğrulama; hata -> InputError
    out = _base(asset, None, limits)
    if limits.get("profit_target_pct") is None and limits.get("max_loss_pct") is None:
        out["state"] = STATE_NO_LIMITS
        return out
    lots = [(i, p) for i, p in portfolio_repo.list_for_user(user_id) if p.asset.upper() == asset]
    if not lots:
        return _blocked(out, POSITION_NOT_FOUND)
    sales = ([(i, s) for i, s in ledger_repo.sales_for_user(user_id) if s.asset.upper() == asset]
             if ledger_repo is not None else [])
    remaining_qty, _, sale_ids = ledger_totals(lots, sales)
    out["position_version"] = position_version(lots, sale_ids)
    if out["position_version"] != client_version:
        return _blocked(out, POSITION_CHANGED)
    if remaining_qty <= 0:  # tamamen satılmış: açık pozisyon yok, değerlendirme yapılmaz
        return _blocked(out, POSITION_NOT_FOUND)
    review_lots = remaining_review_lots(lots, sales)  # kanonik kalan durum (ham lot toplamı DEĞİL)
    try:
        history, provenance = provider.get_history_with_provenance(asset, period=HISTORY_PERIOD)
    except ProviderIdentityError:
        return _blocked(out, PRICE_IDENTITY_MISMATCH)  # uyuşmayan kimlikteki veri hiç kullanılmaz
    except Exception:  # noqa: BLE001 — sağlayıcı hatası değerlendirilemedi olarak döner
        return _blocked(out, PRICE_FETCH_FAILED)
    # Kimlik/kaynak bilgisi aynı geçmiş yanıtından; fiyat temeli beyanı DEĞİŞMEZ (Yahoo için düzeltilmiş seri).
    out["price_provenance"] = {**provenance, "retrieved_at": provenance["retrieved_at"].isoformat(), "price_basis": price_basis}
    now = clock()
    records = _price_records(history, provenance["retrieved_at"], provenance["source"], price_basis)
    for r in records:
        r["symbol"] = asset
    session = pr.valuation_session(now)
    # Kurumsal işlem kaynağına yalnız kimlik ve ham fiyat temeli kapıları geçilebilecekse gidilir; aksi halde sonuç
    # zaten o kapılarda engellenir (review: fiyat temeli kurumsal işlemden önce; kimlik kapısı review'den sonra).
    gates_passable = provenance.get("identity_check") == "MATCH" and price_basis == pr.RAW_BASIS
    if corporate_action_check is None and session is not None and gates_passable:
        verification = verify_corporate_actions(asset, acquisition_evidence(review_lots), session,
                                                corporate_action_provider)
        out["corporate_action_verification"] = verification.summary()
        corporate_action_check = position_review_check(verification)
    report = pr.review({"evaluated_at": now, "positions": [p.model_dump() for p in review_lots], "price_records": records,
                        "corporate_action_checks": {asset: corporate_action_check} if corporate_action_check else {},
                        "limits": {k: v for k, v in limits.items() if v is not None}})
    (row,) = report["positions"]
    out.update(evaluated_at=report["evaluated_at"], expected_session=report["expected_valuation_session"],
               review_version=report["review_version"])
    identity_ok = provenance.get("identity_check") == "MATCH"
    if row["status"] in IDENTITY_GATED_STATUSES and not identity_ok:
        # Kimlik doğrulanmadan fiyat (RAW beyanlı olsa bile) kullanılmaz; hesaplanan hiçbir değer döndürülmez.
        return _blocked(out, PRICE_IDENTITY_UNVERIFIED)
    if row["status"] != pr.VALUED:
        stale = row.get("last_known_price_stale") if identity_ok else None  # doğrulanmamış kaynaktan fiyat gösterilmez
        out["last_known_price"] = ({"session": stale["session"], "source": stale["source"],
                                    "price_basis": stale["price_basis"]} if stale else None)
        return _blocked(out, row["status"])
    used = row["price_used"]
    out["price_used"] = {"session": used["session"], "close": used["close"], "source": used["source"],
                         "price_basis": used["price_basis"]}
    lc = row["limit_checks"]
    out["checks"] = {"profit_target": {"limit_pct": lc["profit_target_pct"]["limit"], "gain_pct_vs_cost": lc["profit_target_pct"]["gain_pct_vs_cost"],
                                       "status": lc["profit_target_pct"]["status"]},
                     "max_loss": {"limit_pct": lc["max_loss_pct"]["limit"], "loss_pct_vs_cost": lc["max_loss_pct"]["loss_pct_vs_cost"],
                                  "status": lc["max_loss_pct"]["status"]}}
    statuses = {c["status"] for c in out["checks"].values()}
    out["state"] = STATE_EXCEEDED if pr.LIMIT_EXCEEDED in statuses else STATE_WITHIN
    return out
