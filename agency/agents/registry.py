from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentSpec:
    name: str
    role: str
    kind: str
    stage: str | None = None
    status: str = "active"
    notes: str = ""


AGENTS: list[AgentSpec] = [
    AgentSpec("Intake Agent", "Validates and normalizes the production brief into a machine spec", "pipeline", "intake"),
    AgentSpec("Project Manager", "Owns project lifecycle state and status transitions", "service"),
    AgentSpec("Master Orchestrator", "Plans, delegates, executes and repairs the production workflow", "core"),
    AgentSpec("Research Agent", "Extracts key points; flags numeric claims for verification", "pipeline", "research"),
    AgentSpec("Creative Director", "Concept, tone, palette and music mood selection", "pipeline", "creative_direction"),
    AgentSpec("Script Agent", "Generates structured narration script (LLM-optional)", "pipeline", "script_writing"),
    AgentSpec("Fact Checker", "Marks unverified claims inside research output", "pipeline", "research"),
    AgentSpec("Storyboard Agent", "Distributes narration across timed scenes", "pipeline", "storyboard"),
    AgentSpec("Asset Intelligence Agent", "Tags assets and computes provenance metadata", "cross-cutting"),
    AgentSpec("Asset Acquisition Agent", "Registers external assets and generates procedural visuals", "pipeline", "asset_acquisition"),
    AgentSpec("Rights/License Agent", "Blocks unknown-rights assets from commercial use", "pipeline", "asset_acquisition"),
    AgentSpec("Voice/TTS Agent", "Narration synthesis via routed provider chain", "pipeline", "narration"),
    AgentSpec("Generative Media Agent", "Procedural image generation (ComfyUI-adapter ready)", "capability"),
    AgentSpec("Video Generation Agent", "Reserved: generative video provider adapter point", "reserved", None, "planned"),
    AgentSpec("Editorial Agent", "Scene timing, EDL construction, timeline validation", "pipeline", "editorial_assembly"),
    AgentSpec("Auto-Cleanup Agent", "Silence detection and removal on narration", "pipeline", "autocleanup"),
    AgentSpec("Motion Graphics Agent", "Title cards and lower thirds with time windows", "pipeline", "motion_graphics"),
    AgentSpec("Animation Agent", "Ken Burns / zoompan motion over stills", "capability", "editorial_assembly"),
    AgentSpec("Color Agent", "Saturation/contrast grading pass", "pipeline", "color_grade"),
    AgentSpec("Sound Design Agent", "Mixing, ducking weights, loudness normalization", "pipeline", "audio_mix"),
    AgentSpec("Music Agent", "Royalty-free-by-construction procedural music bed", "capability", "audio_mix"),
    AgentSpec("Caption Agent", "ASS/SRT generation, styling, safe zones, burn-in", "pipeline", "burn_captions"),
    AgentSpec("Render Agent", "FFmpeg render graph execution (concat/mux/burn)", "pipeline", "rough_concat"),
    AgentSpec("Technical QA Agent", "Container/codec/duration/loudness/sync verification", "pipeline", "technical_qa"),
    AgentSpec("Creative QA Agent", "Script coverage, branding, readability checks", "pipeline", "creative_qa"),
    AgentSpec("Multimodal QA Agent", "Brief→script→timeline→render consistency scoring", "pipeline", "multimodal_qa"),
    AgentSpec("Repair Agent", "Classifies failures and drives targeted repairs", "cross-cutting"),
    AgentSpec("Publishing Agent", "Platform variants, thumbnails, metadata manifests", "pipeline", "delivery"),
    AgentSpec("Analytics Agent", "Delivery metrics recording (external ingestion planned)", "service", "finalize"),
    AgentSpec("Memory Agent", "Project/script/timeline persistence and history", "service"),
    AgentSpec("Model Router", "Capability-first model/provider selection with fallbacks", "core"),
    AgentSpec("Security Agent", "AuthN/Z, upload scanning, SSRF/path guards", "service"),
    AgentSpec("Observability Agent", "Structured events, audit logs, request tracing", "service"),
    AgentSpec("FinOps Agent", "Per-project/job/task cost accounting", "service", "finalize"),
    AgentSpec("Human Approval Agent", "Pre-publish approval gate when policy requires", "gate", "delivery"),
]


def get_registry() -> list[dict]:
    return [a.__dict__ | {} for a in AGENTS]


def active_agent_count() -> int:
    return sum(1 for a in AGENTS if a.status == "active")


__all__ = ["AGENTS", "get_registry", "active_agent_count"]
