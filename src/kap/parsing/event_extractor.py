from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from ..models.events import DerivedEvent, EvidenceSpan, EventType, ScoredCompany
from .html_parser import clean_text, extract_amounts, extract_dates


EVENT_KEYWORDS: dict[EventType, tuple[str, ...]] = {
    EventType.BUYBACK: (
        "geri al",
        "pay geri al",
        "hisse geri al",
        "payların geri alınması",
        "share buyback",
    ),
    EventType.CAPITAL_INCREASE: (
        "sermaye artır",
        "bedelli",
        "bedelsiz",
        "sermaye artırımı",
        "tahsisli sermaye",
        "capital increase",
    ),
    EventType.DIVIDEND: (
        "kar payı",
        "temettü",
        "kar dağıtım",
        "dividend",
        "kâr payı dağıtım",
    ),
    EventType.GUIDANCE: (
        "beklenti",
        "öngörü",
        "guidance",
        "hedef",
        "geleceğe yönelik değerlendirmeler",
        "forecast",
    ),
    EventType.BOARD_DECISION: (
        "yönetim kurulu kararı",
        "yönetim kurulu",
        "karar alındı",
        "board decision",
    ),
    EventType.GENERAL_ASSEMBLY: (
        "genel kurul",
        "olağan genel kurul",
        "olağanüstü genel kurul",
        "general assembly",
    ),
    EventType.TRAFFIC_RESULTS: (
        "trafik sonuç",
        "yolcu sayısı",
        "üretim ve satış",
        "operasyonel sonuçlar",
    ),
    EventType.FINANCIAL_REPORT: (
        "finansal rapor",
        "mali tablo",
        "faaliyet raporu",
        "financial report",
    ),
    EventType.VALUATION_REPORT: (
        "değerleme raporu",
        "gayrimenkul değerleme",
        "valuation report",
    ),
}

EVENT_BASE_SCORES: dict[EventType, float] = {
    EventType.BUYBACK: 2.5,
    EventType.DIVIDEND: 2.0,
    EventType.GUIDANCE: 1.5,
    EventType.FINANCIAL_REPORT: 1.2,
    EventType.TRAFFIC_RESULTS: 1.0,
    EventType.GENERAL_ASSEMBLY: 0.8,
    EventType.BOARD_DECISION: 0.5,
    EventType.VALUATION_REPORT: 0.5,
    EventType.CAPITAL_INCREASE: -0.2,
    EventType.OTHER: 0.1,
}


def _evidence_spans(
    title: str | None,
    body_text: str | None,
    keywords: tuple[str, ...],
) -> list[EvidenceSpan]:
    title_text = clean_text(title)
    body = clean_text(body_text)
    sections: list[tuple[str, str, int]] = []
    if title_text:
        sections.append(("title", title_text, 0))
    if body:
        sections.append(("body", body, len(title_text) + 1 if title_text else 0))

    spans: list[EvidenceSpan] = []
    seen: set[tuple[str, int, int]] = set()
    for source, text, offset in sections:
        for keyword in keywords:
            for match in re.finditer(re.escape(keyword), text, flags=re.IGNORECASE):
                key = (source, match.start(), match.end())
                if key in seen:
                    continue
                seen.add(key)
                spans.append(
                    EvidenceSpan(
                        text=text[match.start():match.end()],
                        start=offset + match.start(),
                        end=offset + match.end(),
                        source=source,
                    )
                )
    spans.sort(key=lambda span: (span.start, span.end))
    return spans


def detect_event_types(
    title: str | None,
    body_text: str | None,
    disclosure_type: str | None = None,
) -> list[tuple[EventType, list[str], list[EvidenceSpan]]]:
    """Detect every event type supported by the title/body and return evidence spans."""
    combined = f"{clean_text(title).casefold()}\n{clean_text(body_text).casefold()}"

    if (disclosure_type or "").upper() == "FR":
        return [
            (
                EventType.FINANCIAL_REPORT,
                ["disclosure_type:FR"],
                [EvidenceSpan(text="disclosure_type:FR", start=0, end=len("disclosure_type:FR"), source="metadata")],
            )
        ]

    matches: list[tuple[EventType, list[str], list[EvidenceSpan]]] = []
    for event_type, keywords in EVENT_KEYWORDS.items():
        matched = [k for k in keywords if k.casefold() in combined]
        if matched:
            matches.append((event_type, matched, _evidence_spans(title, body_text, keywords)))

    return matches or [(EventType.OTHER, [], [])]


def detect_event_type(
    title: str | None,
    body_text: str | None,
    disclosure_type: str | None = None,
) -> tuple[EventType, list[str]]:
    """Backward-compatible single-event view of :func:`detect_event_types`."""
    event_type, evidence, _ = detect_event_types(title, body_text, disclosure_type)[0]
    return event_type, evidence


def parse_kap_datetime(publish_date: str | None) -> datetime | None:
    """Parse KAP timestamp string formatted as 'DD.MM.YYYY HH:MM:SS' or 'DD.MM.YYYY'."""
    if not publish_date:
        return None
    raw = clean_text(publish_date)
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def extract_events_from_text(
    *,
    disclosure_id: str,
    disclosure_index: int,
    company_key: str,
    title: str | None,
    body_text: str | None,
    disclosure_type: str | None = None,
    publish_date: str | None = None,
) -> DerivedEvent:
    """Extract the primary structured event from disclosure text."""
    return extract_multiple_events_from_text(
        disclosure_id=disclosure_id,
        disclosure_index=disclosure_index,
        company_key=company_key,
        title=title,
        body_text=body_text,
        disclosure_type=disclosure_type,
        publish_date=publish_date,
    )[0]


def extract_multiple_events_from_text(
    *,
    disclosure_id: str,
    disclosure_index: int,
    company_key: str,
    title: str | None,
    body_text: str | None,
    disclosure_type: str | None = None,
    publish_date: str | None = None,
) -> list[DerivedEvent]:
    """Extract all supported corporate events from one disclosure."""
    dates = extract_dates(body_text)
    amounts = extract_amounts(body_text)
    events: list[DerivedEvent] = []
    for event_type, evidence, evidence_spans in detect_event_types(title, body_text, disclosure_type):
        confidence = 0.5
        if event_type != EventType.OTHER:
            confidence += 0.25
        if evidence:
            confidence += 0.15
        if amounts or dates:
            confidence += 0.1
        confidence = max(0.1, min(confidence, 0.99))
        events.append(
            DerivedEvent(
                event_id=f"evt-{disclosure_index}-{event_type.value.lower()}",
                disclosure_id=str(disclosure_id or disclosure_index),
                disclosure_index=int(disclosure_index),
                company_key=(company_key or "UNKNOWN").upper(),
                event_type=event_type,
                title=title,
                publish_date=publish_date,
                effective_dates=dates,
                amounts=amounts,
                confidence=confidence,
                evidence=evidence,
                evidence_spans=evidence_spans,
            )
        )
    return events


def score_events(
    events: list[DerivedEvent],
    as_of: datetime | None = None,
) -> list[ScoredCompany]:
    """Score and aggregate derived corporate events per company with exponential time decay."""
    now = as_of or datetime.now(timezone.utc)
    by_company: dict[str, dict[str, Any]] = {}

    for evt in events:
        company = evt.company_key or "UNKNOWN"
        base_score = EVENT_BASE_SCORES.get(evt.event_type, EVENT_BASE_SCORES[EventType.OTHER])

        decay = 1.0
        dt = parse_kap_datetime(evt.publish_date)
        if dt is not None:
            age_days = max((now - dt).total_seconds() / 86400.0, 0.0)
            # 30-day decay constant, not a half-life: a 30-day-old event keeps
            # ~37% of its weight, and the floor stops old news reaching zero.
            decay = max(0.2, math.exp(-age_days / 30.0))

        event_score = round(base_score * float(evt.confidence) * decay, 4)
        evt.score = event_score

        if company not in by_company:
            by_company[company] = {
                "company_key": company,
                "score": 0.0,
                "event_count": 0,
                "reasons": [],
            }

        by_company[company]["score"] += event_score
        by_company[company]["event_count"] += 1
        by_company[company]["reasons"].append({
            "event_id": evt.event_id,
            "event_type": evt.event_type.value,
            "event_score": event_score,
            "confidence": evt.confidence,
            "title": evt.title,
            "disclosure_index": evt.disclosure_index,
        })

    results = [
        ScoredCompany(
            company_key=data["company_key"],
            score=round(data["score"], 4),
            event_count=data["event_count"],
            reasons=data["reasons"],
        )
        for data in by_company.values()
    ]
    results.sort(key=lambda x: x.score, reverse=True)
    return results
