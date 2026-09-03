from __future__ import annotations

import pytest

from kap.models.company import CompanyGeneralInfo, FreeFloatInfo, Shareholder, Subsidiary
from scripts.validate_live_kap import _check_feed, _check_profile


def _valid_profile(*, free_float: list[FreeFloatInfo]) -> CompanyGeneralInfo:
    return CompanyGeneralInfo(
        member_oid="member-oid",
        ticker="BIMAS",
        major_shareholders=[
            Shareholder(name_or_title="A", share_ratio=10),
            Shareholder(name_or_title="B", share_ratio=6),
        ],
        free_float=free_float,
        subsidiaries=[Subsidiary(company_title=f"Subsidiary {index}") for index in range(5)],
    )


def test_live_profile_validation_accepts_empty_free_float() -> None:
    _check_profile(_valid_profile(free_float=[]))


def test_live_profile_validation_checks_only_present_free_float_rows() -> None:
    with pytest.raises(AssertionError, match="free float row"):
        _check_profile(_valid_profile(free_float=[FreeFloatInfo(stock_code="BIMAS")]))


def test_live_feed_validation_accepts_empty_today_feed_but_rejects_wrong_schema() -> None:
    _check_feed([])

    with pytest.raises(AssertionError, match="today feed schema"):
        _check_feed({})

    with pytest.raises(AssertionError, match="today feed schema"):
        _check_feed([object()])
