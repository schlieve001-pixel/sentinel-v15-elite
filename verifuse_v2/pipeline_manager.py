"""
VERIFUSE V2 — Engine 0: The Governor

Global rate limiter and orchestrator. All scrapers check in with the
Governor before making any HTTP request. State persists to JSON.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
STATE_FILE = DATA_DIR / "governor_state.json"

SCRAPER_REGISTRY: dict[str, dict] = {
    "denver_trustee": {
        "rpm": 2,
        "daily_quota": 500,
        "backpressure": True,
        "success_threshold": 0.8,
        "captcha_cooldown_hours": 24,
        "base_url": (
            "https://www.denvergov.org/Government/"
            "Agencies-Departments-Offices/"
            "Agencies-Departments-Offices-Directory/"
            "Department-of-Finance/Public-Trustee"
        ),
        "enabled": True,
    },
    "denver_outcome": {
        "rpm": 2,
        "daily_quota": 500,
        "backpressure": True,
        "success_threshold": 0.8,
        "captcha_cooldown_hours": 24,
        "base_url": (
            "https://www.denvergov.org/Government/"
            "Agencies-Departments-Offices/"
            "Agencies-Departments-Offices-Directory/"
            "Department-of-Finance/Public-Trustee/"
            "ForeclosureDetail"
        ),
        "enabled": True,
    },
    "denver_assessor": {
        "rpm": 2,
        "daily_quota": 300,
        "backpressure": True,
        "success_threshold": 0.8,
        "captcha_cooldown_hours": 24,
        "base_url": "https://www.denvergov.org/property/realproperty/search",
        "enabled": True,
    },
    "elpaso_postsale": {
        "rpm": 2,
        "daily_quota": 300,
        "backpressure": True,
        "success_threshold": 0.8,
        "captcha_cooldown_hours": 24,
        "base_url": "https://elpasopublictrustee.com/foreclosure-reports/",
        "enabled": True,
    },
    "adams_postsale": {
        "rpm": 2,
        "daily_quota": 300,
        "backpressure": True,
        "success_threshold": 0.8,
        "captcha_cooldown_hours": 24,
        "base_url": "https://apps.adcogov.org/PTForeclosureSearch/reports",
        "enabled": True,
    },
}

WINDOW_SIZE = 50  # Rolling window for success-rate calculation


class GovernorState:
    """Per-scraper runtime metrics (serialisable to JSON)."""

    def __init__(
        self,
        scraper_name: str,
        requests_today: int = 0,
        current_rpm: float = 2.0,
        last_captcha_at: Optional[str] = None,
        day_key: Optional[str] = None,
        recent_results: Optional[list[bool]] = None,
    ):
        self.scraper_name = scraper_name
        self.requests_today = requests_today
        self.current_rpm = current_rpm
        self.last_captcha_at = last_captcha_at
        self.day_key = day_key or self._today()
        self.recent_results: deque[bool] = deque(
            recent_results or [], maxlen=WINDOW_SIZE
        )

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def success_rate(self) -> float:
        if not self.recent_results:
            return 1.0
        return sum(self.recent_results) / len(self.recent_results)

    def to_dict(self) -> dict:
        return {
            "scraper_name": self.scraper_name,
            "requests_today": self.requests_today,
            "current_rpm": self.current_rpm,
            "last_captcha_at": self.last_captcha_at,
            "day_key": self.day_key,
            "recent_results": list(self.recent_results),
        }

    @classmethod
    def from_dict(cls, data: dict) -> GovernorState:
        return cls(
            scraper_name=data["scraper_name"],
            requests_today=data.get("requests_today", 0),
            current_rpm=data.get("current_rpm", 2.0),
            last_captcha_at=data.get("last_captcha_at"),
            day_key=data.get("day_key"),
            recent_results=data.get("recent_results"),
        )


class Governor:
    """Engine 0 — global rate limiter and pipeline orchestrator."""

    def __init__(self, registry: Optional[dict] = None):
        self.registry: dict[str, dict] = dict(registry or SCRAPER_REGISTRY)
        self._states: dict[str, GovernorState] = {}
        self._load_state()

    # ── State persistence ────────────────────────────────────────────

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                raw = json.loads(STATE_FILE.read_text())
                for name, sdata in raw.items():
                    self._states[name] = GovernorState.from_dict(sdata)
                log.info("Governor state loaded from %s", STATE_FILE)
            except (json.JSONDecodeError, KeyError) as exc:
                log.warning("Corrupt governor state, resetting: %s", exc)
                self._states = {}
        self._ensure_states()

    def _ensure_states(self) -> None:
        for name, cfg in self.registry.items():
            if name not in self._states:
                self._states[name] = GovernorState(
                    scraper_name=name,
                    current_rpm=cfg["rpm"],
                )

    def _save_state(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {n: s.to_dict() for n, s in self._states.items()}
        STATE_FILE.write_text(json.dumps(payload, indent=2))

    # ── Rate-limiting API ────────────────────────────────────────────

    def request_permit(self, scraper_name: str) -> bool:
        """Return True if the scraper is allowed to make an HTTP request now."""
        cfg = self.registry.get(scraper_name)
        if cfg is None:
            log.error("Unknown scraper: %s", scraper_name)
            return False
        if not cfg.get("enabled", True):
            log.info("Scraper %s is disabled", scraper_name)
            return False

        state = self._states[scraper_name]

        # Reset daily counter at midnight UTC
        today = GovernorState._today()
        if state.day_key != today:
            state.requests_today = 0
            state.day_key = today
            # Restore base RPM on new day
            state.current_rpm = cfg["rpm"]

        # Daily quota check
        if state.requests_today >= cfg["daily_quota"]:
            log.info("Scraper %s hit daily quota (%d)", scraper_name, cfg["daily_quota"])
            return False

        # Captcha cooldown check
        if state.last_captcha_at:
            cooldown = timedelta(hours=cfg["captcha_cooldown_hours"])
            captcha_time = datetime.fromisoformat(state.last_captcha_at)
            if datetime.now(timezone.utc) - captcha_time < cooldown:
                log.info("Scraper %s in captcha cooldown until %s",
                         scraper_name, captcha_time + cooldown)
                return False
            # Cooldown expired — clear flag
            state.last_captcha_at = None

        # Backpressure check
        if cfg.get("backpressure") and len(state.recent_results) >= WINDOW_SIZE:
            if state.success_rate < cfg["success_threshold"]:
                new_rpm = max(0.5, state.current_rpm / 2)
                if new_rpm != state.current_rpm:
                    log.warning("Backpressure: %s RPM %.1f → %.1f (success %.0f%%)",
                                scraper_name, state.current_rpm, new_rpm,
                                state.success_rate * 100)
                    state.current_rpm = new_rpm

        # Jitter delay
        if state.current_rpm > 0:
            jitter = random.uniform(0, 1.0 / state.current_rpm)
            time.sleep(jitter)

        state.requests_today += 1
        self._save_state()
        return True

    def report_result(
        self, scraper_name: str, status_code: int, captcha_hit: bool = False
    ) -> None:
        """Record the outcome of an HTTP request."""
        state = self._states.get(scraper_name)
        if state is None:
            return

        success = 200 <= status_code < 400 and not captcha_hit
        state.recent_results.append(success)

        if captcha_hit:
            state.last_captcha_at = datetime.now(timezone.utc).isoformat()
            log.warning("CAPTCHA detected for %s — pausing", scraper_name)

        self._save_state()

    # ── Pipeline orchestration ───────────────────────────────────────

    def run_pipeline(self) -> dict:
        """Run Engine 1 → Engine 2 → Engine 3 in sequence.

        Returns a summary dict of what was processed.
        """
        summary: dict = {"signals": 0, "outcomes": 0, "entities": 0, "errors": []}

        # Engine 1: Signal discovery
        try:
            from verifuse_v2.scrapers.signal_denver import DenverSignalScraper

            scraper = DenverSignalScraper(governor=self)
            signals = scraper.scrape()
            summary["signals"] = len(signals)
            log.info("Engine 1 produced %d signals", len(signals))
        except Exception as exc:
            summary["errors"].append(f"Engine 1 (Signal): {exc}")
            log.error("Engine 1 failed: %s", exc)
            signals = []

        # Engine 2: Outcome resolution
        try:
            from verifuse_v2.scrapers.outcome_denver import DenverOutcomeScraper

            outcome_scraper = DenverOutcomeScraper(governor=self)
            outcomes = outcome_scraper.scrape()
            summary["outcomes"] = len(outcomes)
            log.info("Engine 2 produced %d outcomes", len(outcomes))
        except Exception as exc:
            summary["errors"].append(f"Engine 2 (Outcome): {exc}")
            log.error("Engine 2 failed: %s", exc)

        # Engine 3: Entity enrichment
        try:
            from verifuse_v2.enrichment.entity_resolver import EntityResolver

            resolver = EntityResolver(governor=self)
            entities = resolver.resolve()
            summary["entities"] = len(entities)
            log.info("Engine 3 produced %d entities", len(entities))
        except Exception as exc:
            summary["errors"].append(f"Engine 3 (Entity): {exc}")
            log.error("Engine 3 failed: %s", exc)

        # Engine 4: Vertex AI PDF extraction
        try:
            from verifuse_v2.scrapers.vertex_engine import process_batch

            batch_result = process_batch(limit=50)
            summary["vertex_processed"] = batch_result.get("processed", 0)
            summary["vertex_ingested"] = batch_result.get("ingested", 0)
            log.info("Engine 4 processed %d PDFs, ingested %d",
                     batch_result.get("processed", 0), batch_result.get("ingested", 0))
        except Exception as exc:
            summary["errors"].append(f"Engine 4 (Vertex): {exc}")
            log.error("Engine 4 failed: %s", exc)

        # Engine 5: El Paso County post-sale PDF scraper
        try:
            from verifuse_v2.scrapers.elpaso_postsale_scraper import run as elpaso_run

            elpaso_result = elpaso_run()
            summary["elpaso_inserted"] = elpaso_result.get("inserted", 0)
            summary["elpaso_total"] = elpaso_result.get("total", 0)
            log.info("Engine 5 (El Paso): %d new from %d records",
                     elpaso_result.get("inserted", 0), elpaso_result.get("total", 0))
        except Exception as exc:
            summary["errors"].append(f"Engine 5 (El Paso): {exc}")
            log.error("Engine 5 failed: %s", exc)

        # Engine 6: Adams County post-sale PDF scraper
        try:
            from verifuse_v2.scrapers.adams_postsale_scraper import run as adams_run

            adams_result = adams_run()
            summary["adams_inserted"] = adams_result.get("inserted", 0)
            summary["adams_total"] = adams_result.get("total", 0)
            log.info("Engine 6 (Adams): %d new from %d records",
                     adams_result.get("inserted", 0), adams_result.get("total", 0))
        except Exception as exc:
            summary["errors"].append(f"Engine 6 (Adams): {exc}")
            log.error("Engine 6 failed: %s", exc)

        self._save_state()
        return summary
