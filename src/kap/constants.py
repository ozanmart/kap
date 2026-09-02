from __future__ import annotations

from zoneinfo import ZoneInfo

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

# Base URLs
KAP_BASE_URL = "https://www.kap.org.tr"

# API Endpoints
ENDPOINT_DISCLOSURE_MAIN = "/{lang}/api/disclosure/list/main"
ENDPOINT_MEMBER_FILTER = "/{lang}/api/member/filter/{query}"
ENDPOINT_SEARCH_COMBINED = "/{lang}/api/search/combined"
ENDPOINT_COMPANY_DETAIL_SGBF = "/{lang}/api/company-detail/sgbf-data/{member_oid}/{notification_type}/{range_value}"
ENDPOINT_COMPANY_DISCLOSURES_BY_TYPE = "/{lang}/api/company-detail/disclosures/{disclosure_type}/{member_oid}"
ENDPOINT_EXPECTED_DISCLOSURES = "/{lang}/api/expected-disclosure-inquiry/company"
ENDPOINT_DISCLOSURE_PAGE = "/{lang}/Bildirim/{disclosure_index}"
ENDPOINT_DISCLOSURE_SUBJECTS = "/{lang}/api/disclosure/subjects/{disclosure_class}/IGS"
ENDPOINT_HISTORICAL_DISCLOSURES = "/{lang}/api/disclosure/members/byCriteria"
ENDPOINT_FINANCIAL_DOWNLOAD_XLS = "/{lang}/api/home-financial/download-file/{member_oid}/{year}/T"

# Listing Pages
LISTING_ROUTES = {
    "bist_sirketler": "/{lang}/bist-sirketler",
    "endeksler": "/{lang}/Endeksler",
    "sektorler": "/{lang}/Sektorler",
    "pazarlar": "/{lang}/Pazarlar",
}

# Member Type Codes
MEMBER_TYPE_CODES: dict[str, str] = {
    "bist_sirketleri": "IGS",
    "yatirim_kuruluslari": "YK",
    "portfoy_yonetim_sirketleri": "PYS",
    "duzenleyici_denetleyici_kurumlar": "DDK",
    "kripto_varlik_hizmet_saglayici": "KVH",
    "diger_kap_uyeleri": "DG",
}
DEFAULT_MEMBER_TYPE_CODE = "IGS"

# Disclosure Class & Type Codes
DISCLOSURE_TYPE_CODES: dict[str, str] = {
    "ozel_durum_aciklamasi": "ODA",
    "finansal_rapor": "FR",
    "duzenleyici_kurum_bildirimleri": "DUY",
    "diger": "DG",
    "hak_kullanimlari": "CA",
}

COMPANY_NOTIFICATION_TYPE_CODES: dict[str, str] = {
    "tum_bildirimler": "ALL",
    "finansal_raporlar": "FR",
    "ozel_durum_aciklamalari": "ODA",
    "duzenleyici_kurum_bildirimleri": "DUY",
    "diger": "DG",
}

# Specific Disclosure Type Filters for Company Detail API
VALID_COMPANY_DISCLOSURE_TYPES: dict[str, str] = {
    "FAR": "Faaliyet Raporu (Activity Reports)",
    "KYUR": "Kurumsal Yönetim Uyum Raporu (Corporate Governance)",
    "SUR": "Sürdürülebilirlik Raporu (Sustainability)",
    "KDP": "Kar Dağıtım Politikası (Dividend Policy)",
    "DEG": "Değerleme Raporu (Valuation Reports)",
    "UNV": "Unvan Değişikliği (Company Name Change)",
    "SYI": "Sermaye Piyasası Aracı İhracı (Securities Issuance)",
}

# Common Subject OIDs
SUBJECT_OID_FINANCIAL_REPORT = "4028328c594bfdca01594c0af9aa0057"
SUBJECT_OID_ACTIVITY_REPORT = "4028328d594c04f201594c5155dd0076"

# Financial Statement Role Mapping
STATEMENT_NAME_BY_ROLE: dict[str, str] = {
    "210015": "balance_sheet",
    "310003": "income_statement",
    "520003": "cash_flow",
    "610000": "equity_changes",
}

# Tradeable BIST Index Codes for Filtering
PUBLICLY_TRADEABLE_INDEX_CODES = {"XUTUM", "XYORT"}
