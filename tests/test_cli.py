from __future__ import annotations

import json

from click.testing import CliRunner

from kap.cli import main
from kap.client import KapClient
from kap.models.disclosure import DisclosureDetail
from kap.models.financials import FinancialStatement
from kap.models.market import Indice
from kap.scrapers.base import KapConnectionError


def test_cli_detail_json_limits_body_and_keeps_attachments(monkeypatch) -> None:
    detail = DisclosureDetail(
        disclosure_index=42,
        title="Finansal Rapor",
        content_text="abcdefghij",
        url="https://www.kap.org.tr/tr/Bildirim/42",
        attachment_urls=["https://www.kap.org.tr/a.pdf"],
    )
    monkeypatch.setattr(KapClient, "get_disclosure_detail", lambda self, index: detail)

    result = CliRunner().invoke(main, ["detail", "42", "--max-chars", "5", "--json-out"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["content_text"] == "abcde"
    assert payload["attachment_urls"] == ["https://www.kap.org.tr/a.pdf"]


def test_cli_financials_and_taxonomy_json(monkeypatch) -> None:
    statement = FinancialStatement(
        disclosure_index=99,
        stock_code="THYAO",
        period_labels=["31.12.2025"],
        currency="TRY",
        scale=1_000_000,
    )
    monkeypatch.setattr(KapClient, "get_financials", lambda self, ticker, year, period: statement)
    monkeypatch.setattr(
        KapClient,
        "get_indices",
        lambda self: [Indice(code="XU100", name="BIST 100", companies=["THYAO"])],
    )

    financials = CliRunner().invoke(main, ["financials", "THYAO", "--year", "2025", "--json-out"])
    taxonomy = CliRunner().invoke(main, ["taxonomy", "indices", "--json-out"])

    assert financials.exit_code == 0
    assert json.loads(financials.output)["currency"] == "TRY"
    assert taxonomy.exit_code == 0
    assert json.loads(taxonomy.output)[0]["companies"] == ["THYAO"]


def test_cli_network_error_is_short_and_has_no_traceback(monkeypatch) -> None:
    monkeypatch.setattr(
        KapClient,
        "get_indices",
        lambda self: (_ for _ in ()).throw(KapConnectionError("TLS handshake timed out")),
    )

    result = CliRunner().invoke(main, ["taxonomy", "indices"])

    assert result.exit_code != 0
    assert "KapConnectionError: TLS handshake timed out" in result.output
    assert "Traceback" not in result.output


def test_cli_rejects_invalid_disclosure_index_before_network() -> None:
    result = CliRunner().invoke(main, ["detail", "0"])

    assert result.exit_code == 2
    assert "0 is not in the range" in result.output


def test_cli_subcommand_help_exits_successfully() -> None:
    result = CliRunner().invoke(main, ["detail", "--help"])

    assert result.exit_code == 0
    assert "Read a disclosure's normalized metadata" in result.output
