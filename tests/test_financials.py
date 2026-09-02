from __future__ import annotations

import io
import zipfile

from kap.scrapers.financials import FinancialsScraper, parse_financial_statement_html


def test_xls_archive_preserves_each_period_column() -> None:
    html = """
    <html><body>
      <table>
        <tr><th>Kalem</th><th>31.12.2024</th><th>31.12.2023</th></tr>
        <tr><td>Nakit ve Nakit Benzerleri</td><td>1.234,50</td><td>987,25</td></tr>
      </table>
    </body></html>
    """.encode("utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_ref:
        zip_ref.writestr("balance_sheet.xls", html)

    result = FinancialsScraper()._parse_zip_xls_content(archive.getvalue(), year="2024")

    report = result["balance_sheet"]
    assert report["period_labels"] == ["31.12.2024", "31.12.2023"]
    assert report["items"] == [
        {
            "key": "Nakit ve Nakit Benzerleri",
            "value": 1234.5,
            "value_text": "1.234,50",
            "period_label": "31.12.2024",
            "period_index": 0,
            "table_index": 0,
        },
        {
            "key": "Nakit ve Nakit Benzerleri",
            "value": 987.25,
            "value_text": "987,25",
            "period_label": "31.12.2023",
            "period_index": 1,
            "table_index": 0,
        },
    ]


def test_xls_archive_supports_cp1254_and_fallback_file_period() -> None:
    html = """
    <html><body>
      <table><tr><th>Kalem</th><th>Tutar</th></tr>
      <tr><td>Özkaynaklar</td><td>10.000</td></tr></table>
    </body></html>
    """.encode("cp1254")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_ref:
        zip_ref.writestr("2024_annual.xls", html)

    report = FinancialsScraper()._parse_zip_xls_content(archive.getvalue(), year="2024")["2024_annual"]

    assert report["period_labels"] == ["2024_annual"]
    assert report["items"][0]["period_label"] == "2024_annual"
    assert report["items"][0]["value"] == 10000


def test_html_financials_keep_periods_and_presentation_units() -> None:
    html = """
    <html><body>
      <div>Sunum Para Birimi: Türk Lirası Ölçek: Milyon</div>
      <table class="financial-table tbl_general_role_210015">
        <tr><td class="context-header"><span class="multi-language-content content-tr">31.12.2024</span></td>
            <td class="context-header"><span class="multi-language-content content-tr">31.12.2023</span></td></tr>
        <tr><td class="taxonomy-field-name">cash|Cash</td>
            <td class="taxonomy-field-title"><span class="multi-language-content content-tr">Nakit</span><span class="multi-language-content content-en">Cash</span></td>
            <td class="taxonomy-context-value"><span class="taxonomy-label-field">1,5</span></td>
            <td class="taxonomy-context-value"><span class="taxonomy-label-field">1,2</span></td></tr>
      </table>
    </body></html>
    """
    statement = parse_financial_statement_html(html, disclosure_index=10)
    assert statement.currency == "TRY"
    assert statement.scale == 1_000_000
    assert statement.period_labels == ["31.12.2024", "31.12.2023"]
    assert statement.items[0].value_numeric == 1.5
    assert statement.items[0].normalized_value == 1_500_000
