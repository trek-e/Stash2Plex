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

1. Fork the repository
2. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature
   ```
3. Make your changes
4. Run tests to ensure they pass:
   ```bash
   pytest
   ```
5. Commit with a descriptive message
6. Push to your fork
7. Open a pull request against the `main` branch

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
