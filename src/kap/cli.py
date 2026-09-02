from __future__ import annotations

import json
import sys
import click

from .client import KapClient


@click.group()
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
        try:
            info = client.get_company_general_info(ticker)
        except Exception as e:
            click.echo(click.style(f"Error fetching info for {ticker}: {e}", fg="red"))
            return

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
            click.echo(f"  • {stock:<12} {r.company_title or '-'} | Period: {period:<15} Dates: {dates}")


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
@click.argument("disclosure_index", type=int)
def events(disclosure_index: int):
    """Analyze a disclosure index for derived corporate events (buyback, dividends, etc.)."""
    with KapClient() as client:
        event = client.extract_events(disclosure_detail=client.get_disclosure_detail(disclosure_index))
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
