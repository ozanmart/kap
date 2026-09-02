# License and provenance audit

Audit date: 2026-09-02

## Findings

- The current KAP package metadata declares `Proprietary`; no MIT redistribution claim is made.
- The local reference project at `/Users/omerozanmart/Downloads/bist-investment-agent-main` declares `Proprietary` in its `pyproject.toml`.
- `KAP_REPORT.md` describes this project as a synthesis of the reference repositories and specifically identifies `bist-investment-agent` as a reference for the SSR parser, financial statement parser, event extractor, and SQLite architecture.
- There is no checked-in provenance manifest, permission record, or file-by-file clean-room rewrite record in this repository.

## Decision

The package metadata, README, and repository `LICENSE` notice use a conservative `Proprietary` / provenance-pending status. The project must not be redistributed as MIT until the source owner grants compatible redistribution rights or the affected implementation is independently rewritten and documented.

This audit does not grant any license, and it is not a substitute for legal review. Before publishing, add one of the following evidence packages:

1. Written permission or a compatible upstream license covering the reused code; or
2. A clean-room provenance record identifying independently implemented files, excluded source material, and review sign-off for any rewritten components.

## Scope limitations

This audit inspected the local repository, `KAP_REPORT.md`, and the local reference project's metadata. It did not perform a legal determination or certify that every line is independently authored.
