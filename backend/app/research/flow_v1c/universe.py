"""FLOW 1C dış doğrulama evreni — KAP endeks bileşenleri PDF'inden.

Kaynak: https://www.kap.org.tr/tr/api/company/indices/pdf/endeksler (Technical
V1 protokolünün BIST100 üyeliği için kullandığı AYNI resmî KAP uç noktası).

Kural (getirilere bakılmadan, protokolde kilitli):
    external = BIST TÜM üyeleri − FLOW 1B dondurulmuş 100 sembol

BIST TÜM bölümü = PDF metnindeki EN UZUN kesintisiz-sıralı bölüm; ek
tutarlılık şartları: "BIST TÜM" başlığı altında olmalı, PDF'teki BIST 100
bölümünü tamamen kapsamalı. Resmî "BIST TÜM-100" bölümü KULLANILMAZ: metin
çıkarımında 458 kayıtta kesiliyor (TÜM−BIST100 = 484; eksik 26 sembolün
tamamı alfabenin V–Z kısmı → sayfa/çıkarım kesilmesi). Bu anomali evren
artefaktında açıkça kaydedilir.

PDF→metin dönüşümü (pypdf) bu modülün DIŞINDADIR — pypdf proje bağımlılığı
değildir; `--text` ile önceden çıkarılmış metin verilir. Ayrıştırma saf ve
test edilebilir.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.research.canonical_hash import content_sha256
from app.research.flow_v1.dataset import load_frozen_universe

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
UNIVERSE_FILE = RESOURCES_DIR / "flow_v1c_universe.json"
SOURCE_URL = "https://www.kap.org.tr/tr/api/company/indices/pdf/endeksler"

_ENTRY = re.compile(r"^(\d+) ([A-Z0-9]{3,6}) ")


def parse_sections(text: str) -> list[dict]:
    """Sıra numarası 1'e döndüğünde yeni bölüm başlar. Her bölüm: en yakın
    önceki `BIST ...` başlığı, kodlar ve sıra numaralarının kesintisiz olup
    olmadığı."""
    sections: list[dict] = []
    current = None
    last_title = None
    for raw in text.split("\n"):
        line = raw.strip()
        match = _ENTRY.match(line)
        if match:
            number, code = int(match.group(1)), match.group(2)
            if number == 1:
                current = {"title": last_title, "codes": [], "numbers": []}
                sections.append(current)
            if current is not None:
                current["codes"].append(code)
                current["numbers"].append(number)
        elif line.startswith("BIST"):
            last_title = line
    for s in sections:
        s["sequential"] = s["numbers"] == list(range(1, len(s["numbers"]) + 1))
        s["unique"] = len(set(s["codes"])) == len(s["codes"])
    return sections


def select_bist_tum(sections: list[dict]) -> list[str]:
    tum = [s for s in sections if s["title"] == "BIST TÜM" and s["sequential"] and s["unique"]]
    if not tum:
        raise ValueError("BIST TÜM bölümü bulunamadı")
    chosen = max(tum, key=lambda s: len(s["codes"]))
    longest_overall = max(len(s["codes"]) for s in sections)
    if len(chosen["codes"]) != longest_overall:
        raise ValueError("BIST TÜM, PDF'teki en uzun bölüm değil — ayrıştırma şüpheli")
    b100 = [s for s in sections if s["title"] == "BIST 100" and len(s["codes"]) == 100 and s["sequential"]]
    if len(b100) != 1 or not set(b100[0]["codes"]) <= set(chosen["codes"]):
        raise ValueError("BIST 100 bölümü BIST TÜM tarafından kapsanmıyor — ayrıştırma şüpheli")
    return list(chosen["codes"])


def build_external_universe(tum_codes: list[str], discovery_symbols: list[str]) -> list[str]:
    """BIST TÜM − keşif evreni; sıralı, tekil. Kesişim 0 garanti edilir."""
    external = sorted(set(tum_codes) - set(discovery_symbols))
    overlap = set(external) & set(discovery_symbols)
    if overlap:  # yapısal olarak imkânsız; savunma amaçlı
        raise ValueError(f"keşif/doğrulama kesişimi: {sorted(overlap)}")
    return external


def load_external_universe() -> tuple[list[str], dict]:
    artifact = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    symbols = artifact["external_symbols"]
    discovery, _ = load_frozen_universe()
    if set(symbols) & set(discovery):
        raise ValueError("dış evren keşif evreniyle kesişiyor")
    if content_sha256(symbols) != artifact["external_symbols_sha256"]:
        raise ValueError("dış evren hash uyuşmazlığı")
    return symbols, artifact


def main() -> None:
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    text = Path(args["--text"]).read_text(encoding="utf-8")
    sections = parse_sections(text)
    tum = select_bist_tum(sections)
    discovery, tech_protocol_sha = load_frozen_universe()
    b100 = next(s["codes"] for s in sections if s["title"] == "BIST 100" and len(s["codes"]) == 100)
    tum100 = [s for s in sections if s["title"] == "BIST TÜM-100"]
    external = build_external_universe(tum, discovery)
    artifact = {
        "artifact": "FLOW_V1C_EXTERNAL_UNIVERSE",
        "source_url": SOURCE_URL,
        "source_retrieved_at_utc": args["--retrieved-at"],
        "source_pdf_sha256": args["--pdf-sha256"],
        "source_pdf_pages": int(args["--pages"]),
        "text_extraction": f"pypdf {args['--pypdf-version']} PdfReader.extract_text(), outside project dependencies",
        "selection_rule": "external = BIST TÜM members (KAP endeksler PDF) minus FLOW 1B frozen 100 (technical_v1_protocol_v1 universe). Decided before any FLOW 1C outcome.",
        "bist_tum_count": len(tum),
        "pdf_bist100_equals_frozen_100": set(b100) == set(discovery),
        "discovery_universe_protocol_sha256": tech_protocol_sha,
        "official_tum_minus_100_section_parsed_count": len(tum100[0]["codes"]) if tum100 else None,
        "official_tum_minus_100_anomaly": "The official 'BIST TÜM-100' section parses to 458 sequential entries while BIST TÜM − BIST 100 = 484; the 26 missing symbols are exactly the alphabetical V–Z tail, consistent with a PDF page/extraction cut. The section is therefore NOT used; the rule above is used instead.",
        "external_count": len(external),
        "overlap_with_discovery": 0,
        "external_symbols": external,
        "external_symbols_sha256": content_sha256(external),
        "bist_tum_symbols_sha256": content_sha256(sorted(tum)),
    }
    UNIVERSE_FILE.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: artifact[k] for k in ("bist_tum_count", "external_count", "pdf_bist100_equals_frozen_100")}))


if __name__ == "__main__":
    main()
