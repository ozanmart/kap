from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..models.company import Company
from ..models.disclosure import Disclosure
from ..models.events import DerivedEvent
from ..models.financials import FinancialLineItem, FinancialStatement


class KapDatabase:
    """Embedded SQLite database for storing, indexing, and querying KAP data locally."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS companies (
                    ticker TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    city TEXT,
                    auditor TEXT,
                    company_id TEXT,
                    summary_page TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS disclosures (
                    disclosure_index INTEGER PRIMARY KEY,
                    disclosure_id TEXT,
                    publish_date TEXT,
                    company_title TEXT,
                    stock_code TEXT,
                    related_stocks TEXT,
                    title TEXT,
                    disclosure_type TEXT,
                    disclosure_class TEXT,
                    disclosure_category TEXT,
                    url TEXT,
                    raw_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_disc_stock ON disclosures(stock_code);
                CREATE INDEX IF NOT EXISTS idx_disc_date ON disclosures(publish_date);
                CREATE INDEX IF NOT EXISTS idx_disc_type ON disclosures(disclosure_type);

                CREATE TABLE IF NOT EXISTS financials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    disclosure_index INTEGER,
                    stock_code TEXT,
                    statement_name TEXT,
                    taxonomy_code TEXT,
                    metric_name_tr TEXT,
                    metric_name_en TEXT,
                    period_label TEXT,
                    period_index INTEGER,
                    value_numeric REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_fin_stock ON financials(stock_code);
                CREATE INDEX IF NOT EXISTS idx_fin_disc ON financials(disclosure_index);

                CREATE TABLE IF NOT EXISTS derived_events (
                    event_id TEXT PRIMARY KEY,
                    disclosure_index INTEGER,
                    company_key TEXT,
                    event_type TEXT,
                    title TEXT,
                    publish_date TEXT,
                    confidence REAL,
                    score REAL,
                    raw_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_evt_company ON derived_events(company_key);
                CREATE INDEX IF NOT EXISTS idx_evt_type ON derived_events(event_type);
            """)

    def close(self) -> None:
        self.conn.close()

    # ── Upserts ──────────────────────────────────────────────────────────────

    def save_companies(self, companies: list[Company]) -> int:
        with self.conn:
            cur = self.conn.executemany(
                """
                INSERT INTO companies (ticker, name, city, auditor, company_id, summary_page)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    name=excluded.name,
                    city=excluded.city,
                    auditor=excluded.auditor,
                    company_id=excluded.company_id,
                    summary_page=excluded.summary_page,
                    updated_at=CURRENT_TIMESTAMP
                """,
                [
                    (c.ticker, c.name, c.city, c.auditor, c.company_id, c.summary_page)
                    for c in companies
                ],
            )
            return cur.rowcount

    def save_disclosures(self, disclosures: list[Disclosure]) -> int:
        with self.conn:
            cur = self.conn.executemany(
                """
                INSERT INTO disclosures (
                    disclosure_index, disclosure_id, publish_date, company_title,
                    stock_code, related_stocks, title, disclosure_type, disclosure_class,
                    disclosure_category, url, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(disclosure_index) DO UPDATE SET
                    publish_date=excluded.publish_date,
                    company_title=excluded.company_title,
                    stock_code=excluded.stock_code,
                    title=excluded.title,
                    raw_json=excluded.raw_json
                """,
                [
                    (
                        d.disclosure_index,
                        d.disclosure_id,
                        d.publish_date,
                        d.company_title,
                        d.stock_code,
                        d.related_stocks,
                        d.title,
                        d.disclosure_type,
                        d.disclosure_class,
                        d.disclosure_category,
                        d.url,
                        json.dumps(d.raw, ensure_ascii=False),
                    )
                    for d in disclosures
                    if d.disclosure_index > 0
                ],
            )
            return cur.rowcount

    def save_financial_statement(self, statement: FinancialStatement) -> int:
        rows = [
            (
                item.disclosure_index,
                statement.stock_code,
                item.statement_name,
                item.taxonomy_code,
                item.metric_name_tr,
                item.metric_name_en,
                item.period_label,
                item.period_index,
                item.value_numeric,
            )
            for item in statement.items
        ]
        with self.conn:
            self.conn.execute("DELETE FROM financials WHERE disclosure_index = ?", (statement.disclosure_index,))
            cur = self.conn.executemany(
                """
                INSERT INTO financials (
                    disclosure_index, stock_code, statement_name, taxonomy_code,
                    metric_name_tr, metric_name_en, period_label, period_index, value_numeric
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return cur.rowcount

    def save_derived_events(self, events: list[DerivedEvent]) -> int:
        with self.conn:
            cur = self.conn.executemany(
                """
                INSERT INTO derived_events (
                    event_id, disclosure_index, company_key, event_type,
                    title, publish_date, confidence, score, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    confidence=excluded.confidence,
                    score=excluded.score,
                    raw_json=excluded.raw_json
                """,
                [
                    (
                        e.event_id,
                        e.disclosure_index,
                        e.company_key,
                        e.event_type.value,
                        e.title,
                        e.publish_date,
                        e.confidence,
                        e.score,
                        json.dumps(e.model_dump(), ensure_ascii=False),
                    )
                    for e in events
                ],
            )
            return cur.rowcount

    # ── Queries ──────────────────────────────────────────────────────────────

    def query_disclosures(
        self,
        stock_code: str | None = None,
        disclosure_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM disclosures WHERE 1=1"
        params: list[Any] = []
        if stock_code:
            sql += " AND UPPER(stock_code) = ?"
            params.append(stock_code.upper().strip())
        if disclosure_type:
            sql += " AND UPPER(disclosure_type) = ?"
            params.append(disclosure_type.upper().strip())
        sql += " ORDER BY disclosure_index DESC LIMIT ?"
        params.append(limit)

        cur = self.conn.execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]

    def query_financials(self, stock_code: str, statement_name: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM financials WHERE UPPER(stock_code) = ?"
        params: list[Any] = [stock_code.upper().strip()]
        if statement_name:
            sql += " AND statement_name = ?"
            params.append(statement_name.lower().strip())
        sql += " ORDER BY disclosure_index DESC, period_index ASC"

        cur = self.conn.execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]
