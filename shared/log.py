"""
Stash plugin logging protocol.

Stash captures plugin output via stderr using a binary prefix protocol:
  \\x01 + level_char + \\x02 + message

This module provides a factory to create log functions with a component prefix,
eliminating the need to duplicate the protocol in every module.

Usage:
    from shared.log import create_logger
    log_trace, log_debug, log_info, log_warn, log_error = create_logger("Worker")
    log_info("Processing job 42")  # -> \\x01i\\x02[Stash2Plex Worker] Processing job 42
"""

import sys


def create_logger(component: str = ""):
    """Create Stash plugin log functions for a component.

    Args:
        component: Component name suffix. If provided, prefix becomes
                   "[Stash2Plex {component}]", otherwise "[Stash2Plex]".

    Returns:
        Tuple of (log_trace, log_debug, log_info, log_warn, log_error) functions.
    """
    prefix = f"[Stash2Plex {component}]" if component else "[Stash2Plex]"

    def log_trace(msg): print(f"\x01t\x02{prefix} {msg}", file=sys.stderr)
    def log_debug(msg): print(f"\x01d\x02{prefix} {msg}", file=sys.stderr)
    def log_info(msg): print(f"\x01i\x02{prefix} {msg}", file=sys.stderr)
    def log_warn(msg): print(f"\x01w\x02{prefix} {msg}", file=sys.stderr)
    def log_error(msg): print(f"\x01e\x02{prefix} {msg}", file=sys.stderr)

    return log_trace, log_debug, log_info, log_warn, log_error


def create_progress_logger():
    """Create Stash plugin progress reporter.

    Returns:
        log_progress function that reports task progress to Stash UI.
    """
    def log_progress(p): print(f"\x01p\x02{p}")
    return log_progress
