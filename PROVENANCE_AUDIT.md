# License and provenance audit

Audit date: 2026-09-03 (corrected 2026-09-03).

## Findings

- The current KAP package metadata and repository `LICENSE` declare MIT,
  selected by the maintainer.
- The local reference project at `Downloads/bist-investment-agent-main`,
  used during development as an architectural reference (SSR parser,
  financial statement parser, event extractor, SQLite architecture), is
  authored by the same maintainer as this repository. Its `Proprietary`
  metadata reflects that project's own unrelated distribution terms, not a
  third-party claim over this codebase.

## Decision

Because both projects share the same author, there is no third-party
license conflict or provenance gap to resolve. MIT stands as declared.

## Scope limitations

This audit inspected the local repository documentation and the local
reference project's metadata. It did not perform a broader legal
determination.
