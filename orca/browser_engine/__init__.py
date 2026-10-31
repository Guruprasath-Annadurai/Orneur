"""Sandboxed Chromium substrate.

This is not the read-only retrieval policy on the separate core-runtime
branch. Page text is untrusted data. A page cannot grant an action.
"""

from orca.browser_engine.engine import BrowserEngine, BrowserError, issue_grant
from orca.browser_engine.policy import PolicyError, page_content_not_authority

__all__ = [
    "BrowserEngine",
    "BrowserError",
    "PolicyError",
    "issue_grant",
    "page_content_not_authority",
]
