from __future__ import annotations

import threading
from collections import deque

BUCKET_BOUNDS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]


def _fmt_labels(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + inner + "}"


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[str, deque] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            dq = self._histograms.setdefault(name, deque(maxlen=10000))
            dq.append(seconds)

    def percentile(self, name: str, pct: float) -> float | None:
        with self._lock:
            dq = self._histograms.get(name)
            if not dq:
                return None
            values = sorted(dq)
        idx = min(int(len(values) * pct / 100.0), len(values) - 1)
        return round(values[idx], 6)

    def render_prometheus(self, extra_gauges: dict[str, float] | None = None) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            hists = {k: list(v) for k, v in self._histograms.items()}
        for (name, labels), value in sorted(counters.items()):
            lines.append(f"{name}{_fmt_labels(dict(labels))} {value}")
        for (name, labels), value in sorted(gauges.items()):
            lines.append(f"{name}{_fmt_labels(dict(labels))} {value}")
        for name, values in sorted(hists.items()):
            total = sum(values)
            count = len(values)
            lines.append(f'{name}_count{{name="{name}"}} {count}')
            lines.append(f'{name}_sum{{name="{name}"}} {round(total, 6)}')
            cumulative = 0
            for bound in BUCKET_BOUNDS:
                cumulative += sum(1 for v in values if v <= bound)
                lines.append(f'{name}_bucket{{name="{name}",le="{bound}"}} {cumulative}')
            lines.append(f'{name}_bucket{{name="{name}",le="+Inf"}} {count}')
        for name, value in sorted((extra_gauges or {}).items()):
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


METRICS = MetricsRegistry()
