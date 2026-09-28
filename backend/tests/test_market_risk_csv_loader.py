"""MARKET-RISK araştırma CSV yükleyicisi: kayıtlı sayıların bit düzeyinde sadık okunması.

Gerçek TUPRS satırları (kayıtlı sepet girdisinden) küçük yerel girdiler olarak
kullanılır; ağ yok.
"""

import math

import pandas as pd
import pytest

from app.engines.technical.data_quality import InvalidOHLCVError, check_raw_ohlcv_integrity
from app.engines.technical.session_timing import ISTANBUL_TZ
from app.research.market_risk_shadow.event_review import load_saved_provider_csv

HEADER = "Date,Open,High,Low,Close,Volume\n"
TUPRS_2023_11_29 = "2023-11-29 00:00:00+03:00,119.85745537844713,120.77415655851685,118.3296356201172,118.32963562011719,25001562\n"
TUPRS_2024_11_27 = "2024-11-27 00:00:00+03:00,130.10005448377174,130.62395264993268,127.91716766357423,127.91716766357422,14741691\n"
VALID_2024_11_26 = "2024-11-26 00:00:00+03:00,129.05228663269028,129.83812065094872,128.35376010352422,128.9649658203125,13472575\n"


def _write(tmp_path, *lines):
    path = tmp_path / "X_provider_ohlcv.csv"
    path.write_text(HEADER + "".join(lines), encoding="utf-8")
    return path


def test_value_changed_by_default_reader_is_kept_bit_exact(tmp_path):
    path = _write(tmp_path, "2024-11-26 00:00:00+03:00,0.30000000000000004,1.0,0.1,0.30000000000000004,1\n")
    default = pd.read_csv(path, index_col=0)["Open"].iloc[0]
    loaded = load_saved_provider_csv(path)["Open"].iloc[0]
    assert float(default).hex() != (0.1 + 0.2).hex()  # önceki okuyucunun farkı (kurulu pandas)
    assert float(loaded).hex() == (0.1 + 0.2).hex()


def test_tuprs_2024_11_27_violation_is_kept_and_rejected(tmp_path):
    df = load_saved_provider_csv(_write(tmp_path, TUPRS_2024_11_27))
    assert df["Low"].iloc[0] > df["Close"].iloc[0]
    with pytest.raises(InvalidOHLCVError):
        check_raw_ohlcv_integrity(df, "TUPRS")


def test_tuprs_2023_11_29_violation_hidden_by_old_reader_is_now_visible(tmp_path):
    path = _write(tmp_path, TUPRS_2023_11_29)
    old = pd.read_csv(path, index_col=0)
    assert not old["Low"].iloc[0] > old["Close"].iloc[0]  # önceki okuyucu ihlali gizliyordu
    new = load_saved_provider_csv(path)
    assert new["Low"].iloc[0] > new["Close"].iloc[0]
    with pytest.raises(InvalidOHLCVError):
        check_raw_ohlcv_integrity(new, "TUPRS")


def test_valid_row_missing_value_timezone_and_order_are_preserved(tmp_path):
    path = _write(tmp_path, VALID_2024_11_26, "2024-11-28 00:00:00+03:00,,,,,0\n")
    df = load_saved_provider_csv(path)
    check_raw_ohlcv_integrity(df.iloc[:1], "TUPRS")  # geçerli OHLC reddedilmez
    assert math.isnan(df["Close"].iloc[1])  # eksik değer doldurulmaz
    assert str(df.index.tz) == str(ISTANBUL_TZ)
    assert [ts.date().isoformat() for ts in df.index] == ["2024-11-26", "2024-11-28"]
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
