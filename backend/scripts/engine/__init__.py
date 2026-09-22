"""
MicroFish simulation engine.

A domain-agnostic multi-agent simulation core. Nothing in this package knows
about social media, markets, or any other specific domain: the rules of the
world are supplied at runtime as a domain pack (see pack.py).

The engine's contract:
  - A domain pack declares resources, entities, actions, observations and metrics.
  - Agents choose an action each round via an LLM, constrained to the pack's verbs.
  - Actions apply declarative effects to shared world state, transactionally.
  - Actions can FAIL when state constraints reject them, and the failure is fed
    back to the agent on its next turn.
  - Metrics are computed from world state, so quantitative outcomes are measured
    rather than asserted by the LLM.
"""

from .pack import DomainPack, PackValidationError, load_pack
from .state import WorldState
from .effects import EffectError, EffectEvaluator
from .actions import ActionRegistry, ActionSpec, ActionValidationError
from .observation import ObservationBuilder
from .metrics import MetricsEngine
from .agent import Agent, AgentProfile, ChosenAction

__all__ = [
    "DomainPack",
    "PackValidationError",
    "load_pack",
    "WorldState",
    "EffectError",
    "EffectEvaluator",
    "ActionRegistry",
    "ActionSpec",
    "ActionValidationError",
    "ObservationBuilder",
    "MetricsEngine",
    "Agent",
    "AgentProfile",
    "ChosenAction",
]
