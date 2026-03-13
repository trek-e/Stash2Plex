# M001: Migration

**Vision:** Stash-to-Plex metadata sync ecosystem: a Stash plugin that pushes metadata on changes (v1.x), plus a Plex metadata provider service that lets Plex pull metadata from Stash during scans (v2.0). Together they ensure metadata flows reliably in both directions.

## Success Criteria


## Slices

- [x] **S01: Gap Detection Engine** `risk:medium` `depends:[]`
  > After this: Build the gap detection engine core: a GapDetector class with three detection methods (empty metadata, stale sync, missing items) using TDD.
- [x] **S02: Manual Reconciliation** `risk:medium` `depends:[S01]`
  > After this: Wire the GapDetectionEngine into the Stash plugin task system so users can trigger reconciliation on-demand.
- [x] **S03: Automated Reconciliation Reporting** `risk:medium` `depends:[S02]`
  > After this: Implement automated reconciliation scheduling, configurable scope, and enhanced queue status reporting.
- [x] **S04: Circuit Breaker Persistence — completed 2026 02 15** `risk:medium` `depends:[S03]`
  > After this: unit tests prove Circuit Breaker Persistence — completed 2026-02-15 works
- [x] **S05: Health Check Infrastructure — completed 2026 02 15** `risk:medium` `depends:[S04]`
  > After this: unit tests prove Health Check Infrastructure — completed 2026-02-15 works
- [x] **S06: Recovery Detection & Automation — completed 2026 02 15** `risk:medium` `depends:[S05]`
  > After this: unit tests prove Recovery Detection & Automation — completed 2026-02-15 works
- [x] **S07: Graduated Recovery & Rate Limiting — completed 2026 02 15** `risk:medium` `depends:[S06]`
  > After this: unit tests prove Graduated Recovery & Rate Limiting — completed 2026-02-15 works
- [x] **S08: Outage Visibility & History — completed 2026 02 15** `risk:medium` `depends:[S07]`
  > After this: unit tests prove Outage Visibility & History — completed 2026-02-15 works
- [x] **S09: DLQ Recovery for Outage Jobs — completed 2026 02 15** `risk:medium` `depends:[S08]`
  > After this: unit tests prove DLQ Recovery for Outage Jobs — completed 2026-02-15 works
- [x] **S10: Foundation Shared Library** `risk:medium` `depends:[S09]`
  > After this: Create the shared_lib package with a bidirectional regex path mapping engine and comprehensive tests using TDD.
- [x] **S11: Provider Http Skeleton** `risk:medium` `depends:[S10]`
  > After this: Create the FastAPI provider application with configuration, structured logging, Plex protocol routes (manifest + stubs), and health endpoint.
- [ ] **S12: Match Endpoint** `risk:medium` `depends:[S11]`
  > After this: unit tests prove match-endpoint works
- [ ] **S13: Metadata Serve Route — Plex displays full scene metadata (title, date, studio, performers, tags, summary, artwork) after a successful match** `risk:medium` `depends:[S12]`
  > After this: unit tests prove Metadata Serve Route — Plex displays full scene metadata (title, date, studio, performers, tags, summary, artwork) after a successful match works
- [ ] **S14: Gap Detection — Scan Time gaps logged in real time; scheduled bi Directional comparison runs; gap report accessible via API endpoint** `risk:medium` `depends:[S13]`
  > After this: unit tests prove Gap Detection — Scan-time gaps logged in real time; scheduled bi-directional comparison runs; gap report accessible via API endpoint works
