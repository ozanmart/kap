from __future__ import annotations

import pytest
from datetime import datetime, timezone
from kap.models.events import EventType
from kap.parsing.event_extractor import (
    detect_event_type,
    extract_events_from_text,
    extract_multiple_events_from_text,
    score_events,
)


def test_detect_event_types():
    # Buyback
    evt, ev = detect_event_type("Pay Geri Alım İşlemleri", "Şirketimizce pay geri alımı yapılmıştır.")
    assert evt == EventType.BUYBACK

    # Dividend
    evt, ev = detect_event_type("Kar Dağıtım Kararı", "2023 yılı net dağıtılabilir kâr payı ödemesi")
    assert evt == EventType.DIVIDEND

    # Capital increase
    evt, ev = detect_event_type("Sermaye Artırımı İşlemlerine İlişkin Bildirim", "Bedelsiz sermaye artırımı")
    assert evt == EventType.CAPITAL_INCREASE

    # Guidance
    evt, ev = detect_event_type("Geleceğe Yönelik Değerlendirmeler", "2024 yılı ciro ve FAVÖK beklentileri")
    assert evt == EventType.GUIDANCE


def test_extract_events_from_text():
    event = extract_events_from_text(
        disclosure_id="disc-123",
        disclosure_index=123,
        company_key="THYAO",
        title="Pay Geri Alım Programı",
        body_text="Şirketimiz Yönetim Kurulu 10.05.2024 tarihinde 1.000.000.000 TL fon ile hisse geri alımı kararı almıştır.",
    )
    assert event.company_key == "THYAO"
    assert event.event_type == EventType.BUYBACK
    assert "10.05.2024" in event.effective_dates
    assert len(event.amounts) == 1
    assert event.amounts[0]["value"] == 1000000000.0
    assert event.confidence > 0.7
    assert event.evidence_spans


def test_extract_multiple_events_keeps_evidence_spans():
    title = "Temettü ve Yönetim Kurulu Kararı"
    body = "Yönetim Kurulu, temettü dağıtımına ilişkin karar aldı."
    events = extract_multiple_events_from_text(
        disclosure_id="disc-multi",
        disclosure_index=456,
        company_key="THYAO",
        title=title,
        body_text=body,
    )

    assert {event.event_type for event in events} == {EventType.DIVIDEND, EventType.BOARD_DECISION}
    combined = f"{title}\n{body}"
    for event in events:
        assert event.evidence_spans
        for span in event.evidence_spans:
            assert combined[span.start:span.end] == span.text


def test_score_events():
    event1 = extract_events_from_text(
        disclosure_id="1",
        disclosure_index=1,
        company_key="THYAO",
        title="Pay Geri Alımı",
        body_text="Pay geri alım işlemi tamamlandı.",
        publish_date="01.09.2024 10:00:00",
    )
    event2 = extract_events_from_text(
        disclosure_id="2",
        disclosure_index=2,
        company_key="BIMAS",
        title="Kar Dağıtım",
        body_text="Temettü dağıtım kararı",
        publish_date="01.09.2024 10:00:00",
    )

    scored = score_events([event1, event2], as_of=datetime(2024, 9, 2, tzinfo=timezone.utc))
    assert len(scored) == 2
    assert scored[0].score > 0.0
