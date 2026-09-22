"""Convert the existing graph/profile output into engine AgentProfile records."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List


def profile_to_engine_dict(profile: Any, index: int = 0) -> Dict[str, Any]:
    """Return the JSON shape consumed by scripts/run_simulation.py."""
    data = profile.to_dict() if hasattr(profile, "to_dict") else dict(profile)
    return {
        "agent_id": int(data.get("user_id", data.get("agent_id", index))),
        "name": data.get("name") or data.get("user_name") or f"Agent {index}",
        "bio": data.get("bio", ""),
        "persona": data.get("persona", ""),
        "archetype": data.get("source_entity_type") or data.get("entity_type") or "participant",
        "attrs": {
            key: data[key]
            for key in ("age", "gender", "mbti", "country", "profession", "interested_topics")
            if data.get(key) is not None
        },
    }


def save_engine_profiles(profiles: Iterable[Any], file_path: str) -> List[Dict[str, Any]]:
    records = [profile_to_engine_dict(profile, i) for i, profile in enumerate(profiles)]
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return records


def load_engine_profiles(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("profiles") or data.get("agents") or []
    return data


def profile_paths(sim_dir: str) -> Dict[str, str]:
    """Stable paths used by the generic runner and old profile endpoints."""
    return {
        "generic": os.path.join(sim_dir, "agent_profiles.json"),
        "reddit_compat": os.path.join(sim_dir, "reddit_profiles.json"),
        "twitter_compat": os.path.join(sim_dir, "twitter_profiles.csv"),
    }


def write_profile_artifacts(profiles: Iterable[Any], sim_dir: str, legacy_generator=None) -> str:
    """
    Write the engine profile file and, when the legacy generator is supplied,
    the old compatibility files that existing UI endpoints expect.
    """
    profiles = list(profiles)
    paths = profile_paths(sim_dir)
    save_engine_profiles(profiles, paths["generic"])

    if legacy_generator is not None:
        legacy_generator.save_profiles(profiles, paths["reddit_compat"], platform="reddit")
        legacy_generator.save_profiles(profiles, paths["twitter_compat"], platform="twitter")

    return paths["generic"]


__all__ = [
    "profile_to_engine_dict",
    "save_engine_profiles",
    "load_engine_profiles",
    "profile_paths",
    "write_profile_artifacts",
]