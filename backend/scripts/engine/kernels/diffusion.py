"""
Diffusion kernel.

Compartmental spread over the agent network: epidemics, rumours, technology
adoption, panic. Agents occupy a state (e.g. susceptible / exposed / adopted /
recovered) and transition probabilistically based on their neighbours.

Gives non-market, non-social domains a quantitative backbone so their outcomes
are measured rather than narrated.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List

from ..state import StateError


class DiffusionKernel:
    def __init__(self, state, config: Dict[str, Any] | None = None):
        self.state = state
        self.config = config or {}
        self.attr = self.config.get("state_attr", "condition")
        self.contact_rel = self.config.get("contact_relation", "contacts")
        self.transmission = float(self.config.get("transmission_rate", 0.15))
        self.recovery = float(self.config.get("recovery_rate", 0.08))
        self.susceptible = self.config.get("susceptible_state", "susceptible")
        self.infected = self.config.get("infected_state", "infected")
        self.recovered = self.config.get("recovered_state", "recovered")
        self._rng = random.Random(self.config.get("seed", 20260101))

    def seed_infection(
        self, ctx: Dict[str, Any], target: str = None, **_ignored
    ) -> Dict[str, Any]:
        target = str(target or ctx.get("actor"))
        self.state.set_attr(target, self.attr, self.infected)
        self.state.set_attr(target, "infected_at_round", ctx.get("round", 0))
        return {"infected": target}

    def expose(
        self, ctx: Dict[str, Any], source: str = None, target: str = "", **_ignored
    ) -> Dict[str, Any]:
        """
        One contact event. Transmission is probabilistic, so an action can
        legitimately succeed without causing infection.
        """
        source = str(source or ctx.get("actor"))
        target = str(target)
        if not target:
            raise StateError("expose requires a target")
        if source == target:
            raise StateError("cannot expose yourself")

        self.state.link(source, self.contact_rel, target)

        source_state = self.state.get_attr(source, self.attr, self.susceptible)
        target_state = self.state.get_attr(target, self.attr, self.susceptible)

        transmitted = False
        if source_state == self.infected and target_state == self.susceptible:
            if self._rng.random() < self.transmission:
                self.state.set_attr(target, self.attr, self.infected)
                self.state.set_attr(target, "infected_at_round", ctx.get("round", 0))
                self.state.set_attr(target, "infected_by", source)
                transmitted = True

        return {"contact": target, "transmitted": transmitted}

    def tick(self, ctx: Dict[str, Any], **_ignored) -> Dict[str, Any]:
        """Advance recovery for every infected agent. Called once per round."""
        rows = self.state.conn.execute(
            "SELECT key FROM world_entity WHERE type = 'Agent'"
        ).fetchall()
        recovered = 0
        for r in rows:
            if self.state.get_attr(r["key"], self.attr) == self.infected:
                if self._rng.random() < self.recovery:
                    self.state.set_attr(r["key"], self.attr, self.recovered)
                    self.state.set_attr(r["key"], "recovered_at_round", ctx.get("round", 0))
                    recovered += 1
        return {"newly_recovered": recovered, **self.census(ctx)}

    def census(self, ctx: Dict[str, Any], **_ignored) -> Dict[str, Any]:
        """Current population counts by state."""
        rows = self.state.conn.execute(
            "SELECT key FROM world_entity WHERE type = 'Agent'"
        ).fetchall()
        counts: Dict[str, int] = {}
        for r in rows:
            condition = self.state.get_attr(r["key"], self.attr, self.susceptible)
            counts[condition] = counts.get(condition, 0) + 1
        return {"population": counts}
