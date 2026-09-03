from __future__ import annotations

from kap.scrapers.financials import parse_financial_statement_html


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


def test_html_financials_recognize_non_general_sector_taxonomy_tables() -> None:
    """Holding/bank-sector KAP reports use ``tbl_holding_role_``/``tbl_bank_role_``
    classes instead of ``tbl_general_role_``; both must parse."""
    html = """
    <html><body>
      <div>Sunum Para Birimi: Türk Lirası Ölçek: Milyon</div>
      <table class="financial-table tbl_holding_role_210015">
        <tr><td class="context-header"><span class="multi-language-content content-tr">31.12.2025</span></td></tr>
        <tr><td class="taxonomy-field-name">cash|Cash</td>
            <td class="taxonomy-field-title"><span class="multi-language-content content-tr">Nakit</span></td>
            <td class="taxonomy-context-value"><span class="taxonomy-label-field">2,0</span></td></tr>
      </table>
    </body></html>
    """
    statement = parse_financial_statement_html(html, disclosure_index=11)
    assert statement.period_labels == ["31.12.2025"]
    assert statement.statement_counts.get("balance_sheet") == 1
    assert statement.items[0].value_numeric == 2.0
