"""
Action registry.

Replaces the old fixed ActionType enum and the if/elif dispatch ladder. Verbs,
their arguments, and their effects all come from the domain pack, so a market
pack gets PLACE_ORDER and a social pack gets CREATE_POST without the engine
knowing what either means.

Argument validation happens before any effect runs, so a malformed LLM response
fails cleanly with a reason the agent can act on next round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class ActionValidationError(Exception):
    """Raised when an agent's chosen action does not fit its declared schema."""


@dataclass
class ActionSpec:
    verb: str
    description: str = ""
    args: Dict[str, str] = field(default_factory=dict)
    effects: List[Dict[str, Any]] = field(default_factory=list)
    cost: Dict[str, float] = field(default_factory=dict)
    terminal: bool = False

    def arg_names(self) -> List[str]:
        return list(self.args.keys())

    def describe(self) -> str:
        """One-line description used in the agent's prompt."""
        if self.args:
            parts = [f"{name}: {type_}" for name, type_ in self.args.items()]
            signature = ", ".join(parts)
            return f"{self.verb}({signature}) - {self.description}"
        return f"{self.verb}() - {self.description}"


class ActionRegistry:
    def __init__(self, specs: List[ActionSpec]):
        self._specs: Dict[str, ActionSpec] = {s.verb: s for s in specs}

    @classmethod
    def from_pack(cls, pack) -> "ActionRegistry":
        specs = []
        for action in pack.actions:
            specs.append(ActionSpec(
                verb=action["verb"],
                description=action.get("description", ""),
                args=action.get("args", {}) or {},
                effects=action.get("effects", []) or [],
                cost=action.get("cost", {}) or {},
                terminal=bool(action.get("terminal", False)),
            ))
        return cls(specs)

    def __contains__(self, verb: str) -> bool:
        return verb in self._specs

    def __iter__(self):
        return iter(self._specs.values())

    def __len__(self) -> int:
        return len(self._specs)

    def get(self, verb: str) -> Optional[ActionSpec]:
        return self._specs.get(verb)

    def verbs(self) -> List[str]:
        return list(self._specs.keys())

    def describe_all(self) -> str:
        return "\n".join(f"  - {spec.describe()}" for spec in self._specs.values())

    # ------------------------------------------------------------------

    def validate(self, verb: str, args: Dict[str, Any]) -> Tuple[ActionSpec, Dict[str, Any]]:
        """
        Check a chosen action against its schema and coerce argument types.

        Returns the spec and the cleaned args. Raises ActionValidationError
        with a message written for the agent to read.
        """
        spec = self._specs.get(verb)
        if spec is None:
            raise ActionValidationError(
                f"'{verb}' is not an available action. Choose one of: "
                f"{', '.join(self.verbs())}"
            )

        args = args or {}
        cleaned: Dict[str, Any] = {}

        for name, declared in spec.args.items():
            optional = str(declared).endswith("?")
            type_str = str(declared).rstrip("?")

            if name not in args or args[name] is None or args[name] == "":
                if optional:
                    continue
                raise ActionValidationError(
                    f"{verb} requires the argument '{name}' ({type_str})"
                )

            cleaned[name] = self._coerce(verb, name, type_str, args[name])

        return spec, cleaned

    @staticmethod
    def _coerce(verb: str, name: str, type_str: str, value: Any) -> Any:
        if type_str.startswith("enum["):
            allowed = [v.strip() for v in type_str[5:-1].split(",")]
            text = str(value).strip().lower()
            for option in allowed:
                if text == option.lower():
                    return option
            raise ActionValidationError(
                f"{verb} argument '{name}' must be one of {allowed}, got '{value}'"
            )

        if type_str == "number":
            try:
                return float(value)
            except (TypeError, ValueError):
                raise ActionValidationError(
                    f"{verb} argument '{name}' must be a number, got '{value}'"
                )

        if type_str == "integer":
            try:
                return int(float(value))
            except (TypeError, ValueError):
                raise ActionValidationError(
                    f"{verb} argument '{name}' must be an integer, got '{value}'"
                )

        if type_str == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "yes", "1")

        # string / entity
        return str(value)
