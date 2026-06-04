"""
omnicovas.core.resource_monitor

Measure and bound resource use (memory, CPU, disk).

Principle 10 (Resource Efficiency):
    All resource use is measured, bounded, and transparent.
    Commanders can inspect live usage via the /resources endpoint.

Principle 7 (Privacy-by-Default) note:
    This data is local-only. Never transmitted anywhere.

Startup behavior:
    - Load resource_budget.yaml
    - Detect constrained systems (<8GB RAM, <100GB free disk)
    - Apply reduced defaults automatically

See: Master Blueprint v4.0 Section 9 (Resource Budget Framework)
See: Phase 1 Development Guide Week 6, Part B
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil
import yaml

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_PATH = Path("resource_budget.yaml")

# Constrained-system thresholds
CONSTRAINED_RAM_GB_THRESHOLD = 8.0
CONSTRAINED_DISK_GB_THRESHOLD = 100.0


@dataclass
class ResourceBudget:
    """Loaded budget limits for each resource category."""

    max_galaxy_dump_size_gb: int = 5
    max_log_retention_days: int = 30
    log_rotation_size_mb: int = 100
    max_cache_size_mb: int = 512
    max_ai_context_tokens: int = 4000
    max_background_task_cpu_percent: int = 10
    max_eddn_submission_per_hour: int = 100
    max_api_calls_per_minute_total: int = 50

    @classmethod
    def load(cls, path: Path = DEFAULT_BUDGET_PATH) -> ResourceBudget:
        """
        Load budget from YAML file. Returns defaults if file is missing.
        """
        if not path.exists():
            logger.warning(
                "Resource budget file not found at %s; using defaults.", path
            )
            return cls()

        try:
            with open(path, encoding="utf-8") as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            logger.error("Failed to load resource budget: %s", e)
            return cls()

        disk = data.get("disk", {})
        memory = data.get("memory", {})
        cpu = data.get("cpu", {})
        bandwidth = data.get("bandwidth", {})

        return cls(
            max_galaxy_dump_size_gb=int(disk.get("max_galaxy_dump_size_gb", 5)),
            max_log_retention_days=int(disk.get("max_log_retention_days", 30)),
            log_rotation_size_mb=int(disk.get("log_rotation_size_mb", 100)),
            max_cache_size_mb=int(memory.get("max_cache_size_mb", 512)),
            max_ai_context_tokens=int(memory.get("max_ai_context_tokens", 4000)),
            max_background_task_cpu_percent=int(
                cpu.get("max_background_task_cpu_percent", 10)
            ),
            max_eddn_submission_per_hour=int(
                bandwidth.get("max_eddn_submission_per_hour", 100)
            ),
            max_api_calls_per_minute_total=int(
                bandwidth.get("max_api_calls_per_minute_total", 50)
            ),
        )


@dataclass
class ResourceSnapshot:
    """A single measurement of current resource use."""

    memory_used_mb: float
    memory_total_mb: float
    cpu_percent: float
    disk_free_gb: float
    disk_total_gb: float


class ResourceMonitor:
    """
    Background monitor that polls system resources every 60s.

    Logs a warning if any budget limit is exceeded.
    Exposes current measurements via /resources in ApiBridge.

    Phase 1: observe and log. Phase 2+ will throttle or alert.
    """

    def __init__(
        self,
        budget: ResourceBudget | None = None,
        poll_interval_seconds: float = 60.0,
    ) -> None:
        self._budget = budget or ResourceBudget.load()
        self._poll_interval = poll_interval_seconds
        self._process = psutil.Process(os.getpid())
        self._latest: ResourceSnapshot | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def budget(self) -> ResourceBudget:
        """Return the active budget (possibly adjusted for constrained system)."""
        return self._budget

    @property
    def latest(self) -> ResourceSnapshot | None:
        """Most recent snapshot, or None if monitor hasn't run yet."""
        return self._latest

    def detect_constrained_system(self) -> bool:
        """
        Check if the current machine is resource-constrained and halve the
        cache / galaxy dump defaults if so.

        Returns:
            True if the system is constrained, False otherwise.
        """
        ram_gb = psutil.virtual_memory().total / (1024**3)
        disk_free_gb = psutil.disk_usage(os.path.expanduser("~")).free / (1024**3)

        constrained = False
        if ram_gb < CONSTRAINED_RAM_GB_THRESHOLD:
            self._budget.max_cache_size_mb //= 2
            constrained = True
            logger.info(
                "Detected constrained RAM (%.1f GB). Cache size halved to %d MB.",
                ram_gb,
                self._budget.max_cache_size_mb,
            )

        if disk_free_gb < CONSTRAINED_DISK_GB_THRESHOLD:
            self._budget.max_galaxy_dump_size_gb //= 2
            constrained = True
            logger.info(
                "Detected constrained disk (%.1f GB free). "
                "Galaxy dump budget halved to %d GB.",
                disk_free_gb,
                self._budget.max_galaxy_dump_size_gb,
            )

        return constrained

    def snapshot(self) -> ResourceSnapshot:
        """Take a single measurement of current resource use."""
        vm = psutil.virtual_memory()
        proc_mem = self._process.memory_info().rss
        disk = psutil.disk_usage(os.path.expanduser("~"))

        return ResourceSnapshot(
            memory_used_mb=proc_mem / (1024**2),
            memory_total_mb=vm.total / (1024**2),
            cpu_percent=self._process.cpu_percent(interval=None),
            disk_free_gb=disk.free / (1024**3),
            disk_total_gb=disk.total / (1024**3),
        )

    def check_budget(self, snap: ResourceSnapshot) -> list[str]:
        """
        Compare the snapshot against configured budgets.

        Returns:
            List of human-readable warning strings (empty if all within budget).
        """
        warnings: list[str] = []

        if snap.memory_used_mb > self._budget.max_cache_size_mb * 2:
            warnings.append(
                f"Memory use {snap.memory_used_mb:.0f} MB exceeds "
                f"2x cache budget ({self._budget.max_cache_size_mb * 2} MB)"
            )

        if snap.cpu_percent > self._budget.max_background_task_cpu_percent * 3:
            warnings.append(
                f"CPU use {snap.cpu_percent:.1f}% exceeds 3x background budget"
            )

        if snap.disk_free_gb < 1.0:
            warnings.append(
                f"Disk free space low: {snap.disk_free_gb:.1f} GB remaining"
            )

        return warnings

    async def _poll_loop(self) -> None:
        """Main polling loop — runs in the background."""
        logger.info("ResourceMonitor polling every %.0fs", self._poll_interval)
        # First call of cpu_percent returns 0.0; prime it once.
        self._process.cpu_percent(interval=None)

        while self._running:
            try:
                snap = self.snapshot()
                self._latest = snap
                warnings = self.check_budget(snap)
                for warning in warnings:
                    logger.warning("[RESOURCE] %s", warning)
            except Exception as e:
                logger.error("ResourceMonitor poll failed: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def start(self) -> None:
        """Start background monitoring."""
        if self._running:
            return
        self._running = True
        self.detect_constrained_system()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("ResourceMonitor started.")

    async def stop(self) -> None:
        """Stop monitoring gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("ResourceMonitor stopped.")
