from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("agency.router")


@dataclass
class ModelCandidate:
    provider: str
    model: str
    task_type: str
    quality: float
    cost_per_1k_usd: float
    latency_s: float
    requires: str = ""
    notes: str = ""


@dataclass
class ProviderHealth:
    provider: str
    healthy: bool = True
    last_check: float = 0.0
    detail: str = ""

    def fresh(self, ttl: float = 120.0) -> bool:
        return (time.time() - self.last_check) < ttl


HEALTH: dict[str, ProviderHealth] = {}


def check_provider_health(provider: str) -> ProviderHealth:
    entry = HEALTH.get(provider)
    if entry is not None and entry.fresh():
        return entry
    healthy, detail = True, "ok"
    if provider == "openai":
        from agency.config import get_settings

        settings = get_settings()
        if not settings.openai_api_key:
            healthy, detail = False, "no api key"
        else:
            try:
                resp = httpx.get(f"{settings.openai_base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {settings.openai_api_key}"}, timeout=6)
                healthy = resp.status_code < 500
                detail = f"status {resp.status_code}"
            except Exception as exc:
                healthy, detail = False, str(exc)[:200]
    elif provider == "comfyui":
        from agency.config import get_settings

        url = get_settings().comfyui_url
        if not url:
            healthy, detail = False, "not configured"
        else:
            try:
                resp = httpx.get(url.rstrip("/") + "/system_stats", timeout=5)
                healthy = resp.status_code == 200
                detail = f"status {resp.status_code}"
            except Exception as exc:
                healthy, detail = False, str(exc)[:200]
    elif provider == "edge-tts":
        try:
            import edge_tts  # noqa: F401

            healthy, detail = True, "library available"
        except Exception as exc:
            healthy, detail = False, str(exc)[:100]
    elif provider == "local-deterministic":
        healthy, detail = True, "always available"
    else:
        healthy, detail = False, "unknown provider"
    entry = ProviderHealth(provider=provider, healthy=healthy, last_check=time.time(), detail=detail)
    HEALTH[provider] = entry
    return entry


CATALOG: list[ModelCandidate] = [
    ModelCandidate("local-deterministic", "template-composer-v1", "text", 0.55, 0.0, 0.2),
    ModelCandidate("openai", "gpt-4o-mini", "text", 0.90, 0.0006, 2.5),
    ModelCandidate("local-deterministic", "procedural-image-v1", "image", 0.50, 0.0, 1.0),
    ModelCandidate("comfyui", "sdxl-1.0", "image", 0.92, 0.004, 12.0, requires="gpu"),
    ModelCandidate("synth-local", "synth-neutral-v1", "tts", 0.40, 0.0, 0.8),
    ModelCandidate("edge-tts", "neural-voice", "tts", 0.85, 0.0, 3.0),
]


def route(task_type: str, prefer_quality: bool = True) -> tuple[ModelCandidate | None, list[str]]:
    reasons: list[str] = []
    candidates = [c for c in CATALOG if c.task_type == task_type]
    if not candidates:
        return None, [f"no candidates for task {task_type}"]
    scored: list[tuple[float, ModelCandidate]] = []
    for c in sorted(candidates, key=lambda x: (-x.quality if prefer_quality else x.cost_per_1k_usd)):
        health = check_provider_health(c.provider)
        if not health.healthy:
            reasons.append(f"skip {c.provider}/{c.model}: {health.detail}")
            continue
        quality_score = c.quality * 10
        cost_penalty = min(c.cost_per_1k_usd * 1000, 10.0)
        latency_penalty = min(c.latency_s, 10.0)
        score = quality_score - cost_penalty - latency_penalty if prefer_quality else -cost_penalty - latency_penalty + c.quality * 2
        scored.append((score, c))
    if not scored:
        return None, reasons or ["all providers unhealthy"]
    scored.sort(key=lambda pair: -pair[0])
    best = scored[0][1]
    reasons.append(f"selected {best.provider}/{best.model}")
    return best, reasons


@dataclass
class RoutingDecision:
    candidate: ModelCandidate | None
    reasons: list[str] = field(default_factory=list)


__all__ = ["route", "check_provider_health", "CATALOG", "RoutingDecision", "ModelCandidate"]

