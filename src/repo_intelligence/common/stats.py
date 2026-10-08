"""Per-stage counters with a scope line printed before work starts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StageStats:
    stage: str
    scope: str = ""
    planned: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def announce(self, scope: str, planned: int) -> None:
        """Rule 10: resolved scope is visible in the first line of every stage."""
        self.scope, self.planned = scope, planned
        print(f"stage={self.stage} scope={scope} items={planned}", flush=True)

    def progress(self, done: int, every: int = 50) -> None:
        if done % every == 0 or done == self.planned:
            print(f"  {self.stage}: {done}/{self.planned} ok={self.succeeded} "
                  f"failed={self.failed} skipped={self.skipped}", flush=True)

    def fail(self, message: str) -> None:
        self.failed += 1
        if len(self.errors) < 20:
            self.errors.append(message[:300])

    def summary(self) -> str:
        return (f"{self.stage}: {self.succeeded} ok, {self.failed} failed, "
                f"{self.skipped} skipped of {self.planned} ({self.scope})")
