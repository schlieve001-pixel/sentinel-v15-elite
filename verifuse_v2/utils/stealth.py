"""
VERIFUSE V2 — Stealth HTTP Session (DEPRECATED SHIM)

This module is kept for backward compatibility.
Use verifuse_v2.utils.polite_crawler.PoliteCrawler instead.

StealthSession is now an alias for PoliteCrawler.
"""

from verifuse_v2.utils.polite_crawler import PoliteCrawler as StealthSession  # noqa: F401

__all__ = ["StealthSession"]
