# License and provenance audit

Audit date: 2026-09-03

## Findings

- The current KAP package metadata and repository `LICENSE` declare MIT, selected by the maintainer on 2026-09-03.
- The local reference project at `Downloads/bist-investment-agent-main` declares `Proprietary` in its `pyproject.toml`.
- The release documentation describes this project as a synthesis of reference repositories and identifies `bist-investment-agent` as a reference for the SSR parser, financial statement parser, event extractor, and SQLite architecture.
- There is no checked-in provenance manifest, permission record, or file-by-file clean-room rewrite record in this repository.

## Decision

The maintainer selected MIT for this repository. This audit records the
remaining provenance evidence gap; it does not override upstream terms or grant
redistribution rights. Before publishing a release, retain written permission
or a clean-room provenance record for any code adapted from a differently
licensed reference.

This audit does not grant any license, and it is not a substitute for legal review. Before publishing, add one of the following evidence packages:

1. Written permission or a compatible upstream license covering the reused code; or
2. A clean-room provenance record identifying independently implemented files, excluded source material, and review sign-off for any rewritten components.

## Scope limitations

This audit inspected the local repository documentation and the local reference project's metadata. It did not perform a legal determination or certify that every line is independently authored.
