"""
Agent decision loop.

An agent sees an observation, is told which actions exist in this domain, and
answers with one action as JSON. The engine validates and executes it.

This replaces the previous agent implementation, which never actually ran:
  - it called re.search without importing re, so every parse raised NameError
    into a bare except and silently returned DO_NOTHING;
  - its decide_action method had no callers;
  - LLMAction() was constructed with no arguments against a dataclass that
    required action_type.

Here the decision loop is the only path, parsing is strict-then-forgiving, and
a failure to parse is reported as a real failure rather than hidden.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .actions import ActionRegistry, ActionValidationError


@dataclass
class AgentProfile:
    """Identity and behaviour parameters for one agent."""
    agent_id: int
    name: str
    bio: str = ""
    persona: str = ""
    archetype: str = ""
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    activity_level: float = 0.5
    attrs: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable world-state key for this agent."""
        return f"agent_{self.agent_id}"


@dataclass
class ChosenAction:
    verb: str
    args: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    parse_error: Optional[str] = None


SYSTEM_TEMPLATE = """You are {name}, acting inside a simulation of: {domain_description}

{persona_block}

You act by choosing exactly ONE action per turn from the list below. These are \
the only actions that exist in this world.

AVAILABLE ACTIONS:
{action_list}

Respond with a single JSON object and nothing else:
{{"action": "VERB", "args": {{...}}, "reasoning": "one short sentence"}}

Rules:
- "action" must be exactly one of the verbs listed above.
- "args" must contain every required argument for that verb, with correct types.
- Stay in character. Your decisions should follow from who you are and what you \
can currently see.
- Actions can be REJECTED by the world (insufficient funds, invalid target, \
duplicate). If you are told your last action failed, choose differently.
- Write all output in English."""


class Agent:
    def __init__(
        self,
        profile: AgentProfile,
        registry: ActionRegistry,
        llm_client,
        domain_description: str = "a simulated world",
    ):
        self.profile = profile
        self.registry = registry
        self.llm = llm_client
        self.domain_description = domain_description
        self.memory: List[Dict[str, Any]] = []

    @property
    def agent_id(self) -> int:
        return self.profile.agent_id

    @property
    def key(self) -> str:
        return self.profile.key

    @property
    def name(self) -> str:
        return self.profile.name

    def remember(self, item: Dict[str, Any], cap: int = 30) -> None:
        self.memory.append(item)
        if len(self.memory) > cap:
            self.memory = self.memory[-cap:]

    def is_active_at(self, hour: int, rng) -> bool:
        """Whether this agent takes a turn this round."""
        if self.profile.active_hours and hour not in self.profile.active_hours:
            return rng.random() < self.profile.activity_level * 0.1
        return rng.random() < max(0.0, min(1.0, self.profile.activity_level))

    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        persona_parts = []
        if self.profile.bio:
            persona_parts.append(self.profile.bio)
        if self.profile.persona:
            persona_parts.append(self.profile.persona[:1500])
        if self.profile.archetype:
            persona_parts.append(f"Your archetype in this simulation: {self.profile.archetype}.")
        persona_block = "\n\n".join(persona_parts) if persona_parts else ""

        return SYSTEM_TEMPLATE.format(
            name=self.profile.name,
            domain_description=self.domain_description,
            persona_block=persona_block,
            action_list=self.registry.describe_all(),
        )

    def build_user_prompt(self, observation_text: str) -> str:
        recent = ""
        if self.memory:
            lines = [
                f"  round {m.get('round')}: you chose {m.get('verb')}"
                + ("" if m.get("success", True) else f" (rejected: {m.get('reason')})")
                for m in self.memory[-4:]
            ]
            recent = "\n\nYOUR RECENT ACTIONS:\n" + "\n".join(lines)

        return (
            f"{observation_text}{recent}\n\n"
            "Choose your single action now. Respond with only the JSON object."
        )

    # ------------------------------------------------------------------

    async def decide(self, observation_text: str, temperature: float = 0.8) -> ChosenAction:
        """Ask the LLM for one action. Never raises; returns a parse_error instead."""
        messages = [
            {"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": self.build_user_prompt(observation_text)},
        ]

        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.llm.chat(messages, temperature=temperature),
            )
        except Exception as exc:
            return ChosenAction(verb="", parse_error=f"LLM call failed: {exc}")

        return self.parse_response(raw)

    def parse_response(self, raw: str) -> ChosenAction:
        """
        Extract an action from the model's reply.

        Tries strict JSON, then a JSON object embedded in prose, then a bare
        verb mention. Anything else is an explicit parse error.
        """
        if not raw or not raw.strip():
            return ChosenAction(verb="", parse_error="empty response from model")

        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()

        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    data = None

        if isinstance(data, dict):
            verb = str(data.get("action") or data.get("verb") or "").strip().upper()
            args = data.get("args") or data.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}
            if verb:
                return ChosenAction(
                    verb=verb,
                    args=args,
                    reasoning=str(data.get("reasoning", ""))[:300],
                )

        # Last resort: the model named a verb without valid JSON.
        for verb in self.registry.verbs():
            if re.search(rf"\b{re.escape(verb)}\b", text):
                return ChosenAction(
                    verb=verb,
                    args={},
                    reasoning="recovered from unstructured response",
                    parse_error="response was not valid JSON; recovered the verb only",
                )

        return ChosenAction(
            verb="",
            parse_error=f"could not parse an action from the response: {text[:200]}",
        )

    def validate(self, chosen: ChosenAction):
        """Validate against the registry. Raises ActionValidationError."""
        return self.registry.validate(chosen.verb, chosen.args)
