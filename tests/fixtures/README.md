# Captured KAP payload fixtures

These small fixtures are reduced excerpts of public KAP responses captured on
2026-09-02. The values and field names are retained from the live responses;
large unrelated page sections were removed so the parser tests stay reviewable.

- `kap_registry_live.html`: `https://www.kap.org.tr/tr/bist-sirketler`
- `kap_feed_live.json`: `POST https://www.kap.org.tr/tr/api/disclosure/list/main`
  (captured 2026-09-03, kept complete: the benchmark's normalization scenario
  feeds it to every repository, and a trimmed payload would fail a strict
  consumer for the capture's shortcomings rather than its own)
- `kap_detail_live.html`: `https://www.kap.org.tr/tr/Bildirim/1656913`
- `kap_financial_live.html`: financial-table excerpt from `Bildirim/1656913`
- `kap_company_general_live.html`: `https://www.kap.org.tr/tr/sirket-bilgileri/genel/4028e4a2420327a4014209c55161144d`

The capture date is part of the fixture provenance. Tests must validate schema
and parsing behavior, not assume that these disclosures remain current.
