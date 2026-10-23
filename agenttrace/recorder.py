"""Tiny instrumentation API; no model, network, or paid service required."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from .models import Run, Step


def now():
    return datetime.now(timezone.utc).isoformat()


class TraceRecorder:
    def __init__(self, name, *, simulated=False, run_id=None, metadata=None):
        self.id = run_id or str(uuid4())
        self.name = name
        self.simulated = simulated
        self.metadata = metadata or {}
        self.started_at = now()
        self.steps = []

    @contextmanager
    def step(self, step_id, name, *, kind="agent", tool=None, input=None):
        if any(s.id == step_id for s in self.steps):
            raise ValueError(f"重复步骤 id：{step_id}")
        item = Step(step_id, name, kind, "success", now(), 0, input=input, tool=tool)
        self.steps.append(item)
        start = perf_counter()
        try:
            yield item
        except Exception as exc:
            item.status = "failed"
            item.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            item.duration_ms = round((perf_counter() - start) * 1000, 3)

    def finish(self):
        return Run(self.id, self.name, "failed" if any(s.status == "failed" for s in self.steps) else "success", self.started_at, list(self.steps), self.simulated, self.metadata)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.finish().to_json(), encoding="utf-8")
