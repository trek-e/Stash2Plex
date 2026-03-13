# T02: 24-provider-http-skeleton 02

**Slice:** S11 — **Milestone:** M001

## Description

Create Docker infrastructure to containerize and run the FastAPI provider, with cross-platform host networking support.

Purpose: Package the provider application built in Plan 01 as a Docker container that Plex can reach. This is the deployment artifact that makes the provider operational — without it, the FastAPI app is just code.

Output: Dockerfile, docker-compose.yml, .dockerignore — `docker-compose up` brings the provider online and reachable at http://localhost:9090.

## Must-Haves

- [ ] "docker-compose build completes successfully with provider image built"
- [ ] "docker-compose up starts the provider container and it becomes healthy"
- [ ] "Provider container is reachable from host at http://localhost:9090"
- [ ] "GET http://localhost:9090/ from host returns the MediaProvider manifest"
- [ ] "GET http://localhost:9090/health from host returns health JSON"
- [ ] "host.docker.internal resolves inside the container on both Linux and macOS"
- [ ] "Container starts with only S2P_STASH_URL and S2P_STASH_API_KEY set (no YAML file required)"

## Files

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`
