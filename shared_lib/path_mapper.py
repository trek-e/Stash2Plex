"""
shared_lib.path_mapper — Bidirectional regex path mapping engine.

Translates file paths between Plex library paths and Stash scene paths
using user-defined regex rules with capture groups.

Rule field semantics
--------------------
plex_pattern
    A Python ``re`` regex that matches Plex file paths.  Capturing groups
    provide the "payload" (file sub-path, relative segment, etc.) that will
    be transplanted into the Stash path.

    Example: ``^/plex/media/(.*)``

stash_pattern
    A ``re.sub`` *replacement template* that constructs the Stash file path
    from the groups captured by ``plex_pattern``.  Use ``\\1``, ``\\2``, …
    as back-references.

    Example: ``/stash/media/\\1``

Together these two values are fully bidirectional:

* **plex→stash**: match with ``plex_pattern``; substitute groups into
  ``stash_pattern`` template.
* **stash→plex**: derive a match regex from ``stash_pattern`` (replace
  ``\\N`` back-references with ``(.*?)`` capture groups); match the
  derived regex against the Stash path; substitute captured groups back
  into a replacement template derived from ``plex_pattern``.

Usage
-----
::

    from shared_lib.path_mapper import PathMapper, PathRule

    rules = [
        PathRule(
            name="nas",
            plex_pattern=r"^/plex/media/(.*)",
            stash_pattern=r"/stash/media/\\1",
        )
    ]
    mapper = PathMapper(rules)
    stash_path = mapper.plex_to_stash("/plex/media/video.mkv")
    # -> "/stash/media/video.mkv"

    plex_path = mapper.stash_to_plex("/stash/media/video.mkv")
    # -> "/plex/media/video.mkv"

Config via environment variable::

    import os
    mapper = PathMapper.from_env(os.environ.get("PATH_RULES", "[]"))

JSON format — capture group references must use ``\\\\1``, ``\\\\2`` etc.
(double-escaped in JSON so the Python string contains a single backslash)::

    PATH_RULES='[{"name":"nas","plex_pattern":"^/plex/(.*)","stash_pattern":"/stash/\\\\1"}]'
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel

log = logging.getLogger("shared_lib.path_mapper")

# Matches back-references \\1 … \\9 (or \\10+ for completeness) in a
# replacement template string.
_BACKREF_RE = re.compile(r"\\(\d+)")


def _template_to_match_pattern(template: str) -> str:
    """
    Convert a ``re.sub`` replacement template into a match pattern.

    Each back-reference ``\\N`` in the template becomes a non-greedy
    capturing group ``(.*?)``.  Literal portions of the template are
    ``re.escape``-d so they match exactly.

    The resulting pattern is anchored with ``^`` and ``$`` to ensure a
    full-string match, not just a prefix.

    Example::

        _template_to_match_pattern(r"/stash/media/\\1")
        # -> r"^/stash/media/(.*?)$"
    """
    parts: list[str] = []
    pos = 0
    for m in _BACKREF_RE.finditer(template):
        parts.append(re.escape(template[pos : m.start()]))
        parts.append("(.*?)")
        pos = m.end()
    parts.append(re.escape(template[pos:]))
    return "^" + "".join(parts) + "$"


def _pattern_to_repl_template(pattern: str) -> str:
    """
    Convert a ``re`` match pattern into a ``re.sub`` replacement template.

    Strips leading ``^`` and trailing ``$`` anchors.  Each top-level
    *capturing* group ``(...)`` is replaced by a numbered back-reference
    ``\\1``, ``\\2``, etc.  Non-capturing groups ``(?:...)``, look-ahead
    ``(?=...)``, and look-behind ``(?<=...)`` are left untouched.

    Example::

        _pattern_to_repl_template(r"^/plex/media/(.*)")
        # -> r"/plex/media/\\1"
    """
    # Strip anchors.
    p = pattern
    if p.startswith("^"):
        p = p[1:]
    if p.endswith("$"):
        p = p[:-1]

    result: list[str] = []
    i = 0
    group_num = 0

    while i < len(p):
        ch = p[i]

        if ch == "\\" and i + 1 < len(p):
            # Escaped character — include both chars verbatim.
            result.append(p[i : i + 2])
            i += 2
            continue

        if ch == "(":
            # Check if this is a non-capturing group: (?  character.
            if i + 1 < len(p) and p[i + 1] == "?":
                # Non-capturing — include the opening paren as-is.
                result.append(ch)
                i += 1
                continue

            # Capturing group — find its balanced closing paren.
            group_num += 1
            depth = 1
            j = i + 1
            while j < len(p) and depth > 0:
                if p[j] == "\\" and j + 1 < len(p):
                    j += 2
                    continue
                if p[j] == "(":
                    depth += 1
                elif p[j] == ")":
                    depth -= 1
                j += 1
            # Replace the entire group with a back-reference.
            result.append(f"\\{group_num}")
            i = j
            continue

        result.append(ch)
        i += 1

    return "".join(result)


class PathRule(BaseModel):
    """A single named bidirectional path mapping rule."""

    name: str
    plex_pattern: str   # Regex (with capturing groups) that matches Plex paths
    stash_pattern: str  # ``re.sub`` replacement template (``\\1``, ``\\2``, …) for Stash paths
    case_insensitive: bool = False


class PathMapper:
    """
    Applies an ordered list of :class:`PathRule` objects to translate paths
    bidirectionally between Plex library paths and Stash scene paths.

    Rules are evaluated in array order — **first match wins**.  Returns
    ``None`` when no rule matches the given path.  Back-slash paths are
    normalised to forward slashes before matching.

    * ``plex_to_stash``: match with compiled ``plex_pattern``; substitute
      into ``stash_pattern`` template.
    * ``stash_to_plex``: match with a derived stash match regex; substitute
      into a derived plex replacement template.
    """

    def __init__(self, rules: list[PathRule]) -> None:
        self._rules = rules

        def _flags(r: PathRule) -> int:
            return re.IGNORECASE if r.case_insensitive else 0

        # plex-side: compiled plex_pattern regex.
        self._plex_compiled: list[re.Pattern[str]] = [
            re.compile(r.plex_pattern, _flags(r)) for r in rules
        ]
        # stash-side: derived match regex from stash_pattern template.
        self._stash_compiled: list[re.Pattern[str]] = [
            re.compile(_template_to_match_pattern(r.stash_pattern), _flags(r))
            for r in rules
        ]
        # Reverse substitution templates derived from plex_pattern regexes.
        self._plex_repl_templates: list[str] = [
            _pattern_to_repl_template(r.plex_pattern) for r in rules
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize(self, path: str) -> str:
        """Replace backslashes with forward slashes."""
        return path.replace("\\", "/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plex_to_stash(self, plex_path: str) -> Optional[str]:
        """
        Translate a Plex file path to a Stash file path.

        Returns ``None`` if no rule matches the given path.
        """
        path = self._normalize(plex_path)
        for rule, plex_re in zip(self._rules, self._plex_compiled):
            if plex_re.match(path):
                result = plex_re.sub(rule.stash_pattern, path, count=1)
                log.debug(
                    "path_mapper: plex\u2192stash via rule %r: %r \u2192 %r",
                    rule.name, path, result,
                )
                return result
        log.info("path_mapper: no rule matched plex path %r", path)
        return None

    def stash_to_plex(self, stash_path: str) -> Optional[str]:
        """
        Translate a Stash file path to a Plex file path.

        Returns ``None`` if no rule matches the given path.
        """
        path = self._normalize(stash_path)
        for rule, stash_re, plex_repl in zip(
            self._rules, self._stash_compiled, self._plex_repl_templates
        ):
            if stash_re.match(path):
                result = stash_re.sub(plex_repl, path, count=1)
                log.debug(
                    "path_mapper: stash\u2192plex via rule %r: %r \u2192 %r",
                    rule.name, path, result,
                )
                return result
        log.info("path_mapper: no rule matched stash path %r", path)
        return None

    @classmethod
    def from_env(cls, env_value: str) -> "PathMapper":
        """
        Parse a ``PATH_RULES`` JSON string into a :class:`PathMapper`.

        The JSON value must be an array of rule objects.  Each object must
        have ``name``, ``plex_pattern``, and ``stash_pattern`` keys.
        ``case_insensitive`` is optional (defaults to ``False``).

        Capture group back-references in JSON must be written as ``\\\\1``,
        ``\\\\2``, etc. (double-escaped in JSON so the Python string
        contains a single backslash which ``re.sub`` interprets as a group
        reference).

        Raises:
            json.JSONDecodeError: If *env_value* is not valid JSON.
            pydantic.ValidationError: If any rule dict is missing required
                fields or has invalid values.
        """
        raw: list[dict] = json.loads(env_value)
        rules = [PathRule(**r) for r in raw]
        return cls(rules)
