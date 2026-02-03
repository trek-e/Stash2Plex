# Phase 6: API Documentation - Research

**Researched:** 2026-02-03
**Domain:** Python API documentation generation from docstrings
**Confidence:** HIGH

## Summary

This phase focuses on generating API reference documentation from Python docstrings for the PlexSync Stash plugin. The codebase already has well-written Google-style docstrings across all modules (sync_queue, validation, plex, worker, hooks), making it ready for automated documentation generation.

The recommended approach is MkDocs with mkdocstrings-python, which provides a modern, Markdown-based documentation workflow that integrates naturally with the existing docs/ folder containing user documentation (install.md, config.md, troubleshoot.md) and architecture documentation (ARCHITECTURE.md). This aligns with the project's concise documentation style and avoids the complexity of Sphinx's reStructuredText.

The primary work involves: (1) auditing existing docstrings for completeness, (2) configuring mkdocs.yml with mkdocstrings, and (3) creating API reference pages that link to the existing architecture documentation.

**Primary recommendation:** Use MkDocs + Material theme + mkdocstrings-python for API documentation generation from existing Google-style docstrings.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| mkdocs | 1.6+ | Static site generator | De facto standard for Markdown docs, simple config |
| mkdocs-material | 9.7+ | Documentation theme | Best-in-class UX, widely adopted, responsive design |
| mkdocstrings | 1.0+ | Auto-doc from source | Language-agnostic, excellent Python support |
| mkdocstrings-python | 2.0+ | Python handler | Griffe-based AST parsing, Google docstring support |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| griffe | (dep) | Python AST parser | Auto-installed with mkdocstrings-python |
| pymdown-extensions | (dep) | Markdown extensions | Auto-installed with mkdocs-material |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| MkDocs | Sphinx | More powerful but steeper learning curve, RST-centric |
| mkdocstrings | sphinx-autodoc | Better Sphinx integration but more complex setup |
| Material theme | ReadTheDocs theme | RTD is simpler but less polished |

**Installation:**
```bash
pip install mkdocs-material mkdocstrings[python]
```

**Add to requirements-dev.txt:**
```
mkdocs-material>=9.7.0
mkdocstrings[python]>=1.0.0
```

## Architecture Patterns

### Recommended Project Structure
```
PlexSync/
├── docs/                    # Documentation source (existing)
│   ├── install.md          # User guide (existing)
│   ├── config.md           # Configuration (existing)
│   ├── troubleshoot.md     # Troubleshooting (existing)
│   ├── ARCHITECTURE.md     # System architecture (existing)
│   └── api/                # NEW: API reference pages
│       ├── index.md        # API overview
│       ├── sync_queue.md   # sync_queue module docs
│       ├── validation.md   # validation module docs
│       ├── plex.md         # plex module docs
│       └── worker.md       # worker module docs
├── mkdocs.yml              # NEW: MkDocs configuration
├── sync_queue/             # Source modules
├── validation/
├── plex/
├── worker/
└── hooks/
```

### Pattern 1: Module-per-page API Reference
**What:** One Markdown page per module, using mkdocstrings autodoc syntax
**When to use:** Small to medium projects with clear module boundaries
**Example:**
```markdown
# docs/api/sync_queue.md
# sync_queue Module

Queue management for persistent job storage.

## Manager

::: sync_queue.manager
    options:
      show_source: false
      members_order: source

## Operations

::: sync_queue.operations
    options:
      show_source: false

## Models

::: sync_queue.models
```

### Pattern 2: Recursive Module Documentation
**What:** Single autodoc directive documents entire module tree
**When to use:** Smaller modules, less control needed
**Example:**
```markdown
::: sync_queue
    options:
      show_submodules: true
      members_order: source
```

### Pattern 3: Cross-Reference to Architecture Docs
**What:** Link API docs back to architecture explanations
**When to use:** When design rationale exists elsewhere
**Example:**
```markdown
# sync_queue Module

See [Architecture: Persistence Layer](../ARCHITECTURE.md#sync_queue---persistence-layer)
for design rationale.

::: sync_queue.manager
```

### Anti-Patterns to Avoid
- **Duplicating architecture content:** Don't copy design explanations into docstrings; link to ARCHITECTURE.md instead
- **Over-documenting internals:** Filter private members; focus on public API
- **Hiding source code by default:** Show source helps users understand implementation
- **Inconsistent docstring style:** Mixing Google/NumPy/Sphinx styles breaks parsing

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Docstring parsing | Custom parser | mkdocstrings-python/Griffe | Handles edge cases, multiple styles |
| Cross-references | Manual links | mkdocstrings autorefs | Automatic linking between objects |
| Type annotation rendering | String formatting | mkdocstrings signatures | Handles complex types, generics |
| Navigation generation | Manual nav tree | mkdocs nav config | Auto-discovers pages if not specified |
| Search functionality | Custom search | mkdocs-material built-in | Full-text search with lunr.js |

**Key insight:** Documentation generation tooling has solved edge cases around docstring parsing, Unicode handling, cross-references, and rendering that are not worth reimplementing.

## Common Pitfalls

### Pitfall 1: Module Not Found Errors
**What goes wrong:** mkdocstrings can't find Python modules during build
**Why it happens:** Package not in Python path during mkdocs build
**How to avoid:** Configure `paths` option in mkdocs.yml to point to source root
**Warning signs:** "Could not find module 'sync_queue'" errors during build

```yaml
# mkdocs.yml - fix module finding
plugins:
  - mkdocstrings:
      handlers:
        python:
          paths: [.]  # Add project root to path
```

### Pitfall 2: Docstring Style Mismatch
**What goes wrong:** Parameters not parsed, sections appear as plain text
**Why it happens:** Default docstring style doesn't match actual style
**How to avoid:** Explicitly set `docstring_style: google` in config
**Warning signs:** Args/Returns sections render as code blocks instead of tables

```yaml
# mkdocs.yml - set docstring style
plugins:
  - mkdocstrings:
      handlers:
        python:
          options:
            docstring_style: google
```

### Pitfall 3: Import Errors from Dependencies
**What goes wrong:** Build fails when importing modules with optional dependencies
**Why it happens:** persist-queue, plexapi not installed in docs build environment
**How to avoid:** Dependencies don't need to be importable; Griffe uses AST parsing
**Warning signs:** ImportError for plexapi/persistqueue during build

Note: Griffe uses static AST analysis, NOT runtime imports. This is a key advantage over Sphinx autodoc. However, if `allow_inspection: true` (default false), imports will be attempted.

### Pitfall 4: Footnotes Split Across Sections
**What goes wrong:** Footnotes don't render, warnings about missing references
**Why it happens:** Griffe splits docstrings into sections; footnotes must be in same section
**How to avoid:** Keep footnote definitions in same docstring section as references
**Warning signs:** "Footnote [1] is not defined" warnings

### Pitfall 5: Private Members Cluttering API Docs
**What goes wrong:** Internal helpers appear in public API docs
**Why it happens:** Default filter `["!^_[^_]"]` still shows `_helper` functions
**How to avoid:** Use `filters: ["!^_"]` to hide all underscore-prefixed names
**Warning signs:** Methods like `_init_queue()` appearing in docs

### Pitfall 6: Broken Cross-References
**What goes wrong:** "Link to 'X' not found" warnings
**Why it happens:** Using parentheses `()` instead of brackets `[]` for refs
**How to avoid:** Use `[ClassName][]` syntax, not `(ClassName)`
**Warning signs:** MkDocs warnings about unfound links

## Code Examples

Verified patterns from official sources:

### Minimal mkdocs.yml Configuration
```yaml
# Source: https://mkdocstrings.github.io/python/usage/
site_name: PlexSync
site_description: Stash to Plex metadata sync plugin
repo_url: https://github.com/user/PlexSync

theme:
  name: material
  features:
    - navigation.sections
    - navigation.expand
    - search.suggest
    - content.code.copy

plugins:
  - search
  - mkdocstrings:
      handlers:
        python:
          paths: [.]
          options:
            docstring_style: google
            show_source: true
            show_root_heading: true
            show_root_full_path: false
            members_order: source
            filters: ["!^_"]

nav:
  - Home: index.md
  - User Guide:
    - Installation: install.md
    - Configuration: config.md
    - Troubleshooting: troubleshoot.md
  - Architecture: ARCHITECTURE.md
  - API Reference:
    - Overview: api/index.md
    - sync_queue: api/sync_queue.md
    - validation: api/validation.md
    - plex: api/plex.md
    - worker: api/worker.md

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.highlight:
      anchor_linenums: true
  - toc:
      permalink: true
```

### API Reference Page Template
```markdown
# sync_queue Module

Queue management for persistent job storage with crash recovery.

**Architecture:** See [Persistence Layer](../ARCHITECTURE.md#sync_queue---persistence-layer)

## QueueManager

::: sync_queue.manager.QueueManager
    options:
      members_order: source
      show_source: true

## Queue Operations

::: sync_queue.operations
    options:
      members_order: source

## Data Models

::: sync_queue.models
```

### Google-Style Docstring Template
```python
# Source: https://google.github.io/styleguide/pyguide.html
def function_name(param1: str, param2: int = 10) -> dict:
    """Short description of function (one line).

    Longer description if needed. Explain what the function does,
    not how it does it (that's what the code is for).

    Args:
        param1: Description of param1.
        param2: Description of param2. Defaults to 10.

    Returns:
        Description of return value. For complex returns:
            key1: Description of key1
            key2: Description of key2

    Raises:
        ValueError: When param1 is empty.
        ConnectionError: When network is unavailable.

    Example:
        >>> result = function_name("test", 5)
        >>> print(result)
        {'status': 'ok'}
    """
```

### Cross-Referencing Between Objects
```markdown
<!-- Reference a class -->
See [QueueManager][sync_queue.manager.QueueManager] for lifecycle management.

<!-- Reference a function -->
Use [enqueue()][sync_queue.operations.enqueue] to add jobs.

<!-- Reference with custom text -->
The [validation model][validation.metadata.SyncMetadata] ensures data quality.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Sphinx autodoc (runtime imports) | Griffe AST parsing | 2023+ | No import errors, faster builds |
| reStructuredText | Markdown + mkdocs | 2020+ | Lower barrier, same features |
| Manual API pages | mkdocstrings autodoc | 2020+ | Always in sync with code |
| Read the Docs theme | Material theme | 2022+ | Better UX, more features |

**Deprecated/outdated:**
- `mkgendocs`: Superseded by mkdocstrings
- `pdoc3`: Less actively maintained than mkdocstrings
- Sphinx for small projects: Overkill for most Python packages

## Docstring Audit Checklist

Current codebase docstring status (based on file review):

| Module | Files | Docstring Coverage | Style | Needs Work |
|--------|-------|-------------------|-------|------------|
| sync_queue | 4 | Complete | Google | Minor - add Examples |
| validation | 4 | Complete | Google | Good |
| plex | 4 | Complete | Google | Good |
| worker | 3 | Complete | Google | Minor - backoff examples |
| hooks | 1 | Partial | Google | Needs review |

**Common improvements needed:**
1. Add `Example:` sections to key functions
2. Ensure `Raises:` sections document all exceptions
3. Add module-level `__all__` for explicit public API
4. Verify return type annotations match docstrings

## Open Questions

Things that couldn't be fully resolved:

1. **Hosting platform**
   - What we know: MkDocs generates static HTML, deployable anywhere
   - What's unclear: Will docs be hosted on GitHub Pages, Read the Docs, or project repo?
   - Recommendation: Start with `mkdocs serve` for local preview; decide hosting later

2. **CI integration**
   - What we know: `mkdocs build` can be added to CI pipeline
   - What's unclear: Whether to auto-deploy docs on release
   - Recommendation: Add `mkdocs build --strict` to CI for validation; deploy is optional

3. **Version documentation**
   - What we know: mike plugin supports versioned docs
   - What's unclear: Whether multiple versions needed for a plugin
   - Recommendation: Single version is fine for plugins; add versioning if needed later

## Sources

### Primary (HIGH confidence)
- [mkdocstrings-python documentation](https://mkdocstrings.github.io/python/) - Handler configuration, usage patterns
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) - Theme configuration, features
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) - Docstring format reference

### Secondary (MEDIUM confidence)
- [mkdocstrings troubleshooting](https://mkdocstrings.github.io/troubleshooting/) - Common issues and solutions
- [PyPI mkdocs-material](https://pypi.org/project/mkdocs-material/) - Version 9.7.1 (Dec 2025)
- [PyPI mkdocstrings-python](https://pypi.org/project/mkdocstrings-python/) - Version 2.0.1 (Dec 2025)

### Tertiary (LOW confidence)
- WebSearch comparisons of Sphinx vs MkDocs - Community preferences, may vary by use case

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official docs verified, versions confirmed on PyPI
- Architecture: HIGH - Based on official mkdocstrings patterns and project structure
- Pitfalls: HIGH - From official troubleshooting docs
- Docstring audit: HIGH - Direct file review of codebase

**Research date:** 2026-02-03
**Valid until:** 60 days (stable tooling, infrequent breaking changes)
