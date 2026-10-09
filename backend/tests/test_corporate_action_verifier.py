"""Kurumsal işlem doğrulayıcısı — kanonik sonuç, alış tarihi kanıtı, coverage semantiği, kimlik, olay türleri ve
satış/K/Z/limit entegrasyonu. Ağsız; tüm kaynak verisi test fikstürüdür (gerçek kaynak/Firestore yok)."""

from datetime import date, datetime, timezone

import pytest
from google.cloud.firestore_v1 import _helpers as firestore_helpers

from app.engines.technical.session_timing import ISTANBUL_TZ
from app.models import corporate_action as ca
from app.models.portfolio_position import PortfolioPosition
from app.services.portfolio import corporate_action_verifier as cav
from app.services.portfolio import limit_check as lc
from app.services.portfolio import position_review as pr
from app.services.portfolio.pnl_calculator import calculate_pnl
from app.services.portfolio.sale_ledger import plan_sale

# TUPRS fikstürü (gerçek satış kaydının tarihleri; kayıt DEĞİŞTİRİLMEZ, burada yalnız saf hesap)
BUY = datetime(2026, 8, 19, 10, 46, 43, tzinfo=timezone.utc)  # İstanbul 2026-08-19
SALE = datetime(2026, 10, 9, 8, 27, 57, tzinfo=timezone.utc)  # İstanbul 2026-10-09
ISIN = "TRATUPRS91E8"  # test fikstürü değeri
FROM, THROUGH = date(2026, 8, 19), date(2026, 10, 9)
PROV = ca.SourceProvenance(source="fixture_source", retrieved_at=datetime(2026, 10, 9, 20, tzinfo=timezone.utc),
                           provider_version="fixture-v1")


def acquired(when=BUY, verified=True):
    """Alış tarihi kanıtı. verified=True yalnız testte (doğrulanmış işlem kaynağını temsil eder)."""
    return ca.AcquisitionDateEvidence(acquired_at=when, verified=verified,
                                      source="fixture_broker_ledger" if verified else ca.ACQUISITION_SOURCE_APP_RECORDED)


def identity(isin=ISIN, status=ca.IDENTITY_VERIFIED, symbol="TUPRS", mic=ca.XIST, valid_from=date(2000, 1, 1),
             valid_through=None):
    return ca.InstrumentIdentity(symbol=symbol, isin=isin, mic=mic, identity_status=status, valid_from=valid_from,
                                 valid_through=valid_through, provenance=PROV)


def coverage(frm=date(2026, 1, 1), thru=date(2026, 10, 9), types=ca.REQUIRED_EVENT_TYPES,
             completeness=ca.COVERAGE_COMPLETE, isin=ISIN, symbol="TUPRS", mic=ca.XIST):
    return ca.CorporateActionCoverage(isin=isin, symbol=symbol, mic=mic, checked_from=frm, checked_through=thru,
                                      covered_event_types=frozenset(types), completeness=completeness, provenance=PROV)


def event(event_type, day=date(2026, 9, 15), status=ca.EVENT_ACTIVE, event_id="e1", original=None, isin=ISIN, **terms):
    return ca.CorporateActionEvent(event_id=event_id, symbol="TUPRS", isin=isin, mic=ca.XIST, event_type=event_type,
                                   effective_date=day, announcement_id="kap-1", status=status,
                                   original_event_id=original, provenance=PROV, **terms)


SPLIT_TERMS = {"split": ca.SplitTerms(old_shares="1", new_shares="2")}


class Source:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def get_corporate_action_coverage(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        if self.error:
            raise self.error
        return self.result


def full(events=(), cov=None, ident=None):
    return Source(ca.CorporateActionSourceResult(identity=ident or identity(), coverage=tuple(cov or [coverage()]),
                                                 events=tuple(events)))


def verify(src, acq=None, thru=SALE, symbol="TUPRS"):
    return cav.verify_corporate_actions(symbol, acq if acq is not None else acquired(), thru, src)


def tuprs_lot(verified=False):
    return PortfolioPosition(user_id="u", asset="TUPRS", buy_price=377.5, quantity=4.0, buy_date=BUY, created_at=BUY,
                             acquisition_date_verified=verified)


def tuprs_sale(provider=None, verified=False):
    return plan_sale("u", "TUPRS", [("l1", tuprs_lot(verified))], [], quantity=1.0, sell_price=385.5, sell_date=SALE,
                     expected_version=None, request_currency=None, now=SALE,
                     corporate_action_provider=provider).transaction


# --- TUPRS fikstürü A–F ----------------------------------------------------------------------------------------------

def test_A_no_coverage_is_missing_and_sale_unverified_with_unchanged_math():
    v = verify(None)  # üretim varsayılanı
    assert not v.verified and v.reason == cav.COVERAGE_MISSING
    assert (v.required_from, v.required_through) == (FROM, THROUGH)
    tx = tuprs_sale()
    assert tx.basis_verified is False and tx.basis_verification_reason == cav.COVERAGE_MISSING
    assert tx.corporate_action_checked_from is None and tx.corporate_action_source is None
    assert (tx.disposed_cost_basis, tx.sale_proceeds, tx.realized_pnl_exact) == ("377.50", "385.50", "8.00")
    assert (tx.remaining_quantity, tx.remaining_cost_basis) == ("3.0", "1132.50")


def test_B_full_coverage_no_events_verifies():
    src = full()
    v = verify(src)
    assert v.verified and v.reason == cav.MATCH and v.events == ()
    assert (v.checked_from, v.checked_through) == (date(2026, 1, 1), THROUGH)
    assert v.source == "fixture_source" and v.isin == ISIN and v.instrument_identity_status == ca.IDENTITY_VERIFIED
    assert src.calls == [("TUPRS", FROM, THROUGH)]


def test_C_coverage_not_reaching_buy_date_fails():
    v = verify(full(cov=[coverage(frm=date(2026, 9, 1))]))
    assert not v.verified and v.reason == cav.COVERAGE_INCOMPLETE


def test_D_isin_unknown_fails():
    assert verify(full(ident=identity(isin=None))).reason == cav.IDENTITY_UNVERIFIED
    assert verify(full(ident=identity(status=ca.IDENTITY_UNVERIFIED))).reason == cav.IDENTITY_UNVERIFIED


def test_E_split_requires_position_adjustment():
    v = verify(full([event(ca.SPLIT, **SPLIT_TERMS)]))
    assert not v.verified and v.reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT
    assert [e.event_type for e in v.events] == [ca.SPLIT]


@pytest.mark.parametrize("ev", [
    event(ca.SYMBOL_CHANGE, symbol_change=ca.SymbolChangeTerms(old_symbol="TUPRS", new_symbol="TUPRX",
                                                               isin_continuous=True)),
    event(ca.MERGER, conversion=ca.ConversionTerms(old_isin=ISIN, new_isins=("TRAXXXXX0001",), conversion_ratio="1")),
    event(ca.DEMERGER, conversion=ca.ConversionTerms(old_isin=ISIN, new_isins=(ISIN, "TRAYYYYY0002"),
                                                     conversion_ratio="0.5")),
])
def test_F_symbol_change_and_merger_fail_closed(ev):
    v = verify(full([ev]))
    assert not v.verified and v.reason == cav.UNSUPPORTED_EVENT


# --- alış tarihi kanıtı (elde tutma başlangıcı) ----------------------------------------------------------------------

def test_acq_1_no_provider_stays_coverage_missing_even_if_unverified():
    assert verify(None, acq=acquired(verified=False)).reason == cav.COVERAGE_MISSING


def test_acq_2_provider_full_coverage_but_unverified_acquisition():
    v = verify(full(), acq=acquired(verified=False))
    assert not v.verified and v.reason == cav.ACQUISITION_DATE_UNVERIFIED
    # Düz tarih/zaman (eski çağrı biçimi) hiçbir zaman doğrulanmış sayılmaz.
    assert verify(full(), acq=BUY).reason == cav.ACQUISITION_DATE_UNVERIFIED
    assert verify(full(), acq=FROM).reason == cav.ACQUISITION_DATE_UNVERIFIED


def test_acq_3_provider_full_coverage_verified_acquisition_matches():
    assert verify(full(), acq=acquired(verified=True)).reason == cav.MATCH


def test_acq_4_legacy_position_is_unverified():
    legacy = PortfolioPosition(**{"user_id": "u", "asset": "TUPRS", "buy_price": 377.5, "quantity": 4.0,
                                  "buy_date": BUY, "created_at": BUY})  # eski Firestore belgesi biçimi
    ev = cav.acquisition_evidence([legacy])
    assert ev.verified is False and ev.source == ca.ACQUISITION_SOURCE_UNSPECIFIED and ev.acquired_at == BUY
    assert verify(full(), acq=ev).reason == cav.ACQUISITION_DATE_UNVERIFIED


def test_acq_mixed_lots_unverified_and_earliest_lot_is_start():
    later = tuprs_lot(verified=True).model_copy(update={"buy_date": datetime(2026, 9, 1, tzinfo=timezone.utc),
                                                        "acquisition_date_source": "fixture_broker_ledger"})
    ev = cav.acquisition_evidence([later, tuprs_lot(verified=False)])
    assert ev.verified is False and ev.acquired_at == BUY and ev.source == "MIXED"
    both = cav.acquisition_evidence([later, tuprs_lot(verified=True)])
    assert both.verified is True and both.acquired_at == BUY


def test_acq_5_app_add_and_edit_record_unverified_even_if_client_claims(monkeypatch):
    from tests.test_partial_sale import make_client
    c, store = make_client(monkeypatch, [])
    body = {"asset": "AAA", "buy_price": 10.0, "quantity": 5.0, "buy_date": "2026-08-19T10:00:00+00:00",
            "currency": "TRY", "acquisition_date_verified": True, "acquisition_date_source": "BROKER"}
    assert c.post("/portfolio/positions", json=body).status_code == 200
    (doc,) = store.lots.values()
    assert doc["acquisition_date_verified"] is False
    assert doc["acquisition_date_source"] == ca.ACQUISITION_SOURCE_APP_RECORDED
    upd = {k: body[k] for k in ("buy_price", "quantity", "buy_date", "acquisition_date_verified")}
    assert c.put("/portfolio/positions/AAA", json=upd).status_code == 200
    (doc,) = store.lots.values()
    assert doc["acquisition_date_verified"] is False
    assert doc["acquisition_date_source"] == ca.ACQUISITION_SOURCE_APP_RECORDED


# --- aynı gün / olay penceresi (iki uç dahil) ------------------------------------------------------------------------

@pytest.mark.parametrize("ev,reason", [
    (event(ca.SPLIT, day=FROM, **SPLIT_TERMS), cav.EVENT_REQUIRES_POSITION_ADJUSTMENT),
    (event(ca.BONUS, day=FROM, split=ca.SplitTerms(old_shares="1", new_shares="1.5")), cav.EVENT_REQUIRES_POSITION_ADJUSTMENT),
    (event(ca.RIGHTS, day=FROM, rights=ca.RightsTerms(rights_ratio="0.5", subscription_price="1.00")),
     cav.EVENT_REQUIRES_POSITION_ADJUSTMENT),
    (event(ca.SYMBOL_CHANGE, day=FROM, symbol_change=ca.SymbolChangeTerms(old_symbol="TUPRS", new_symbol="TUPRX",
                                                                         isin_continuous=True)), cav.UNSUPPORTED_EVENT),
])
def test_same_day_event_on_verified_acquisition_date_is_not_match(ev, reason):
    v = verify(full([ev]), acq=acquired(verified=True))
    assert not v.verified and v.reason == reason


def test_event_one_day_before_is_outside_one_day_after_inside_end_day_inside():
    assert verify(full([event(ca.SPLIT, day=date(2026, 8, 18), **SPLIT_TERMS)])).verified
    assert verify(full([event(ca.SPLIT, day=date(2026, 8, 20), **SPLIT_TERMS)])).reason == \
        cav.EVENT_REQUIRES_POSITION_ADJUSTMENT
    assert verify(full([event(ca.SPLIT, day=THROUGH, **SPLIT_TERMS)])).reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT
    assert verify(full([event(ca.SPLIT, day=date(2026, 10, 10), **SPLIT_TERMS)])).verified


def test_zero_length_holding_period():
    d = date(2026, 9, 15)
    acq = acquired(datetime(2026, 9, 15, 9, tzinfo=timezone.utc))
    assert verify(full(cov=[coverage(frm=d, thru=d)]), acq=acq, thru=d).verified
    assert verify(full([event(ca.SPLIT, day=d, **SPLIT_TERMS)], cov=[coverage(frm=d, thru=d)]), acq=acq,
                  thru=d).reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT


def test_buy_date_uses_istanbul_calendar_day():
    late_utc = datetime(2026, 8, 18, 22, 30, tzinfo=timezone.utc)  # İstanbul 2026-08-19 01:30
    v = verify(full(cov=[coverage(frm=FROM, thru=THROUGH)]), acq=acquired(late_utc))
    assert v.required_from == FROM and v.verified
    # Aynı İstanbul günündeki olay pencerede (UTC gününe göre bir gün önce görünse bile).
    assert verify(full([event(ca.SPLIT, day=FROM, **SPLIT_TERMS)]), acq=acquired(late_utc)).reason == \
        cav.EVENT_REQUIRES_POSITION_ADJUSTMENT


def test_invalid_range_and_source_error_fail_closed():
    assert verify(full(), acq=acquired(SALE), thru=BUY).reason == cav.INVALID_RANGE
    v = verify(Source(error=RuntimeError("down")))
    assert not v.verified and v.reason == cav.SOURCE_ERROR


# --- coverage semantiği ----------------------------------------------------------------------------------------------

def test_empty_source_result_is_not_no_events():
    v = verify(Source(ca.CorporateActionSourceResult(identity=identity(), coverage=(), events=())))
    assert not v.verified and v.reason == cav.COVERAGE_MISSING


def test_partial_completeness_or_missing_event_type_is_incomplete():
    assert verify(full(cov=[coverage(completeness=ca.COVERAGE_PARTIAL)])).reason == cav.COVERAGE_INCOMPLETE
    assert verify(full(cov=[coverage(types=ca.REQUIRED_EVENT_TYPES - {ca.RIGHTS})])).reason == cav.COVERAGE_INCOMPLETE


def test_coverage_boundaries_inclusive():
    assert verify(full(cov=[coverage(frm=FROM, thru=THROUGH)])).verified
    assert verify(full(cov=[coverage(frm=date(2026, 8, 20), thru=THROUGH)])).reason == cav.COVERAGE_INCOMPLETE
    assert verify(full(cov=[coverage(frm=FROM, thru=date(2026, 10, 8))])).reason == cav.COVERAGE_INCOMPLETE


def test_merge_consecutive_calendar_days():
    assert verify(full(cov=[coverage(frm=FROM, thru=date(2026, 9, 1)), coverage(frm=date(2026, 9, 2), thru=THROUGH)])).verified


def test_merge_friday_to_monday():
    # 2026-08-28 Cuma, 2026-08-31 Pazartesi: arada beklenen seans yok
    assert verify(full(cov=[coverage(frm=FROM, thru=date(2026, 8, 28)), coverage(frm=date(2026, 8, 31), thru=THROUGH)])).verified


def test_merge_across_official_holiday():
    # 2026-05-27..29 Kurban Bayramı kapanışı + 30-31 hafta sonu (trading_calendar)
    acq = acquired(datetime(2026, 5, 20, 9, tzinfo=timezone.utc))
    cov = [coverage(frm=date(2026, 5, 20), thru=date(2026, 5, 26)), coverage(frm=date(2026, 6, 1), thru=date(2026, 6, 10))]
    assert verify(full(cov=cov), acq=acq, thru=date(2026, 6, 10)).verified


def test_merge_real_trading_day_gap_is_incomplete():
    gap = [coverage(frm=FROM, thru=date(2026, 9, 1)), coverage(frm=date(2026, 9, 3), thru=THROUGH)]  # 09-02 Çarşamba seans
    assert verify(full(cov=gap)).reason == cav.COVERAGE_INCOMPLETE


def test_merge_unsupported_calendar_year_fails_closed():
    acq = acquired(datetime(2026, 12, 21, 9, tzinfo=timezone.utc))
    cov = [coverage(frm=date(2026, 12, 21), thru=date(2026, 12, 31)), coverage(frm=date(2027, 1, 4), thru=date(2027, 1, 8))]
    assert verify(full(cov=cov), acq=acq, thru=date(2027, 1, 8)).reason == cav.COVERAGE_INCOMPLETE


def test_overlapping_and_complete_plus_partial_coverage():
    overlap = [coverage(frm=FROM, thru=date(2026, 9, 20)), coverage(frm=date(2026, 9, 1), thru=THROUGH)]
    assert verify(full(cov=overlap)).verified
    # PARTIAL kayıt boşluğu dolduramaz; tam kapsayan COMPLETE varsa PARTIAL yok sayılır.
    hole = [coverage(frm=FROM, thru=date(2026, 9, 1)), coverage(frm=date(2026, 9, 1), thru=THROUGH,
                                                                   completeness=ca.COVERAGE_PARTIAL)]
    assert verify(full(cov=hole)).reason == cav.COVERAGE_INCOMPLETE
    assert verify(full(cov=[coverage(), coverage(completeness=ca.COVERAGE_PARTIAL)])).verified


# --- kimlik ----------------------------------------------------------------------------------------------------------

def test_identity_mismatch_cases():
    assert verify(full(ident=identity(symbol="TUPRX"))).reason == cav.IDENTITY_MISMATCH
    assert verify(full(ident=identity(mic="XNAS"))).reason == cav.IDENTITY_MISMATCH
    assert verify(full(cov=[coverage(isin="TRAOTHER0001")])).reason == cav.IDENTITY_MISMATCH
    assert verify(full(cov=[coverage(mic="XNAS")])).reason == cav.IDENTITY_MISMATCH
    assert verify(full([event(ca.CASH_DIVIDEND, isin="TRAOTHER0001")])).reason == cav.IDENTITY_MISMATCH


def test_coverage_symbol_must_match_canonical_identity():
    assert verify(full(cov=[coverage(symbol="OTHER")])).reason == cav.IDENTITY_MISMATCH  # aynı ISIN, aynı MIC


def test_identity_mapping_must_cover_holding_period_and_be_well_formed():
    assert verify(full(ident=identity(valid_from=date(2026, 9, 1)))).reason == cav.IDENTITY_UNVERIFIED
    assert verify(full(ident=identity(valid_from=None))).reason == cav.IDENTITY_UNVERIFIED
    assert verify(full(ident=identity(valid_through=date(2026, 10, 1)))).reason == cav.IDENTITY_UNVERIFIED
    assert verify(full(ident=identity(isin="TUPRS"))).reason == cav.IDENTITY_UNVERIFIED


# --- olay türleri ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ev", [
    event(ca.SPLIT, split=ca.SplitTerms(old_shares="1", new_shares="10")),
    event(ca.REVERSE_SPLIT, split=ca.SplitTerms(old_shares="10", new_shares="1")),
    event(ca.BONUS, split=ca.SplitTerms(old_shares="1", new_shares="2")),
    event(ca.RIGHTS, rights=ca.RightsTerms(rights_ratio="0.5", subscription_price="1.00")),
])
def test_quantity_affecting_events_require_adjustment(ev):
    assert verify(full([ev])).reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT


def test_cash_dividend_is_recorded_but_not_blocking():
    v = verify(full([event(ca.CASH_DIVIDEND)]))
    assert v.verified and [e.event_type for e in v.events] == [ca.CASH_DIVIDEND]


def test_unknown_event_type_is_unsupported():
    assert verify(full([event("SPIN_OFF_X")])).reason == cav.UNSUPPORTED_EVENT


def test_cancelled_event_is_ignored_but_active_replacement_counts():
    assert verify(full([event(ca.SPLIT, status=ca.EVENT_CANCELLED, **SPLIT_TERMS)])).verified
    repl = [event(ca.SPLIT, event_id="e1", status=ca.EVENT_CANCELLED, **SPLIT_TERMS),
            event(ca.SPLIT, event_id="e2", original="e1", **SPLIT_TERMS)]
    assert verify(full(repl)).reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT


def test_correction_chain():
    original = event(ca.SPLIT, event_id="e1", status=ca.EVENT_SUPERSEDED, **SPLIT_TERMS)
    corrected_outside = event(ca.SPLIT, event_id="e2", original="e1", day=date(2026, 11, 2), **SPLIT_TERMS)
    assert verify(full([original, corrected_outside])).verified  # düzeltme olayı aralık dışına taşıdı
    corrected_inside = corrected_outside.model_copy(update={"effective_date": date(2026, 9, 20)})
    assert verify(full([original, corrected_inside])).reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT


@pytest.mark.parametrize("events", [
    [event(ca.CASH_DIVIDEND, status=ca.EVENT_STATUS_UNKNOWN)],  # durum bilinmiyor
    [event(ca.SPLIT, status=ca.EVENT_SUPERSEDED, **SPLIT_TERMS)],  # yerine geçen yok
    [event(ca.CASH_DIVIDEND, event_id="e2", original="missing")],  # düzeltilen bildirim yok
    [event(ca.CASH_DIVIDEND, event_id="e1"), event(ca.CASH_DIVIDEND, event_id="e2", original="e1")],  # asıl hâlâ ACTIVE
    [event(ca.SPLIT, event_id="e1", status=ca.EVENT_SUPERSEDED, original="e2", **SPLIT_TERMS),  # düzeltme döngüsü
     event(ca.SPLIT, event_id="e2", status=ca.EVENT_SUPERSEDED, original="e1", **SPLIT_TERMS)],
])
def test_unverifiable_correction_status_fails_closed(events):
    assert verify(full(events)).reason == cav.CORRECTION_STATUS_UNVERIFIED


def test_duplicate_event_and_duplicate_announcement_never_match():
    dup = event(ca.SPLIT, **SPLIT_TERMS)
    assert verify(full([dup, dup])).reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT
    two_ids = [event(ca.SPLIT, event_id="a", **SPLIT_TERMS), event(ca.SPLIT, event_id="b", **SPLIT_TERMS)]
    assert verify(full(two_ids)).reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT
    div = event(ca.CASH_DIVIDEND)
    assert verify(full([div, div])).verified  # temettü tekrarı adet/maliyeti etkilemez


# --- entegrasyon: satış --------------------------------------------------------------------------------------------

def test_sale_with_provider_but_app_recorded_lot_is_acquisition_unverified():
    tx = tuprs_sale(provider=full(), verified=False)
    assert tx.basis_verified is False and tx.basis_verification_reason == cav.ACQUISITION_DATE_UNVERIFIED
    assert (tx.disposed_cost_basis, tx.realized_pnl_exact, tx.remaining_cost_basis) == ("377.50", "8.00", "1132.50")


def test_sale_snapshot_with_verified_source_and_acquisition():
    tx = tuprs_sale(provider=full(), verified=True)
    assert tx.basis_verified is True and tx.basis_verification_reason == cav.MATCH
    assert (tx.corporate_action_checked_from, tx.corporate_action_checked_through) == ("2026-01-01", "2026-10-09")
    assert tx.corporate_action_source == "fixture_source"
    assert tx.corporate_action_verifier_version == cav.VERIFIER_VERSION


def test_sale_with_split_in_holding_period_is_recorded_unverified():
    tx = tuprs_sale(provider=full([event(ca.SPLIT, **SPLIT_TERMS)]), verified=True)
    assert tx.basis_verified is False and tx.basis_verification_reason == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT


# --- entegrasyon: açık K/Z -----------------------------------------------------------------------------------------

class Latest:
    def __init__(self, md):
        self.md = md

    def get_latest(self, symbol):
        return self.md


def _md(basis):
    from app.models.market_data import MarketData
    return MarketData(asset_id="TUPRS", timestamp=SALE, open=1, high=1, low=1, close=400.0, volume=1, source="fake",
                      currency="TRY", exchange="IST", identity_check="MATCH", price_basis=basis)


def test_pnl_uses_canonical_verification():
    pos = PortfolioPosition(user_id="u", asset="TUPRS", buy_price=377.5, quantity=3, buy_date=BUY, created_at=BUY,
                            currency="TRY")
    missing = calculate_pnl(pos, provider=Latest(_md(pr.RAW_BASIS)), corporate_action_verification=verify(None))
    assert missing["position_basis_verified"] is False and missing["pnl_basis_verified"] is False
    assert missing["corporate_action_verification"]["reason"] == cav.COVERAGE_MISSING
    unverified_acq = calculate_pnl(pos, provider=Latest(_md(pr.RAW_BASIS)),
                                   corporate_action_verification=verify(full(), acq=acquired(verified=False)))
    assert unverified_acq["position_basis_verified"] is False and unverified_acq["pnl_basis_verified"] is False
    ok = calculate_pnl(pos, provider=Latest(_md(pr.RAW_BASIS)), corporate_action_verification=verify(full()))
    assert ok["position_basis_verified"] is True and ok["pnl_basis_verified"] is True
    # Doğrulanmış kurumsal işlem, düzeltilmiş (Yahoo) fiyat temelini doğrulamaz.
    adjusted = calculate_pnl(pos, provider=Latest(_md("PROVIDER_ADJUSTED_YFINANCE_AUTO_ADJUST")),
                             corporate_action_verification=verify(full()))
    assert adjusted["pnl_basis_verified"] is False and adjusted["pnl_unverified_reason"] == "PRICE_BASIS_UNVERIFIED"


# --- entegrasyon: limit (test_portfolio_limit_check ile aynı sahte fiyat sağlayıcısı) -------------------------------

from tests.test_portfolio_limit_check import BUY as LBUY, NOW as LNOW, FakeProvider, FakeRepo  # noqa: E402

AAA_ISIN = "TRAAAAAA0001"
VERIFIED_ROWS = [("a1", PortfolioPosition(user_id="u1", asset="AAA", buy_price=100.0, buy_date=LBUY, quantity=10.0,
                                          created_at=LBUY, acquisition_date_verified=True))]
APP_ROWS = [("a1", VERIFIED_ROWS[0][1].model_copy(update={"acquisition_date_verified": False}))]


def aaa_source(events=()):
    ident = ca.InstrumentIdentity(symbol="AAA", isin=AAA_ISIN, mic=ca.XIST, identity_status=ca.IDENTITY_VERIFIED,
                                  valid_from=date(2000, 1, 1), provenance=PROV)
    cov = ca.CorporateActionCoverage(isin=AAA_ISIN, symbol="AAA", mic=ca.XIST, checked_from=date(2025, 1, 1),
                                     checked_through=date(2025, 7, 11), covered_event_types=ca.REQUIRED_EVENT_TYPES,
                                     completeness=ca.COVERAGE_COMPLETE, provenance=PROV)
    evs = tuple(e.model_copy(update={"isin": AAA_ISIN, "symbol": "AAA"}) for e in events)
    return Source(ca.CorporateActionSourceResult(identity=ident, coverage=(cov,), events=evs))


def limit(rows=VERIFIED_ROWS, provider=None, basis=pr.RAW_BASIS, price_provider=None, **kw):
    return lc.check_limits("u1", "aaa", lc.position_version(rows), {"max_loss_pct": 8.0}, FakeRepo(rows),
                           price_provider or FakeProvider(), clock=lambda: LNOW, price_basis=basis,
                           corporate_action_provider=provider, **kw)


def test_limit_default_source_stays_blocked():
    out = limit()
    assert out["block_code"] == pr.CORPORATE_ACTIONS_UNVERIFIED
    assert out["corporate_action_verification"]["reason"] == cav.COVERAGE_MISSING


def test_limit_verified_source_and_acquisition_evaluates():
    src = aaa_source()
    out = limit(provider=src)
    assert out["state"] == lc.STATE_WITHIN and out["corporate_action_verification"]["verified"] is True
    assert src.calls == [("AAA", LBUY.astimezone(ISTANBUL_TZ).date(), date(2025, 7, 11))]


def test_limit_app_recorded_acquisition_blocks_even_with_full_source():
    out = limit(rows=APP_ROWS, provider=aaa_source())
    assert out["block_code"] == pr.CORPORATE_ACTIONS_UNVERIFIED and out["checks"] is None
    assert out["corporate_action_verification"]["reason"] == cav.ACQUISITION_DATE_UNVERIFIED


def test_limit_same_day_event_cannot_be_revalidated_by_position_review():
    buy_day = LBUY.astimezone(ISTANBUL_TZ).date()  # 2025-07-01
    src = aaa_source([event(ca.SPLIT, day=buy_day, **SPLIT_TERMS)])
    out = limit(provider=src)
    assert out["corporate_action_verification"]["reason"] == cav.EVENT_REQUIRES_POSITION_ADJUSTMENT
    assert out["state"] == lc.STATE_NOT_EVALUATED and out["block_code"] == pr.CORPORATE_ACTIONS_UNVERIFIED
    assert out["checks"] is None and out["price_used"] is None
    # Neden olay tarihi taşınmıyor: dondurulmuş review'in kendi filtresi (başlangıç < olay) aynı günkü olayı düşürüp
    # bu girdiyle değerlendirmeyi YAPARDI.
    lots = [p.model_dump() for _, p in VERIFIED_ROWS]
    review = pr.review({"evaluated_at": LNOW, "positions": lots,
                        "price_records": [{"symbol": "AAA", "session": "2025-07-11", "close": 110.0,
                                           "price_basis": pr.RAW_BASIS}],
                        "corporate_action_checks": {"AAA": {"checked_from": "2025-01-01", "checked_through": "2025-07-11",
                                                            "split_or_bonus_dates": [buy_day.isoformat()]}}})
    assert review["positions"][0]["status"] == pr.VALUED
    assert cav.position_review_check(cav.verify_corporate_actions("AAA", cav.acquisition_evidence(
        [p for _, p in VERIFIED_ROWS]), date(2025, 7, 11), src)) is None


def test_limit_split_later_in_holding_period_blocks():
    src = aaa_source([event(ca.SPLIT, day=date(2025, 7, 5), **SPLIT_TERMS)])
    assert limit(provider=src)["block_code"] == pr.CORPORATE_ACTIONS_UNVERIFIED


def test_limit_gate_order_and_no_source_call_when_earlier_gate_blocks():
    src = aaa_source()
    adjusted = limit(provider=src, basis=lc.PROVIDER_PRICE_BASIS)
    assert adjusted["block_code"] == pr.PRICE_BASIS_UNVERIFIED and src.calls == []
    unverified = limit(provider=src, price_provider=FakeProvider(identity="NONE"))
    assert unverified["block_code"] == lc.PRICE_IDENTITY_UNVERIFIED and src.calls == []
    assert adjusted["corporate_action_verification"] is None


# --- API düzeyi (sahte depo; gerçek Firestore yok) -----------------------------------------------------------------

def test_api_sell_snapshot_and_positions_reason(monkeypatch):
    from tests.test_partial_sale import lot, make_client, sell
    c, store = make_client(monkeypatch, [lot(100, 10.0)])
    rows = c.get("/portfolio/positions").json()["positions"]
    assert rows[0]["corporate_action_verification"]["reason"] == cav.COVERAGE_MISSING
    assert rows[0]["position_basis_verified"] is False and rows[0]["pnl_basis_verified"] is False
    tx = sell(c, 10).json()
    assert tx["basis_verified"] is False and tx["basis_verification_reason"] == cav.COVERAGE_MISSING
    assert tx["corporate_action_verifier_version"] == cav.VERIFIER_VERSION
    # Gelecekte gerçek kaynak bağlansa bile uygulamada kaydedilmiş lot doğrulanmaz.
    monkeypatch.setattr(cav, "default_corporate_action_provider", lambda: aaa_source())
    rows = c.get("/portfolio/positions").json()["positions"]
    assert rows[0]["corporate_action_verification"]["reason"] == cav.ACQUISITION_DATE_UNVERIFIED
    assert rows[0]["position_basis_verified"] is False


# --- eski (değişmez) satışın sonradan doğrulanması: YALNIZ MODEL, bağlı değil --------------------------------------

def record(verified, at, frm=FROM, thru=THROUGH, tx="t1", reason=None):
    return ca.TransactionBasisVerification(
        transaction_id=tx, user_id="u", asset="TUPRS", required_from=frm, required_through=thru, verified=verified,
        reason=reason or (cav.MATCH if verified else cav.COVERAGE_MISSING), checked_from=FROM if verified else None,
        checked_through=THROUGH if verified else None, source="fixture_source" if verified else None,
        isin=ISIN if verified else None, verifier_version=cav.VERIFIER_VERSION, verified_at=at)


def test_historical_verification_read_path():
    t1 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert cav.effective_transaction_verification("t1", False, [], FROM, THROUGH) == (False, None, None)
    ok, reason, rec = cav.effective_transaction_verification("t1", False, [record(False, t1), record(True, t2)],
                                                             FROM, THROUGH)
    assert ok and reason == cav.MATCH and rec.verified_at == t2
    assert not cav.effective_transaction_verification("t1", False, [record(True, t2, tx="t2")], FROM, THROUGH)[0]
    assert not cav.effective_transaction_verification("t1", False, [record(True, t2, frm=date(2026, 9, 1))],
                                                      FROM, THROUGH)[0]
    assert not cav.effective_transaction_verification("t1", False, [record(True, t1), record(False, t2)], FROM, THROUGH)[0]
    assert cav.effective_transaction_verification("t1", True, [], FROM, THROUGH)[0]


# --- serileştirme ----------------------------------------------------------------------------------------------------

def test_firestore_serialization_contract():
    cov = coverage()
    with pytest.raises(TypeError):
        firestore_helpers.encode_value(cov.model_dump())  # düz model_dump: `date` Firestore'a yazılamaz
    for model in (cov, event(ca.SPLIT, **SPLIT_TERMS), identity(), acquired(), record(True, BUY)):
        firestore_helpers.encode_value(model.firestore_dict())  # güvenli yöntem
    assert cov.firestore_dict()["checked_from"] == "2026-01-01"
    assert sorted(cov.firestore_dict()["covered_event_types"]) == sorted(ca.REQUIRED_EVENT_TYPES)
    firestore_helpers.encode_value(verify(full()).summary())
    tx = tuprs_sale(provider=full(), verified=True)
    assert isinstance(tx.corporate_action_checked_from, str)  # işlem anlık görüntüsü ISO metni
    firestore_helpers.encode_value(tx.model_dump())


def test_production_default_provider_never_returns_coverage():
    assert cav.default_corporate_action_provider().get_corporate_action_coverage("TUPRS", FROM, THROUGH) is None
