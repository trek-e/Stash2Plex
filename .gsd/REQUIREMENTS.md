# Requirements

## Active

### PROV-02 — Match endpoint accepts Plex scan request and returns match candidates from Stash via path mapping + fallback

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Match endpoint accepts Plex scan request and returns match candidates from Stash via path mapping + fallback

### PROV-03 — Metadata endpoint returns full scene metadata (title, summary, date, performers, tags, studio, artwork) for a matched scene

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Metadata endpoint returns full scene metadata (title, summary, date, performers, tags, studio, artwork) for a matched scene

### PROV-04 — Provider responds within Plex's 90-second timeout under concurrent scan load

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Provider responds within Plex's 90-second timeout under concurrent scan load

### PATH-03 — Startup roundtrip validation confirms each mapping rule correctly translates in both directions

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Startup roundtrip validation confirms each mapping rule correctly translates in both directions

### PATH-04 — Path mapping handles Plex's relative-to-library-root filename format

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Path mapping handles Plex's relative-to-library-root filename format

### GAPD-01 — Real-time gap detection flags files in Plex that Stash doesn't know about during Match requests

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Real-time gap detection flags files in Plex that Stash doesn't know about during Match requests

### GAPD-02 — Scheduled comparison identifies gaps in both directions (Plex→Stash and Stash→Plex)

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Scheduled comparison identifies gaps in both directions (Plex→Stash and Stash→Plex)

### GAPD-03 — Gap detection results available as a report (API endpoint or log output)

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Gap detection results available as a report (API endpoint or log output)

### GAPD-04 — Configurable comparison schedule (hourly/daily/weekly/manual)

- Status: active
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Configurable comparison schedule (hourly/daily/weekly/manual)

## Validated

### PROV-01 — Plex metadata provider registers as tv.plex.agents.custom.stash2plex with Match + Metadata features

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Plex metadata provider registers as tv.plex.agents.custom.stash2plex with Match + Metadata features

### PROV-05 — Provider deployed as Docker container with configurable Stash/Plex connection settings

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Provider deployed as Docker container with configurable Stash/Plex connection settings

### PATH-01 — Regex-based bidirectional path mapping translates Plex library paths to Stash scene paths and vice versa

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Regex-based bidirectional path mapping translates Plex library paths to Stash scene paths and vice versa

### PATH-02 — Path mapping supports multiple named rules applied in order

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Path mapping supports multiple named rules applied in order

### INFR-01 — Monorepo structure with shared_lib/ package importable by both plugin and provider

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Monorepo structure with shared_lib/ package importable by both plugin and provider

### INFR-02 — Stash GraphQL client in shared_lib/ queries scenes by path and by ID

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Stash GraphQL client in shared_lib/ queries scenes by path and by ID

### INFR-03 — Docker container handles Linux host networking (host.docker.internal workaround)

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Docker container handles Linux host networking (host.docker.internal workaround)

### INFR-04 — Provider configuration via environment variables and/or config file

- Status: validated
- Class: core-capability
- Source: inferred
- Primary Slice: none yet

Provider configuration via environment variables and/or config file

## Deferred

## Out of Scope
