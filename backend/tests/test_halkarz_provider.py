import pytest

from app.services.ipo.halkarz_provider import HalkArzProvider, parse_detail_page, parse_listing_page

_LISTING_HTML = """
<html><body>
<ul class="halka-arz-list">
  <li><article class="index-list">
    <div class="il-badge"><div class="il-new">Yeni!</div></div>
    <a href="https://halkarz.com/abc-a-s/" title="ABC A.Ş."><img src="x.jpg"></a>
    <div class="il-content">
      <span class="il-bist-kod"></span>
      <h3 class="il-halka-arz-sirket"><a href="https://halkarz.com/abc-a-s/">ABC A.Ş.</a></h3>
      <span class="il-halka-arz-tarihi"><time datetime="Hazırlanıyor...">Hazırlanıyor...</time></span>
    </div>
  </article></li>
  <li><article class="index-list">
    <div class="il-badge"></div>
    <a href="https://halkarz.com/veyas/" title="VEYAS A.Ş."><img src="y.jpg"></a>
    <div class="il-content">
      <span class="il-bist-kod">VEYAS</span>
      <h3 class="il-halka-arz-sirket"><a href="https://halkarz.com/veyas/">VEYAS A.Ş.</a></h3>
      <span class="il-halka-arz-tarihi"><time datetime="12-13-14 Ağustos 2026">12-13-14 Ağustos 2026</time></span>
    </div>
  </article></li>
</ul>
</body></html>
"""

_DETAIL_HTML = """
<html><body>
<article class="index-list detail-page">
  <div class="il-content">
    <h2 class="il-bist-kod">VEYAS</h2>
    <h1 class="il-halka-arz-sirket">VEYAS A.Ş.</h1>
  </div>
</article>
<table class="sp-table">
  <tr><td><em>Halka Arz Tarihi : </em></td><td><time>12-13-14 Ağustos 2026</time></td></tr>
  <tr><td><em>Halka Arz Fiyatı/Aralığı : </em></td><td><strong>136,00 TL</strong></td></tr>
  <tr><td><em>Bist Kodu : </em></td><td><strong>VEYAS</strong></td></tr>
</table>
<table class="as-table">
  <tr><td rowspan="2"><b>Yatırımcı Grubu</b></td><td colspan="3"><b>Dağıtım</b></td></tr>
  <tr><td><b>Kişi</b></td><td><b>Lot</b></td><td><b>Oran</b></td></tr>
  <tr><td>Yurt İçi Bireysel</td><td>364.592</td><td>15.533.163</td><td>%35</td></tr>
  <tr><td>Toplam</td><td>365.280</td><td>44.375.000</td><td>%100</td></tr>
</table>
</body></html>
"""


def test_parse_listing_page_extracts_all_fields():
    listings = parse_listing_page(_LISTING_HTML)

    assert len(listings) == 2
    first = listings[0]
    assert first.company_name == "ABC A.Ş."
    assert first.bist_code is None
    assert first.detail_url == "https://halkarz.com/abc-a-s/"
    assert first.date_text == "Hazırlanıyor..."
    assert first.badge_text == "Yeni!"

    second = listings[1]
    assert second.bist_code == "VEYAS"
    assert second.date_text == "12-13-14 Ağustos 2026"
    assert second.badge_text is None


def test_parse_listing_page_returns_empty_list_when_no_container():
    assert parse_listing_page("<html><body>no list here</body></html>") == []


def test_parse_detail_page_extracts_fields_and_demand_results():
    detail = parse_detail_page(_DETAIL_HTML)

    assert detail is not None
    assert detail.company_name == "VEYAS A.Ş."
    assert detail.bist_code == "VEYAS"
    assert detail.fields["Halka Arz Fiyatı/Aralığı"] == "136,00 TL"
    assert detail.fields["Bist Kodu"] == "VEYAS"
    assert len(detail.demand_results) == 2
    assert detail.demand_results[0] == {
        "grup": "Yurt İçi Bireysel",
        "kisi": "364.592",
        "lot": "15.533.163",
        "oran": "%35",
    }
    assert detail.demand_results[1]["grup"] == "Toplam"


def test_parse_detail_page_returns_none_when_no_header():
    assert parse_detail_page("<html><body>empty</body></html>") is None


def test_get_detail_rejects_non_halkarz_url():
    with pytest.raises(ValueError):
        HalkArzProvider().get_detail("https://evil.example.com/phish")


def test_parse_listing_page_strips_lone_surrogates():
    # Canlı testte halkarz.com'dan (ya da aradaki bir katmandan) ara sıra
    # geçersiz surrogate karakter geldiği görüldü (ör. "A.Ş." içinde) — bu
    # Flutter'ın kesin UTF-8 JSON çözücüsünü çökertir, bu yüzden temizlenmeli.
    html = _LISTING_HTML.replace("ABC A.Ş.", "ABC A.\udc9e.")

    listings = parse_listing_page(html)

    name = listings[0].company_name
    assert "\udc9e" not in name
    assert not any(0xD800 <= ord(c) <= 0xDFFF for c in name)
