from __future__ import annotations

import pytest
from kap.parsing.html_parser import (
    clean_text,
    extract_amounts,
    extract_dates,
    html_to_text,
    normalize_numeric_value,
)


def test_html_to_text():
    html = """
    <html>
        <head><style>.test { color: red; }</style></head>
        <body>
            <script>console.log('ignored');</script>
            <h1>Başlık</h1>
            <p>Bu bir KAP bildirim metnidir.&nbsp;&nbsp;Detaylar aşağıdadır.</p>
        </body>
    </html>
    """
    text = html_to_text(html)
    assert "Başlık" in text
    assert "Bu bir KAP bildirim metnidir." in text
    assert "console.log" not in text
    assert "color: red" not in text


def test_normalize_numeric_value():
    assert normalize_numeric_value("1.234.567,89") == 1234567.89
    assert normalize_numeric_value("1234567") == 1234567
    assert normalize_numeric_value("(50.000,50)") == -50000.50
    assert normalize_numeric_value("-100.000") == -100000
    assert normalize_numeric_value("-") is None
    assert normalize_numeric_value("--") is None
    assert normalize_numeric_value(None) is None


def test_extract_dates():
    text = "Toplantı 15.03.2024 tarihinde saat 10:00'da yapılacaktır. Kayıt tarihi 14.03.2024 olarak belirlenmiştir."
    dates = extract_dates(text)
    assert "15.03.2024" in dates
    assert "14.03.2024" in dates


def test_extract_amounts():
    text = "Şirketimiz 500.000.000 TL nominal değerli pay geri alımı ve 1.500.000 USD tutarında yatırım kararı almıştır."
    amounts = extract_amounts(text)
    assert len(amounts) == 2
    assert amounts[0]["value"] == 500000000.0
    assert amounts[0]["currency"] == "TL"
    assert amounts[1]["value"] == 1500000.0
    assert amounts[1]["currency"] == "USD"
