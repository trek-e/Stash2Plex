"""
Guard test for the release zip manifest in .github/workflows/release.yml.

This exists because shared_lib/ shipped missing from a release once:
Stash2Plex.py and reconciliation/engine.py both import
`shared_lib.prefix_path_map` at function scope (inside a function body, not
at module top-level), so the plugin started cleanly and only raised
ModuleNotFoundError the first time a Plex scan or reconciliation path-map
apply actually ran. A plain "does the plugin import" smoke test would never
have caught this because the failure only happens deep inside a call graph
at runtime.

This test statically scans every first-party source file that the "Build
plugin zip" step in release.yml packages, finds every top-level first-party
package it imports (function-level imports included, since we use an AST
walk rather than actually importing anything), and asserts each such
package is listed in the zip manifest. If a new first-party top-level
package (e.g. `shared_lib`) starts being imported by packaged code but
isn't added to the `zip -r` entry list in release.yml, this test fails and
names exactly which package/file/line is missing.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"

# Directories we never want to treat as "packaged source" even if a package
# with the same name gets added later.
EXCLUDED_DIR_NAMES = {"tests", "test", "__pycache__", ".pytest_cache", "docs"}


def _parse_zip_manifest_entries():
    """Extract the list of paths passed to `zip -r` in release.yml.

    The build step looks like:

        zip -r Stash2Plex.zip \\
          Stash2Plex.py Stash2Plex.yml requirements.txt BUILD_INFO.txt \\
          worker/ sync_queue/ plex/ validation/ shared/ shared_lib/ hooks/ reconciliation/ \\
          -x '*/test*' '*/__pycache__/*' '*.pyc' '*/.pytest*'

    We capture everything between `zip -r <target>` and the `-x` exclude
    flag, across the backslash-continued lines, and split it into tokens.
    """
    text = RELEASE_YML.read_text()
    match = re.search(
        r"zip\s+-r\s+\S+\s+((?:.|\n)*?)\n\s*-x\b",
        text,
    )
    assert match is not None, (
        f"Could not find a `zip -r ... -x ...` build command in {RELEASE_YML}. "
        "The release workflow's zip-build step may have been restructured; "
        "update the parsing regex in test_release_manifest.py's "
        "_parse_zip_manifest_entries() to match the new format."
    )
    block = match.group(1)
    # Strip backslash line-continuations, then split on whitespace.
    block = block.replace("\\", " ")
    entries = [tok.strip() for tok in block.split() if tok.strip()]
    return entries


def _manifest_packages_and_files():
    entries = _parse_zip_manifest_entries()
    packages = {e.rstrip("/") for e in entries if e.endswith("/")}
    files = {e for e in entries if not e.endswith("/")}
    return packages, files


def _first_party_candidates():
    """Top-level directories in the repo root that are Python packages.

    This is dynamic (rather than a hardcoded list) so a *new* first-party
    package automatically becomes a candidate this test checks for, instead
    of silently being ignored the way shared_lib was.
    """
    candidates = set()
    for child in REPO_ROOT.iterdir():
        if not child.is_dir():
            continue
        if child.name in EXCLUDED_DIR_NAMES or child.name.startswith("."):
            continue
        if (child / "__init__.py").exists():
            candidates.add(child.name)
    return candidates


def _packaged_python_files(manifest_packages, manifest_files):
    """Resolve the manifest entries to actual .py files in the repo tree.

    Mirrors the `-x '*/test*' '*/__pycache__/*' '*.pyc' '*/.pytest*'`
    excludes from the zip command closely enough for static-import scanning
    purposes (we only need source files, not test fixtures).
    """
    py_files = []

    for name in manifest_files:
        if name.endswith(".py"):
            path = REPO_ROOT / name
            if path.exists():
                py_files.append(path)

    for pkg in manifest_packages:
        pkg_dir = REPO_ROOT / pkg
        if not pkg_dir.is_dir():
            continue
        for path in pkg_dir.rglob("*.py"):
            rel_parts = path.relative_to(pkg_dir).parts
            if any(part in EXCLUDED_DIR_NAMES or "test" in part for part in rel_parts):
                continue
            py_files.append(path)

    return py_files


def _first_party_imports_in_file(path, candidates):
    """Return {package_name: [(file, lineno), ...]} for imports of any
    candidate first-party package found anywhere in the file (including
    inside function bodies, since we walk the whole AST)."""
    referenced = {}
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - would indicate a real bug
        pytest.fail(f"Could not parse {path} while scanning for imports: {exc}")

    for node in ast.walk(tree):
        names_and_lines = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                names_and_lines.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import, not a top-level package reference
            if node.module:
                names_and_lines.append((node.module.split(".")[0], node.lineno))

        for top_name, lineno in names_and_lines:
            if top_name in candidates:
                referenced.setdefault(top_name, []).append(
                    (str(path.relative_to(REPO_ROOT)), lineno)
                )
    return referenced


def test_release_zip_manifest_ships_every_first_party_import():
    """Every first-party package imported by packaged code must be in the
    release.yml zip manifest.

    Regression guard for shared_lib/ shipping missing: Stash2Plex.py and
    reconciliation/engine.py import shared_lib.prefix_path_map inside
    function bodies, so the gap was invisible to a full pytest run and only
    surfaced as an ImportError in the field the first time a Plex scan or
    reconciliation apply ran.
    """
    manifest_packages, manifest_files = _manifest_packages_and_files()
    candidates = _first_party_candidates()
    packaged_files = _packaged_python_files(manifest_packages, manifest_files)

    assert packaged_files, (
        "No packaged .py files were resolved from the release.yml zip "
        "manifest -- the manifest parsing or package resolution logic in "
        "test_release_manifest.py is likely broken; fix the test before "
        "trusting its PASS/FAIL result."
    )

    all_referenced = {}
    for path in packaged_files:
        for pkg, locations in _first_party_imports_in_file(path, candidates).items():
            all_referenced.setdefault(pkg, []).extend(locations)

    missing = {
        pkg: locations
        for pkg, locations in all_referenced.items()
        if pkg not in manifest_packages
    }

    if missing:
        lines = ["Packaged code imports first-party package(s) not shipped by "
                 f"the release zip manifest in {RELEASE_YML}:"]
        for pkg, locations in sorted(missing.items()):
            lines.append(f"  - '{pkg}' referenced at:")
            for file, lineno in sorted(locations):
                lines.append(f"      {file}:{lineno}")
            lines.append(
                f"    Fix: add '{pkg}/' to the `zip -r Stash2Plex.zip ...` "
                f"entry list in {RELEASE_YML.relative_to(REPO_ROOT)}."
            )
        pytest.fail("\n".join(lines))
