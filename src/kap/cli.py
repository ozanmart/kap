from __future__ import annotations

import json
import sys
import click

from .client import KapClient


def _short_error(exc: Exception) -> str:
    """Render deterministic CLI errors without response bodies or tracebacks."""
    message = " ".join(str(exc).split()) or type(exc).__name__
    return f"{type(exc).__name__}: {message}"[:300]


class _KapCLIGroup(click.Group):
    def invoke(self, ctx: click.Context):
        try:
            return super().invoke(ctx)
        except click.exceptions.Exit:
            # Click uses Exit(0) for --help. Preserve the successful exit code
            # instead of rendering it as a generic CLI error.
            raise
        except click.ClickException:
            raise
        except Exception as exc:
            raise click.ClickException(_short_error(exc)) from None


def _json_model(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


@click.group(cls=_KapCLIGroup)
@click.version_option(package_name="kap")
def main():
    """KAP (Kamuyu Aydınlatma Platformu) & Borsa Istanbul Agent-Native CLI."""
    pass


@main.command()
@click.argument("query")
@click.option("--online", is_flag=True, default=False, help="Perform live online search via KAP endpoint instead of local index")
def search(query: str, online: bool):
    """Search BIST companies by ticker or name."""
    with KapClient() as client:
        results = client.search_companies(query, online=online)
        if not results:
            click.echo(f"No companies matching '{query}' found.")
            return

        click.echo(f"Found {len(results)} matching companies:\n")
        for c in results:
            click.echo(f"  • {click.style(c.ticker, bold=True, fg='green'):<10} {c.name} (City: {c.city or '-'})")


@main.command()
@click.argument("ticker")
def info(ticker: str):
    """Show detailed company profile, shareholders, float, and subsidiaries."""
    with KapClient() as client:
        info = client.get_company_general_info(ticker)

        click.echo(click.style(f"\n=== {info.company_title or ticker} ({ticker.upper()}) ===", bold=True, fg="cyan"))
        click.echo(f"Activity Field : {info.activity_field or '-'}")
        click.echo(f"Sector         : {info.sector or '-'}")
        click.echo(f"Market         : {info.market or '-'}")
        click.echo(f"Indices        : {info.indices or '-'}")
        click.echo(f"Auditor        : {info.auditor or '-'}")
        click.echo(f"Website        : {info.website or '-'}")

        if info.major_shareholders:
            click.echo(click.style("\nMajor Shareholders (>= 5%):", bold=True))
            for s in info.major_shareholders:
                ratio_str = f"{s.share_ratio:.2f}%" if s.share_ratio is not None else "-"
                click.echo(f"  • {s.name_or_title:<45} Share: {ratio_str}")

        if info.free_float:
            click.echo(click.style("\nFree Float:", bold=True))
            for f in info.free_float:
                ratio_str = f"{f.float_ratio:.2f}%" if f.float_ratio is not None else "-"
                click.echo(f"  • Float Ratio: {ratio_str} (Nominal: {f.nominal_value:,.2f} TL)" if f.nominal_value else f"  • Float Ratio: {ratio_str}")

        if info.subsidiaries:
            click.echo(click.style(f"\nSubsidiaries & Financial Assets ({len(info.subsidiaries)}):", bold=True))
            for sub in info.subsidiaries[:10]:
                ratio_str = f"{sub.share_ratio:.2f}%" if sub.share_ratio is not None else "-"
                click.echo(f"  • {sub.company_title:<45} Stake: {ratio_str}")
            if len(info.subsidiaries) > 10:
                click.echo(f"  ... and {len(info.subsidiaries) - 10} more.")


@main.command()
@click.option("--member-type", default="bist_sirketleri", help="Filter by member type (default: bist_sirketleri)")
@click.option("--json-out", is_flag=True, help="Output raw JSON format")
def today(member_type: str, json_out: bool):
    """List today's live KAP announcements."""
    with KapClient() as client:
        items = client.get_today_disclosures(member_type=member_type)
        if json_out:
            click.echo(json.dumps([d.model_dump() for d in items], ensure_ascii=False, indent=2))
            return

        click.echo(f"Today's KAP Announcements ({len(items)} items):\n")
        for d in items:
            stock = click.style(f"[{d.stock_code or 'GENERAL'}]", bold=True, fg="yellow")
            time_part = d.publish_date.split()[-1] if d.publish_date and " " in d.publish_date else ""
            click.echo(f"  {time_part:<8} {stock:<15} {d.title or '-'} (#{d.disclosure_index})")


@main.command()
@click.option("--limit", default=25, help="Number of announcements to fetch")
@click.option("--ticker", default=None, help="Filter by stock ticker")
def latest(limit: int, ticker: str | None):
    """List latest global KAP announcements."""
    with KapClient() as client:
        items = client.get_latest_disclosures(limit=limit, ticker=ticker)
        click.echo(f"Latest KAP Announcements ({len(items)} items):\n")
        for d in items:
            stock = click.style(f"[{d.stock_code or 'GENERAL'}]", bold=True, fg="yellow")
            click.echo(f"  {d.publish_date or '-':<20} {stock:<15} {d.title or '-'} (#{d.disclosure_index})")


@main.command()
@click.argument("ticker")
@click.option("--type", "notification_type", default="ALL", help="ALL, FR, ODA, DUY, DG")
@click.option("--days", default=365, help="Lookback in days")
@click.option("--limit", default=20, help="Max items")
def disclosures(ticker: str, notification_type: str, days: int, limit: int):
    """List historical announcements for a specific company."""
    with KapClient() as client:
        items = client.get_company_disclosures(ticker, notification_type=notification_type, range_days=days, limit=limit)
        click.echo(f"Historical Announcements for {ticker.upper()} ({len(items)} items):\n")
        for d in items:
            click.echo(f"  • {d.publish_date or '-':<20} [{d.disclosure_type or '-'}] {d.title} (#{d.disclosure_index})")


@main.command()
@click.argument("disclosure_index", type=click.IntRange(min=1))
@click.option("--max-chars", type=click.IntRange(min=1), default=None, help="Limit rendered disclosure body characters")
@click.option("--json-out", is_flag=True, help="Output JSON")
def detail(disclosure_index: int, max_chars: int | None, json_out: bool):
    """Read a disclosure's normalized metadata, body, and attachments."""
    with KapClient() as client:
        item = client.get_disclosure_detail(disclosure_index)
        if json_out:
            payload = _json_model(item)
            if max_chars is not None:
                payload["content_text"] = (payload.get("content_text") or "")[:max_chars]
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        body = item.content_text or ""
        if max_chars is not None:
            body = body[:max_chars]
        click.echo(f"{item.publish_date or '-'} [{item.stock_code or 'GENERAL'}] {item.title or '-'}")
        disclosure_type = item.disclosure_type or item.disclosure_class or "-"
        click.echo(f"Company: {item.company_title or '-'} | Type: {disclosure_type}")
        click.echo(body)
        rendered_urls: set[str] = set()
        for attachment in item.attachment_metadata:
            file_name = attachment.get("file_name") or attachment.get("name") or attachment.get("fileName") or "-"
            url = attachment.get("url") or attachment.get("download_url") or attachment.get("downloadUrl") or ""
            if url:
                rendered_urls.add(str(url))
            click.echo(f"Attachment: {file_name} {url}".rstrip())
        for url in item.attachment_urls:
            if url not in rendered_urls:
                click.echo(f"Attachment: {url}")


@main.command()
@click.option("--days", default=90, help="Days ahead (default: 90)")
@click.option("--ticker", default=None, help="Filter by ticker")
def calendar(days: int, ticker: str | None):
    """View expected earnings announcement calendar."""
    with KapClient() as client:
        items = client.get_expected_disclosures(days_ahead=days, ticker_or_oid=ticker)
        click.echo(f"Expected Earnings Announcements Next {days} Days ({len(items)} items):\n")
        for r in items:
            stock = click.style(f"[{r.stock_code or 'MEMBER'}]", bold=True, fg="green")
            period = r.period or f"{r.year or ''}"
            dates = f"{r.start_date or ''} -> {r.end_date or ''}"
            subject = r.subject or "-"
            click.echo(f"  • {stock:<12} {r.company_title or '-'} | Subject: {subject:<32} Period: {period:<15} Dates: {dates}")


@main.command()
@click.argument("disclosure_index", type=int)
def statement(disclosure_index: int):
    """Parse and view financial statement tables for an announcement index."""
    with KapClient() as client:
        stmt = client.get_financial_statement(disclosure_index)
        click.echo(f"\nFinancial Statement for #{disclosure_index} ({stmt.stock_code or 'UNKNOWN'}):")
        click.echo(f"Periods: {', '.join(stmt.period_labels)}")
        for stmt_name, count in stmt.statement_counts.items():
            click.echo(f"  • {stmt_name}: {count} line items")


@main.command()
@click.argument("ticker")
@click.option("--year", type=click.IntRange(min=2000, max=2100), required=True)
@click.option("--period", default="annual", show_default=True, help="annual, Q1, Q2, Q3, or Q4")
@click.option("--json-out", is_flag=True, help="Output JSON")
def financials(ticker: str, year: int, period: str, json_out: bool):
    """Find and parse the correct financial report for ticker/year/period."""
    with KapClient() as client:
        stmt = client.get_financials(ticker, year, period)
        if json_out:
            click.echo(json.dumps(_json_model(stmt), ensure_ascii=False, indent=2))
            return
        click.echo(f"Financials {stmt.stock_code or ticker.upper()} {year} {period} (#{stmt.disclosure_index})")
        click.echo(f"Currency: {stmt.currency or '-'} | Scale: {stmt.scale or 1}")
        click.echo(f"Periods: {', '.join(stmt.period_labels)}")
        click.echo(f"Line items: {len(stmt.items)}")


@main.command()
@click.argument("category", type=click.Choice(["indices", "sectors", "markets"], case_sensitive=False))
@click.option("--json-out", is_flag=True, help="Output JSON")
def taxonomy(category: str, json_out: bool):
    """List KAP indices, sectors, or trading markets."""
    with KapClient() as client:
        getters = {
            "indices": client.get_indices,
            "sectors": client.get_sectors,
            "markets": client.get_markets,
        }
        rows = getters[category.lower()]()
        if json_out:
            click.echo(json.dumps([_json_model(row) for row in rows], ensure_ascii=False, indent=2))
            return
        click.echo(f"KAP {category.title()} ({len(rows)} items):")
        for row in rows:
            code = (
                getattr(row, "code", None)
                or getattr(row, "market_oid", None)
                or getattr(row, "sector_oid", None)
                or "-"
            )
            name = getattr(row, "name", None) or getattr(row, "market_name", None) or "-"
            click.echo(f"  • {code}: {name}")


@main.command()
@click.argument("disclosure_index", type=int)
def events(disclosure_index: int):
    """Analyze a disclosure index for derived corporate events (buyback, dividends, etc.)."""
    with KapClient() as client:
        detected = client.extract_events_many(
            disclosure_detail=client.get_disclosure_detail(disclosure_index)
        )
        for event in detected:
            click.echo(click.style(f"\n=== Detected Event: {event.event_type.value} ===", bold=True, fg="green"))
            click.echo(f"Company    : {event.company_key}")
            click.echo(f"Title      : {event.title}")
            click.echo(f"Confidence : {event.confidence:.2%}")
            click.echo(f"Score      : {event.score}")
            if event.effective_dates:
                click.echo(f"Dates      : {', '.join(event.effective_dates)}")
            if event.amounts:
                click.echo(f"Amounts    : {event.amounts}")
            if event.evidence:
                click.echo(f"Evidence   : {', '.join(event.evidence)}")


@main.command()
def mcp():
    """Start the Model Context Protocol (MCP) server over stdio for AI agent integration."""
    import asyncio
    from .tools import run_mcp_stdio_server
    asyncio.run(run_mcp_stdio_server())


if __name__ == "__main__":
    main()
