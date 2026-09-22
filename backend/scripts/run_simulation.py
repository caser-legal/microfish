#!/usr/bin/env python3
"""
Simulation entry point.

Spawned as a subprocess by backend/app/services/simulation_runner.py. Reads a
simulation config, loads the domain pack it names, builds agents from the
generated profiles, and runs every track to completion.

Replaces run_twitter_simulation.py, run_reddit_simulation.py and
run_parallel_simulation.py.

Usage:
    python run_simulation.py --config /path/to/simulation_config.json
                             [--max-rounds N]
"""

import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime

# The backend launches this subprocess with cwd set to the simulation output
# directory. Load the project .env explicitly so the domain runner uses the same
# LLM endpoint and key as the API process.
try:
    from dotenv import load_dotenv
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=False)
except ImportError:
    pass

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from engine.agent import AgentProfile           # noqa: E402
from engine.pack import PackValidationError, load_pack, load_builtin  # noqa: E402
from engine.runner import run_simulation        # noqa: E402
from llm_client import get_llm_client           # noqa: E402


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def load_profiles(config: dict, config_dir: str) -> list:
    """
    Build AgentProfile objects from the generated profile file.

    Accepts either an inline "agents" list or a path in "profiles_path",
    falling back to the conventional agent_profiles.json next to the config.
    """
    raw = config.get("agents")

    if raw is None:
        candidates = [
            config.get("profiles_path"),
            os.path.join(config_dir, "agent_profiles.json"),
            os.path.join(config_dir, "profiles.json"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                with open(candidate, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                log(f"Loaded profiles from {candidate}")
                break

    if raw is None:
        raise SystemExit("No agent profiles found (checked 'agents', 'profiles_path', "
                         "agent_profiles.json, profiles.json)")

    if isinstance(raw, dict):
        raw = raw.get("profiles") or raw.get("agents") or []

    activity = {
        int(cfg.get("agent_id", i)): cfg
        for i, cfg in enumerate(config.get("agent_configs", []) or [])
    }

    profiles = []
    for i, item in enumerate(raw):
        agent_id = int(item.get("agent_id", item.get("user_id", i)))
        cfg = activity.get(agent_id, {})

        attrs = dict(item.get("attrs") or {})
        for key in ("country", "profession", "mbti", "age", "gender"):
            if item.get(key) is not None:
                attrs[key] = item[key]

        profiles.append(AgentProfile(
            agent_id=agent_id,
            name=item.get("name") or item.get("user_name") or f"Agent {agent_id}",
            bio=item.get("bio", ""),
            persona=item.get("persona", ""),
            archetype=(
                item.get("archetype")
                or item.get("source_entity_type")
                or item.get("entity_type")
                or "unspecified"
            ),
            active_hours=cfg.get("active_hours") or list(range(8, 23)),
            activity_level=float(cfg.get("activity_level", 0.5)),
            attrs=attrs,
        ))

    return profiles


def resolve_pack(config: dict, config_dir: str):
    """Load the domain pack: inline, by path, or by built-in name."""
    inline = config.get("domain_pack")
    if isinstance(inline, dict):
        log(f"Using inline domain pack '{inline.get('domain')}'")
        return load_pack(inline)

    path = config.get("domain_pack_path")
    if path:
        candidate = path if os.path.isabs(path) else os.path.join(config_dir, path)
        if os.path.exists(candidate):
            log(f"Loading domain pack from {candidate}")
            return load_pack(candidate)

    name = config.get("domain") or "social"
    log(f"Loading built-in domain pack '{name}'")
    return load_builtin(name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a MicroFish simulation")
    parser.add_argument("--config", required=True, help="Path to simulation_config.json")
    parser.add_argument("--max-rounds", type=int, default=None, help="Cap the round count")
    parser.add_argument("--output-dir", default=None, help="Where to write logs and state")
    args = parser.parse_args()

    if not os.path.exists(args.config):
        log(f"ERROR: config not found: {args.config}")
        return 1

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    config_dir = os.path.dirname(os.path.abspath(args.config))
    output_dir = args.output_dir or config.get("output_dir") or config_dir
    os.makedirs(output_dir, exist_ok=True)

    log("=" * 60)
    log("MicroFish simulation starting")
    log("=" * 60)

    try:
        pack = resolve_pack(config, config_dir)
    except PackValidationError as exc:
        log(f"ERROR: invalid domain pack: {exc}")
        return 1

    try:
        profiles = load_profiles(config, config_dir)
    except SystemExit as exc:
        log(f"ERROR: {exc}")
        return 1

    if not profiles:
        log("ERROR: no agent profiles to run")
        return 1

    time_config = config.get("time_config", {}) or {}
    total_rounds = args.max_rounds or int(config.get("max_rounds") or time_config.get("total_rounds") or 20)
    minutes_per_round = int(time_config.get("minutes_per_round", 60))
    min_agents = int(time_config.get("agents_per_hour_min", 1))
    max_agents = int(time_config.get("agents_per_hour_max", 0))

    log(f"Config: {len(profiles)} agents, {total_rounds} rounds, "
        f"{minutes_per_round} min/round")

    try:
        llm_client = get_llm_client()
    except Exception as exc:
        log(f"ERROR: could not initialise the LLM client: {exc}")
        return 1

    try:
        results = asyncio.run(run_simulation(
            pack=pack,
            agent_profiles=profiles,
            llm_client=llm_client,
            output_dir=output_dir,
            total_rounds=total_rounds,
            minutes_per_round=minutes_per_round,
            min_agents_per_round=min_agents,
            max_agents_per_round=max_agents,
            logger=log,
            seed=int(config.get("seed", 20260101)),
        ))
    except KeyboardInterrupt:
        log("Interrupted by user")
        return 130
    except Exception as exc:
        log(f"ERROR: simulation failed: {exc}")
        traceback.print_exc()
        return 1

    with open(os.path.join(output_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    log("=" * 60)
    log("Simulation complete")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
