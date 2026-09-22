"""
Domain packs.

A pack is the declarative description of one kind of world: what exists, what
agents can do, what they can see, and what should be measured. The engine
executes packs; it has no built-in knowledge of any domain.

Structure:

{
  "domain": "market",
  "description": "Continuous prediction market with an order book",
  "tracks": ["main"],                    # parallel worlds (social uses two)
  "kernels": {"orderbook": {...}},       # kernels this pack needs, with config
  "resources": {"cash": {"initial": 1000}, "position": {"allow_negative": true}},
  "entities": [ {"key": "BTC-100K", "type": "Market", "attrs": {...}} ],
  "agent_attrs": {"archetype": "..."},   # per-agent attributes seeded at start
  "actions": [ {...} ],                  # see ActionSpec
  "observation": {...},                  # see ObservationBuilder
  "metrics": [ {...} ],                  # see MetricsEngine
  "events": [ {...} ],                   # scheduled world events (shocks)
  "verbalizers": {"PLACE_ORDER": "{actor} bid {size} at {limit}"}
}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class PackValidationError(Exception):
    """Raised when a domain pack is malformed."""


VALID_OPS = {
    "set", "add", "transfer", "append", "link", "unlink", "require", "noop",
}

VALID_ARG_TYPES = {"string", "number", "integer", "boolean", "entity"}


@dataclass
class DomainPack:
    domain: str
    description: str = ""
    tracks: List[str] = field(default_factory=lambda: ["main"])
    kernels: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    resources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    agent_attrs: Dict[str, Any] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    observation: Dict[str, Any] = field(default_factory=dict)
    metrics: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    verbalizers: Dict[str, str] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def negative_resources(self) -> List[str]:
        """Resources allowed to go below zero, e.g. a short position."""
        return [
            name for name, spec in self.resources.items()
            if isinstance(spec, dict) and spec.get("allow_negative")
        ]

    def action_verbs(self) -> List[str]:
        return [a["verb"] for a in self.actions]

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.raw)


def load_pack(source: Any) -> DomainPack:
    """Load a pack from a path, a JSON string, or an already-parsed dict."""
    if isinstance(source, DomainPack):
        return source

    if isinstance(source, dict):
        data = source
    elif isinstance(source, str) and os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif isinstance(source, str):
        try:
            data = json.loads(source)
        except json.JSONDecodeError as exc:
            raise PackValidationError(f"pack is not valid JSON and not a readable path: {exc}")
    else:
        raise PackValidationError(f"cannot load a pack from {type(source).__name__}")

    validate_pack(data)

    return DomainPack(
        domain=data["domain"],
        description=data.get("description", ""),
        tracks=data.get("tracks") or ["main"],
        kernels=data.get("kernels", {}) or {},
        resources=data.get("resources", {}) or {},
        entities=data.get("entities", []) or [],
        agent_attrs=data.get("agent_attrs", {}) or {},
        actions=data["actions"],
        observation=data.get("observation", {}) or {},
        metrics=data.get("metrics", []) or [],
        events=data.get("events", []) or [],
        verbalizers=data.get("verbalizers", {}) or {},
        raw=data,
    )


def validate_pack(data: Dict[str, Any]) -> None:
    """
    Structural validation. Runs before a pack can execute, so an LLM-authored
    pack cannot produce a runtime explosion halfway through a simulation.
    """
    if not isinstance(data, dict):
        raise PackValidationError("pack must be a JSON object")

    if not data.get("domain"):
        raise PackValidationError("pack must declare a 'domain' name")

    actions = data.get("actions")
    if not isinstance(actions, list) or not actions:
        raise PackValidationError("pack must declare a non-empty 'actions' list")

    known_kernels = set((data.get("kernels") or {}).keys())
    seen_verbs = set()

    for i, action in enumerate(actions):
        where = f"actions[{i}]"
        if not isinstance(action, dict):
            raise PackValidationError(f"{where} must be an object")

        verb = action.get("verb")
        if not verb or not isinstance(verb, str):
            raise PackValidationError(f"{where} must have a string 'verb'")
        if not verb.isupper():
            raise PackValidationError(f"{where} verb '{verb}' must be UPPER_SNAKE_CASE")
        if verb in seen_verbs:
            raise PackValidationError(f"duplicate action verb '{verb}'")
        seen_verbs.add(verb)

        args = action.get("args", {}) or {}
        if not isinstance(args, dict):
            raise PackValidationError(f"{where} 'args' must be an object")
        for arg_name, arg_type in args.items():
            base = str(arg_type).split("[")[0]
            if base not in VALID_ARG_TYPES and not str(arg_type).startswith("enum["):
                raise PackValidationError(
                    f"{where} arg '{arg_name}' has unknown type '{arg_type}'; "
                    f"valid: {sorted(VALID_ARG_TYPES)} or enum[a,b,c]"
                )

        effects = action.get("effects", []) or []
        if not isinstance(effects, list):
            raise PackValidationError(f"{where} 'effects' must be a list")
        for j, effect in enumerate(effects):
            _validate_effect(effect, f"{where}.effects[{j}]", known_kernels)

    for name, spec in (data.get("resources") or {}).items():
        if not isinstance(spec, dict):
            raise PackValidationError(f"resource '{name}' spec must be an object")

    for i, entity in enumerate(data.get("entities") or []):
        if not isinstance(entity, dict) or "key" not in entity or "type" not in entity:
            raise PackValidationError(f"entities[{i}] needs 'key' and 'type'")

    for i, metric in enumerate(data.get("metrics") or []):
        if not isinstance(metric, dict) or "name" not in metric or "op" not in metric:
            raise PackValidationError(f"metrics[{i}] needs 'name' and 'op'")


def _validate_effect(effect: Any, where: str, known_kernels: set) -> None:
    if not isinstance(effect, dict):
        raise PackValidationError(f"{where} must be an object")
    op = effect.get("op")
    if not op:
        raise PackValidationError(f"{where} must have an 'op'")

    if op.startswith("kernel."):
        parts = op.split(".")
        if len(parts) != 3:
            raise PackValidationError(
                f"{where} kernel op must be 'kernel.<name>.<method>', got '{op}'"
            )
        if parts[1] not in known_kernels:
            raise PackValidationError(
                f"{where} uses kernel '{parts[1]}' which the pack does not declare "
                f"in 'kernels' (declared: {sorted(known_kernels) or 'none'})"
            )
        return

    if op not in VALID_OPS:
        raise PackValidationError(
            f"{where} has unknown op '{op}'; valid: {sorted(VALID_OPS)} "
            f"or kernel.<name>.<method>"
        )


def builtin_pack_dir() -> str:
    """Directory holding the shipped packs (backend/domains/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "domains"))


def load_builtin(name: str) -> DomainPack:
    path = os.path.join(builtin_pack_dir(), f"{name}.json")
    if not os.path.exists(path):
        raise PackValidationError(f"no built-in domain pack named '{name}' at {path}")
    return load_pack(path)


def list_builtins() -> List[str]:
    directory = builtin_pack_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(
        f[:-5] for f in os.listdir(directory) if f.endswith(".json")
    )
