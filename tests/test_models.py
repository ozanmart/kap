from __future__ import annotations

import pytest
from kap.models.company import Company, CompanyGeneralInfo, Shareholder, FreeFloatInfo, Subsidiary
from kap.models.disclosure import Disclosure, ExpectedDisclosure, DisclosureSubject
from kap.models.financials import FinancialLineItem, FinancialStatement
from kap.models.events import DerivedEvent, EventType, ScoredCompany
from kap.models.market import Indice, Sector, SubSector, Market


def test_company_model():
    comp = Company(
        ticker="THYAO",
        name="TÜRK HAVA YOLLARI A.O.",
        city="İSTANBUL",
        auditor="PwC",
        company_id="4028e4a240e8d16e0140e90c62950047",
    )
    assert comp.code == "THYAO"
    assert comp.ticker == "THYAO"
    assert comp.city == "İSTANBUL"


def test_general_info_model():
    info = CompanyGeneralInfo(
        member_oid="12345",
        ticker="GARAN",
        company_title="T. GARANTİ BANKASI A.Ş.",
        website="https://garantibbva.com.tr",
        sector="Mali Kuruluşlar",
        major_shareholders=[
            Shareholder(name_or_title="BBVA", share_ratio=85.97, voting_ratio=85.97)
        ],
        free_float=[
            FreeFloatInfo(stock_code="GARAN", float_ratio=14.03, nominal_value=500000000.0)
        ],
        subsidiaries=[
            Subsidiary(company_title="Garanti Emeklilik", activity_field="Emeklilik", share_ratio=84.91)
        ],
    )
    assert info.ticker == "GARAN"
    assert len(info.major_shareholders) == 1
    assert info.major_shareholders[0].share_ratio == 85.97
    assert len(info.free_float) == 1
    assert len(info.subsidiaries) == 1


def test_financial_statement_model():
    stmt = FinancialStatement(
        disclosure_index=123456,
        stock_code="BIMAS",
        company_title="BİM BİRLEŞİK MAĞAZALAR A.Ş.",
        period_labels=["31.12.2024", "31.12.2023"],
        statement_counts={"balance_sheet": 2},
        items=[
            FinancialLineItem(
                disclosure_index=123456,
                statement_role_code="210015",
                statement_name="balance_sheet",
                taxonomy_code="Dönen Varlıklar",
                metric_name_tr="DÖNEN VARLIKLAR",
                metric_name_en="CURRENT ASSETS",
                period_label="31.12.2024",
                period_index=0,
                value_numeric=55000000000.0,
            ),
            FinancialLineItem(
                disclosure_index=123456,
                statement_role_code="210015",
                statement_name="balance_sheet",
                taxonomy_code="Nakit ve Nakit Benzerleri",
                metric_name_tr="Nakit ve Nakit Benzerleri",
                metric_name_en="Cash and Cash Equivalents",
                period_label="31.12.2024",
                period_index=0,
                value_numeric=12000000000.0,
            ),
        ],
    )
    dict_repr = stmt.to_dict()
    assert "balance_sheet" in dict_repr
    assert dict_repr["balance_sheet"]["DÖNEN VARLIKLAR"] == 55000000000.0


def test_financial_statement_model_preserves_repeated_metric_periods():
    stmt = FinancialStatement(
        disclosure_index=123456,
        items=[
            FinancialLineItem(
                disclosure_index=123456,
                statement_role_code="210015",
                statement_name="balance_sheet",
                taxonomy_code="Cash",
                metric_name_tr="NAKİT",
                period_label="31.12.2024",
                period_index=0,
                value_numeric=100,
            ),
            FinancialLineItem(
                disclosure_index=123456,
                statement_role_code="210015",
                statement_name="balance_sheet",
                taxonomy_code="Cash",
                metric_name_tr="NAKİT",
                period_label="31.12.2023",
                period_index=1,
                value_numeric=80,
            ),
        ],
    )

    assert stmt.to_dict()["balance_sheet"]["NAKİT"] == {
        "31.12.2024": 100,
        "31.12.2023": 80,
    }
    assert stmt.to_period_dict()["balance_sheet"]["NAKİT"]["31.12.2023"] == 80
