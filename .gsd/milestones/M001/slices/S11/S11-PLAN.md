# S11: Provider Http Skeleton

**Goal:** Create the FastAPI provider application with configuration, structured logging, Plex protocol routes (manifest + stubs), and health endpoint.
**Demo:** Create the FastAPI provider application with configuration, structured logging, Plex protocol routes (manifest + stubs), and health endpoint.

## Must-Haves


## Tasks

- [x] **T01: 24-provider-http-skeleton 01** `est:8min`
  - Create the FastAPI provider application with configuration, structured logging, Plex protocol routes (manifest + stubs), and health endpoint.

Purpose: Establish the complete Python application that implements the Plex Custom Metadata Provider HTTP protocol, with proper config management and observability. This is the application code that Plan 02 will containerize.

Output: A runnable `provider/` package with all routes, config, logging, and models — ready for Docker packaging.
- [x] **T02: 24-provider-http-skeleton 02** `est:2min`
  - Create Docker infrastructure to containerize and run the FastAPI provider, with cross-platform host networking support.

Purpose: Package the provider application built in Plan 01 as a Docker container that Plex can reach. This is the deployment artifact that makes the provider operational — without it, the FastAPI app is just code.

Output: Dockerfile, docker-compose.yml, .dockerignore — `docker-compose up` brings the provider online and reachable at http://localhost:9090.

## Files Likely Touched

- `provider/__init__.py`
- `provider/config.py`
- `provider/logging_config.py`
- `provider/models.py`
- `provider/main.py`
- `provider/routes/__init__.py`
- `provider/routes/manifest.py`
- `provider/routes/match.py`
- `provider/routes/metadata.py`
- `provider/routes/health.py`
- `provider/requirements.txt`
- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
