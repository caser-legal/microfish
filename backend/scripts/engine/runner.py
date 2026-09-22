"""
Simulation runner.

One generic round loop for every domain. Replaces run_twitter_simulation.py,
run_reddit_simulation.py and run_parallel_simulation.py, all three of which
carried a SyntaxError and had never executed.

Per round:
  1. pick the agents who act this round (schedule),
  2. build each one's observation from world state,
  3. ask each agent for an action concurrently,
  4. apply the chosen actions one at a time, transactionally,
  5. log every attempt - including rejections and why they were rejected,
  6. fire any scheduled world events (shocks, resolutions).

The actions.jsonl output format is preserved exactly, because the backend's
SimulationRunner already tails it. Action arguments are written whole: the old
pipeline silently dropped any argument outside a 9-key social whitelist.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from .actions import ActionRegistry, ActionValidationError
from .agent import Agent, AgentProfile, ChosenAction
from .effects import EffectError, EffectEvaluator
from .kernels import build_kernels
from .metrics import MetricsEngine
from .observation import ObservationBuilder
from .pack import DomainPack
from .state import StateError, WorldState


class TrackRunner:
    """Runs one track (a parallel world) of a simulation."""

    def __init__(
        self,
        pack: DomainPack,
        track: str,
        agents: List[Agent],
        state: WorldState,
        log_dir: str,
        logger=None,
        seed: int = 20260101,
    ):
        self.pack = pack
        self.track = track
        self.agents = agents
        self.state = state
        self.logger = logger
        self.rng = random.Random(seed)

        self.kernels = build_kernels(pack.kernels.keys(), state, pack.kernels)
        self.registry = ActionRegistry.from_pack(pack)
        self.evaluator = EffectEvaluator(state, self.kernels)
        self.observer = ObservationBuilder(state, pack, self.kernels)
        self.metrics = MetricsEngine(state, pack)

        self.log_dir = os.path.join(log_dir, track)
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "actions.jsonl")

        self.total_actions = 0
        self.total_failures = 0

    # ------------------------------------------------------------------

    def _write(self, entry: Dict[str, Any]) -> None:
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def log_simulation_start(self, total_rounds: int) -> None:
        self._write({
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_start",
            "platform": self.track,
            "track": self.track,
            "domain": self.pack.domain,
            "total_rounds": total_rounds,
            "agents_count": len(self.agents),
            "available_actions": self.registry.verbs(),
        })

    def log_round_start(self, round_num: int, hour: int) -> None:
        self._write({
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "event_type": "round_start",
            "simulated_hour": hour,
            "track": self.track,
        })

    def log_round_end(self, round_num: int, count: int, hour: int) -> None:
        self._write({
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "event_type": "round_end",
            "actions_count": count,
            "simulated_hours": hour,
            "track": self.track,
        })

    def log_simulation_end(self, total_rounds: int) -> None:
        self._write({
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_end",
            "platform": self.track,
            "track": self.track,
            "total_rounds": total_rounds,
            "total_actions": self.total_actions,
            "total_failures": self.total_failures,
            "metrics": self.metrics.compute_all(),
        })

    # ------------------------------------------------------------------

    def active_agents(self, hour: int, min_agents: int, max_agents: int) -> List[Agent]:
        chosen = [a for a in self.agents if a.is_active_at(hour, self.rng)]
        if len(chosen) < min_agents:
            remaining = [a for a in self.agents if a not in chosen]
            self.rng.shuffle(remaining)
            chosen.extend(remaining[: max(0, min_agents - len(chosen))])
        if max_agents and len(chosen) > max_agents:
            self.rng.shuffle(chosen)
            chosen = chosen[:max_agents]
        return chosen

    async def run_round(self, round_num: int, hour: int, min_agents: int, max_agents: int) -> int:
        self.state.current_round = round_num
        self.log_round_start(round_num, hour)

        acting = self.active_agents(hour, min_agents, max_agents)
        if not acting:
            self.log_round_end(round_num, 0, hour)
            return 0

        # Observations are built before any action lands, so every agent in a
        # round reacts to the same world.
        observations = {
            agent.agent_id: self.observer.render(
                self.observer.build(agent.key, round_num, self.track)
            )
            for agent in acting
        }

        decisions = await asyncio.gather(
            *[agent.decide(observations[agent.agent_id]) for agent in acting],
            return_exceptions=True,
        )

        executed = 0
        for agent, decision in zip(acting, decisions):
            if isinstance(decision, Exception):
                decision = ChosenAction(verb="", parse_error=str(decision))
            self._apply(agent, decision, round_num)
            executed += 1

        self._run_scheduled_events(round_num)
        self.log_round_end(round_num, executed, hour)
        return executed

    # ------------------------------------------------------------------

    def _apply(self, agent: Agent, chosen: ChosenAction, round_num: int) -> None:
        """Validate and execute one action, transactionally, and log the result."""
        timestamp = datetime.now().isoformat()

        if not chosen.verb:
            self._record_failure(
                agent, chosen.verb or "UNPARSED", {}, round_num,
                chosen.parse_error or "no action chosen", timestamp,
            )
            return

        try:
            spec, args = self.registry.validate(chosen.verb, chosen.args)
        except ActionValidationError as exc:
            self._record_failure(agent, chosen.verb, chosen.args, round_num, str(exc), timestamp)
            return

        ctx: Dict[str, Any] = {
            "actor": agent.key,
            "actor_name": agent.name,
            "actor_id": agent.agent_id,
            "args": args,
            "round": round_num,
            "track": self.track,
        }

        self.state.begin()
        try:
            outcome = self.evaluator.apply_all(spec.effects, ctx)
            self.state.commit()
        except (EffectError, StateError) as exc:
            self.state.rollback()
            self._record_failure(agent, chosen.verb, args, round_num, str(exc), timestamp)
            return
        except Exception as exc:
            self.state.rollback()
            self._record_failure(
                agent, chosen.verb, args, round_num, f"unexpected error: {exc}", timestamp
            )
            return

        self.state.record_event(
            round_num, agent.key, chosen.verb, args, outcome,
            success=True, track=self.track, timestamp=timestamp,
        )
        agent.remember({"round": round_num, "verb": chosen.verb, "success": True})

        self.total_actions += 1
        self._write({
            "round": round_num,
            "timestamp": timestamp,
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "action_type": chosen.verb,
            "action_args": args,
            "result": self._verbalize(agent, chosen.verb, args, outcome),
            "outcome": outcome,
            "success": True,
            "track": self.track,
            "platform": self.track,
            "reasoning": chosen.reasoning,
        })

    def _record_failure(
        self,
        agent: Agent,
        verb: str,
        args: Dict[str, Any],
        round_num: int,
        reason: str,
        timestamp: str,
    ) -> None:
        self.state.record_event(
            round_num, agent.key, verb, args, {}, success=False,
            failure_reason=reason, track=self.track, timestamp=timestamp,
        )
        agent.remember({"round": round_num, "verb": verb, "success": False, "reason": reason})

        self.total_actions += 1
        self.total_failures += 1
        self._write({
            "round": round_num,
            "timestamp": timestamp,
            "agent_id": agent.agent_id,
            "agent_name": agent.name,
            "action_type": verb,
            "action_args": args,
            "result": f"rejected: {reason}",
            "success": False,
            "failure_reason": reason,
            "track": self.track,
            "platform": self.track,
        })
        if self.logger:
            self.logger(f"  [{self.track}] {agent.name}: {verb} rejected - {reason}")

    def _verbalize(
        self, agent: Agent, verb: str, args: Dict[str, Any], outcome: Dict[str, Any]
    ) -> str:
        """
        Render an action as a sentence. Packs supply templates so simulation
        activity can be fed to the knowledge graph in any domain.
        """
        template = self.pack.verbalizers.get(verb)
        if template:
            fields = {"actor": agent.name, **args, **outcome}
            try:
                return template.format(**fields)
            except (KeyError, IndexError, ValueError):
                pass
        if args:
            rendered = ", ".join(f"{k}={v}" for k, v in list(args.items())[:4])
            return f"{agent.name} performed {verb} ({rendered})"
        return f"{agent.name} performed {verb}"

    def _run_scheduled_events(self, round_num: int) -> None:
        """Fire pack-declared world events due this round (shocks, resolutions)."""
        for event in self.pack.events:
            if int(event.get("at_round", -1)) != round_num:
                continue
            ctx = {"actor": "world", "args": {}, "round": round_num, "track": self.track}
            self.state.begin()
            try:
                outcome = self.evaluator.apply_all(event.get("effects", []), ctx)
                self.state.commit()
            except Exception as exc:
                self.state.rollback()
                if self.logger:
                    self.logger(f"  [{self.track}] world event failed: {exc}")
                continue

            self.state.record_event(
                round_num, "world", event.get("name", "WORLD_EVENT"), {}, outcome,
                success=True, track=self.track, timestamp=datetime.now().isoformat(),
            )
            self._write({
                "round": round_num,
                "timestamp": datetime.now().isoformat(),
                "agent_id": -1,
                "agent_name": "World",
                "action_type": event.get("name", "WORLD_EVENT"),
                "action_args": {},
                "result": event.get("description", "A world event occurred"),
                "outcome": outcome,
                "success": True,
                "track": self.track,
                "platform": self.track,
            })
            if self.logger:
                self.logger(f"  [{self.track}] WORLD EVENT: {event.get('description', '')}")


async def run_simulation(
    pack: DomainPack,
    agent_profiles: List[AgentProfile],
    llm_client,
    output_dir: str,
    total_rounds: int = 20,
    minutes_per_round: int = 60,
    min_agents_per_round: int = 1,
    max_agents_per_round: int = 0,
    logger=None,
    seed: int = 20260101,
) -> Dict[str, Any]:
    """Run every track of a domain pack to completion."""
    log = logger or (lambda msg: print(msg, flush=True))

    log(f"Domain: {pack.domain} - {pack.description}")
    log(f"Tracks: {', '.join(pack.tracks)}")
    log(f"Agents: {len(agent_profiles)} | Rounds: {total_rounds}")

    results: Dict[str, Any] = {}

    for track in pack.tracks:
        log(f"\n=== Track '{track}' ===")

        db_path = os.path.join(output_dir, f"{track}_world.db")
        state = WorldState(db_path, allow_negative=pack.negative_resources)

        _seed_world(state, pack, agent_profiles)

        registry = ActionRegistry.from_pack(pack)
        agents = [
            Agent(profile, registry, llm_client, pack.description or pack.domain)
            for profile in agent_profiles
        ]

        runner = TrackRunner(pack, track, agents, state, output_dir, log, seed)
        runner.log_simulation_start(total_rounds)

        for round_num in range(1, total_rounds + 1):
            hour = ((round_num - 1) * minutes_per_round // 60) % 24
            count = await runner.run_round(
                round_num, hour, min_agents_per_round, max_agents_per_round
            )
            log(
                f"  round {round_num}/{total_rounds} (hour {hour:02d}): "
                f"{count} actions, {runner.total_failures} rejected so far"
            )

        runner.log_simulation_end(total_rounds)

        metrics = runner.metrics.compute_all()
        results[track] = {
            "total_actions": runner.total_actions,
            "total_failures": runner.total_failures,
            "metrics": metrics,
            "state": state.summary(),
        }

        log(f"\n  Track '{track}' complete: {runner.total_actions} actions "
            f"({runner.total_failures} rejected)")
        for name, value in metrics.items():
            log(f"    {name}: {json.dumps(value.get('value'), default=str)[:200]}")

        with open(os.path.join(output_dir, f"{track}_metrics.json"), "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False, default=str)

        state.close()

    return results


def _seed_world(state: WorldState, pack: DomainPack, profiles: List[AgentProfile]) -> None:
    """Create the pack's declared entities and register agents with starting resources."""
    for entity in pack.entities:
        state.put_entity(entity["key"], entity["type"], entity.get("attrs", {}) or {})
        # Entities can hold resources too: a shared pool, a treasury, a reserve.
        # Without this a pack could declare a pool and never be able to fund it.
        for resource, amount in (entity.get("resources") or {}).items():
            state.set_resource(entity["key"], resource, float(amount))

    for profile in profiles:
        attrs = {
            "name": profile.name,
            "archetype": profile.archetype or "unspecified",
            "agent_id": profile.agent_id,
            **(pack.agent_attrs or {}),
            **(profile.attrs or {}),
        }
        state.put_entity(profile.key, "Agent", attrs)

        for resource, spec in (pack.resources or {}).items():
            initial = spec.get("initial", 0) if isinstance(spec, dict) else 0
            if initial:
                state.set_resource(profile.key, resource, float(initial))

    state.conn.commit()
