# Contributing to Stash2Plex

Thank you for your interest in contributing to Stash2Plex! This is a Stash plugin that syncs metadata to Plex media libraries.

For an overview of the codebase architecture, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/trek-e/Stash2Plex.git
   cd Stash2Plex
   ```

2. Install runtime dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

**Note:** No code formatters (black, ruff) are configured. Follow existing code patterns and style.

For testing within Stash, see the [Stash plugin development documentation](https://docs.stashapp.cc/development/plugins/).

## Running Tests

Run all tests with coverage:
```bash
pytest
```

Run tests without coverage report:
```bash
pytest --no-cov
```

Run a specific test file:
```bash
pytest tests/test_specific.py
```

Skip slow tests:
```bash
pytest -m "not slow"
```

The project enforces **80% code coverage** (configured in `pytest.ini`). Tests are encouraged for new functionality, but not strictly required for small fixes.

## Pull Request Process

### Which branch to target

This repository has three branches:

- **`v1.x.x` is the release line.** This is where v1 bug fixes and improvements
  go. The published `Stash2Plex.zip` is built from `v1.x.x` by
  `.github/workflows/release.yml`. **If you are fixing behaviour in a released
  version, branch from and target `v1.x.x`** — that is the only way your fix
  reaches users.
- **`main` mirrors `v1.x.x`.** After each release, the release workflow copies
  `index.yml`, `Stash2Plex.yml` and `Stash2Plex.zip` from `v1.x.x` onto `main`.
  `main` hosts the index URL
  (`https://raw.githubusercontent.com/trek-e/Stash2Plex/main/index.yml`) that
  users add as a plugin source. **Do not target `main` directly with fixes** —
  it is a mirror, not a place to develop against, and changes made only there
  will not appear in the published zip. `.github/workflows/release-drift.yml`
  checks on every push to `main` or `v1.x.x` that the two remain identical.
- **`v2.x.x` is the v2 development line.** It holds ongoing refactor work and is
  not released from; nothing here reaches users until it is promoted to a
  release line.

1. Fork the repository
2. Create a feature branch from **`v1.x.x`** if you are fixing released
   behaviour, or from `v2.x.x` if you are contributing to the v2 refactor:
   ```bash
   git checkout -b feature/your-feature v1.x.x
   ```
3. Make your changes
4. Run tests to ensure they pass:
   ```bash
   pytest
   ```
5. Commit with a descriptive message
6. Push to your fork
7. Open a pull request against the branch you branched from (`v1.x.x` for bug
   fixes against released behaviour, `v2.x.x` for v2 work)

### PR Guidelines

- **Keep changes focused** - one feature or fix per PR
- **Include tests** when practical for new functionality
- **Update documentation** if adding user-facing features
- **Describe the change** - explain what and why in the PR description

## Code Style

- No automated formatters are configured - follow existing patterns
- Type hints are encouraged (the project uses Pydantic models)
- Add docstrings to public functions
- Keep functions focused and reasonably sized

## Getting Help

- Check [docs/troubleshoot.md](docs/troubleshoot.md) for common issues
- Search existing issues before opening a new one
- Open an issue for questions or feature discussions
