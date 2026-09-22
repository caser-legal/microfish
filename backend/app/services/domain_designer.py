"""
Domain designer.

Decides what kind of world a simulation should be, from the user's seed
document and simulation prompt. This is what makes MicroFish a general
simulator rather than a social-media simulator.

Two paths:
  1. Select a built-in pack when one fits (social, market, allocation).
  2. Author a new pack when nothing fits, using the built-ins as examples.

An authored pack is validated against the pack schema before it can run, so a
malformed design fails here with a clear message rather than halfway through a
simulation. Packs are declarative data; they never contain executable code.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.domain_designer')

# The engine lives under backend/scripts/; reuse its pack validator so the
# designer and the runner agree on exactly what a valid pack is.
_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:
    from engine.pack import PackValidationError, list_builtins, load_builtin, validate_pack
except ImportError as exc:  # pragma: no cover - surfaced at call time instead
    logger.error(f"Could not import the simulation engine: {exc}")
    PackValidationError = Exception  # type: ignore

    def list_builtins():  # type: ignore
        return []

    def load_builtin(name):  # type: ignore
        raise RuntimeError("simulation engine unavailable")

    def validate_pack(data):  # type: ignore
        raise RuntimeError("simulation engine unavailable")


SELECTION_PROMPT = """You are choosing how to simulate a scenario.

Available built-in simulation domains:
{domain_catalog}

Read the simulation requirement and the source document, then decide.

Choose an existing domain when the scenario genuinely fits it. Choose to design
a new domain only when none of the built-ins can express what needs to be
measured.

Guidance:
- "social" fits when the subject is public reaction, narrative spread, opinion
  and reputation.
- "market" fits when participants trade, quote prices, hold positions, and
  profit or lose money.
- "allocation" fits when parties compete over a finite shared resource,
  negotiate, and form coalitions.
- Design a new domain for anything else: elections, epidemics, supply chains,
  military logistics, sports, ecosystems, legal proceedings.

Return JSON only:
{{
  "decision": "use_builtin" | "design_new",
  "domain": "<builtin name, when use_builtin>",
  "new_domain_name": "<short lowercase name, when design_new>",
  "reasoning": "one or two sentences",
  "what_must_be_measured": ["the quantitative outcomes this scenario demands"]
}}"""


DESIGN_PROMPT = """You are designing a simulation domain: a declarative
description of a world that a multi-agent engine will execute.

Design a domain named "{domain_name}" for this scenario.

THE ENGINE CONTRACT

A domain pack is JSON with these fields:

- "domain": short lowercase name
- "description": one sentence describing the world
- "tracks": list of parallel worlds; use ["main"] unless the scenario genuinely
  needs separate arenas
- "kernels": pre-built mechanics this domain needs, with configuration
- "resources": what agents hold; each has {{"initial": <number>}} and optionally
  {{"allow_negative": true}}
- "entities": objects that exist at the start; each has "key", "type", "attrs",
  and optionally "resources" to give that entity a starting balance
- "agent_attrs": attributes every agent starts with
- "actions": the verbs agents can choose (see below)
- "observation": what agents can see each turn
- "metrics": what gets computed at the end
- "events": scheduled world events (shocks, deadlines, resolutions)
- "verbalizers": templates rendering each action as a sentence

AVAILABLE KERNELS (you may only use these):
- "ledger": position and profit-and-loss accounting.
  Methods: trade(holder, resource, quantity, price), mark_to_market(resource,
  price), settle(resource, price)
- "orderbook": limit order book with matching.
  Methods: submit(book, side, size, limit, actor), cancel(book, actor),
  shock(book, price), quote(book)
- "content": feed ranking and engagement.
  Methods: feed(viewer, limit), trending(limit), engage(target, relation)
- "diffusion": spread through a contact network.
  Methods: seed_infection(target), expose(source, target), tick(), census()

EFFECT OPERATIONS (an action's "effects" is a list of these):
- {{"op": "set", "entity": "...", "attr": "...", "value": ...}}
- {{"op": "add", "holder": "$actor", "resource": "...", "amount": <number>}}
- {{"op": "transfer", "from": "...", "to": "...", "resource": "...", "amount": ...}}
- {{"op": "append", "type": "...", "attrs": {{...}}, "as": "new_key"}}
- {{"op": "link", "from": "$actor", "rel": "...", "to": "..."}}
- {{"op": "unlink", "from": "$actor", "rel": "...", "to": "..."}}
- {{"op": "require", "cond": {{...}}, "message": "why this failed"}}
- {{"op": "noop"}}
- {{"op": "kernel.<kernel>.<method>", ...params}}

REFERENCES inside effects:
- "$actor" the acting agent, "$args.<name>" an argument, "$round" the round
- "$balance.<resource>" the actor's balance
- "$entity.<key>.<attr>" an attribute of an entity
- Arithmetic: {{"mul": [a, b]}}, {{"add": [...]}}, {{"sub": [a, b]}}, {{"div": [a, b]}}

ARGUMENT TYPES: "string", "number", "integer", "boolean", "entity",
"enum[a,b,c]". Suffix with "?" to make it optional.

METRIC OPERATIONS:
- {{"op": "group_sum", "over": "agent.<attr>", "by": "agent.archetype"}}
- {{"op": "rank", "over": "agent.<attr>", "limit": 10, "label": "name"}}
- {{"op": "count", "by": "verb" | "actor", "verb": "<optional filter>"}}
- {{"op": "resource_total", "resource": "...", "by": "archetype"}}
- {{"op": "failure_rate"}}
- {{"op": "series"}}

DESIGN RULES (these matter most)

1. Actions must be able to FAIL. A world where every action succeeds measures
   nothing. Use finite resources, "require" guards, and transfers that can run
   short, so scarcity and competition are real.
2. Outcomes must be COMPUTED from state, not narrated. Design resources and
   metrics such that the scenario's central question is answered by arithmetic.
3. Give agents 4-7 actions. Enough for meaningful choice, few enough to choose
   well.
4. Every action needs a clear description; agents read it to decide.
5. Include a "WAIT" or "DO_NOTHING" style action so agents can decline to act.
6. Verbs must be UPPER_SNAKE_CASE and unique.
7. Only reference kernels you declared in "kernels".
8. Write everything in English.

REFERENCE EXAMPLE
{example_pack}

Return only the JSON pack. No commentary."""


class DomainDesigner:
    """Selects or authors the domain pack for a simulation."""

    MAX_DESIGN_ATTEMPTS = 3

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    # ------------------------------------------------------------------

    def design(
        self,
        simulation_requirement: str,
        document_text: str = "",
        force_domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Decide the domain for a simulation.

        Returns:
            {
              "domain": name,
              "source": "forced" | "builtin" | "designed" | "fallback",
              "pack": <pack dict>,
              "reasoning": str,
              "measures": [str],
            }
        """
        if force_domain:
            try:
                pack = load_builtin(force_domain)
                logger.info(f"Using explicitly requested domain '{force_domain}'")
                return {
                    "domain": force_domain,
                    "source": "forced",
                    "pack": pack.to_dict(),
                    "reasoning": f"Domain '{force_domain}' was explicitly requested.",
                    "measures": [],
                }
            except Exception as exc:
                logger.warning(f"Requested domain '{force_domain}' unavailable: {exc}")

        try:
            decision = self._select(simulation_requirement, document_text)
        except Exception as exc:
            logger.warning(f"Domain selection failed ({exc}); falling back to '{Config.DEFAULT_DOMAIN}'")
            return self._fallback(f"Domain selection failed: {exc}")

        reasoning = decision.get("reasoning", "")
        measures = decision.get("what_must_be_measured", []) or []

        if decision.get("decision") == "use_builtin":
            name = decision.get("domain", Config.DEFAULT_DOMAIN)
            try:
                pack = load_builtin(name)
                logger.info(f"Selected built-in domain '{name}': {reasoning}")
                return {
                    "domain": name,
                    "source": "builtin",
                    "pack": pack.to_dict(),
                    "reasoning": reasoning,
                    "measures": measures,
                }
            except Exception as exc:
                logger.warning(f"Built-in domain '{name}' failed to load: {exc}")
                return self._fallback(f"Built-in '{name}' unavailable: {exc}")

        name = decision.get("new_domain_name") or "custom"
        try:
            pack = self._author(name, simulation_requirement, document_text, measures)
            logger.info(f"Authored new domain '{pack.get('domain', name)}': {reasoning}")
            return {
                "domain": pack.get("domain", name),
                "source": "designed",
                "pack": pack,
                "reasoning": reasoning,
                "measures": measures,
            }
        except Exception as exc:
            logger.warning(f"Could not author domain '{name}': {exc}")
            return self._fallback(f"Domain design failed: {exc}")

    # ------------------------------------------------------------------

    def _select(self, requirement: str, document_text: str) -> Dict[str, Any]:
        catalog = self._catalog()
        messages = [
            {"role": "system", "content": SELECTION_PROMPT.format(domain_catalog=catalog)},
            {
                "role": "user",
                "content": (
                    f"## Simulation requirement\n\n{requirement}\n\n"
                    f"## Source document (excerpt)\n\n{document_text[:6000]}"
                ),
            },
        ]
        return self.llm_client.chat_json(messages=messages, temperature=0.2)

    def _author(
        self,
        name: str,
        requirement: str,
        document_text: str,
        measures: List[str],
    ) -> Dict[str, Any]:
        example = self._example_pack()
        system = DESIGN_PROMPT.format(domain_name=name, example_pack=example)

        user = (
            f"## Simulation requirement\n\n{requirement}\n\n"
            f"## Source document (excerpt)\n\n{document_text[:6000]}\n\n"
            f"## This simulation must be able to measure\n\n"
            + "\n".join(f"- {m}" for m in measures)
        )

        last_error = None
        for attempt in range(self.MAX_DESIGN_ATTEMPTS):
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            if last_error:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous design was rejected by the validator:\n{last_error}\n\n"
                        "Return a corrected pack that fixes exactly that problem."
                    ),
                })

            try:
                pack = self.llm_client.chat_json(messages=messages, temperature=0.3)
                pack.setdefault("domain", name)
                validate_pack(pack)
                self._check_quality(pack)
                return pack
            except Exception as exc:
                last_error = str(exc)
                logger.warning(f"Design attempt {attempt + 1} rejected: {last_error}")

        raise ValueError(f"pack failed validation after {self.MAX_DESIGN_ATTEMPTS} attempts: {last_error}")

    @staticmethod
    def _check_quality(pack: Dict[str, Any]) -> None:
        """
        Beyond structural validity, reject designs that cannot measure anything.
        A world where nothing is scarce and nothing is computed is not a
        simulation.
        """
        if len(pack.get("actions", [])) < 2:
            raise ValueError("a domain needs at least 2 actions to present a real choice")

        if not pack.get("metrics"):
            raise ValueError("a domain must declare metrics, or nothing can be measured")

        has_scarcity = bool(pack.get("resources")) or any(
            effect.get("op") in ("transfer", "require")
            or str(effect.get("op", "")).startswith("kernel.")
            for action in pack.get("actions", [])
            for effect in action.get("effects", []) or []
        )
        if not has_scarcity:
            raise ValueError(
                "no action can fail: declare resources, transfers, or require guards "
                "so that constraints actually bind"
            )

    # ------------------------------------------------------------------

    @staticmethod
    def _catalog() -> str:
        lines = []
        for name in list_builtins():
            try:
                pack = load_builtin(name)
                lines.append(
                    f"- {name}: {pack.description}\n"
                    f"    actions: {', '.join(pack.action_verbs())}\n"
                    f"    measures: {', '.join(m['name'] for m in pack.metrics)}"
                )
            except Exception:
                continue
        return "\n".join(lines) if lines else "(none available)"

    @staticmethod
    def _example_pack() -> str:
        """The allocation pack is the clearest example of scarcity done right."""
        for name in ("allocation", "market", "social"):
            try:
                return json.dumps(load_builtin(name).to_dict(), indent=2)[:6000]
            except Exception:
                continue
        return "{}"

    @staticmethod
    def _fallback(reason: str) -> Dict[str, Any]:
        name = Config.DEFAULT_DOMAIN
        try:
            pack = load_builtin(name).to_dict()
        except Exception:
            pack = {}
        return {
            "domain": name,
            "source": "fallback",
            "pack": pack,
            "reasoning": f"{reason} Using the default '{name}' domain.",
            "measures": [],
        }


def available_domains() -> List[Dict[str, str]]:
    """Catalog of built-in domains, for the API and the frontend."""
    out = []
    for name in list_builtins():
        try:
            pack = load_builtin(name)
            out.append({
                "name": name,
                "description": pack.description,
                "actions": pack.action_verbs(),
                "tracks": pack.tracks,
            })
        except Exception:
            continue
    return out
