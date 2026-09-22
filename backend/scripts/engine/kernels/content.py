"""
Content kernel.

Feed ranking and engagement mechanics for information-spreading domains
(social media, newsrooms, rumour propagation). Keeps the social domain
expressible as an ordinary pack rather than a special case in the engine.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List

from ..state import StateError


class ContentKernel:
    def __init__(self, state, config: Dict[str, Any] | None = None):
        self.state = state
        self.config = config or {}
        self.recency_weight = float(self.config.get("recency_weight", 1.0))
        self.popularity_weight = float(self.config.get("popularity_weight", 1.0))
        self.echo_chamber = float(self.config.get("echo_chamber_strength", 0.0))
        self.content_type = self.config.get("content_type", "Post")

    def feed(
        self,
        ctx: Dict[str, Any],
        viewer: str = None,
        limit: int = 10,
        **_ignored,
    ) -> Dict[str, Any]:
        """
        Rank visible content for one viewer.

        Score blends recency, engagement, and (when echo_chamber_strength > 0)
        a boost for authors the viewer already follows.
        """
        viewer = str(viewer or ctx.get("actor"))
        current_round = int(ctx.get("round", 0))
        followed = {l["dst"] for l in self.state.links_from(viewer, "follows")}

        rows = self.state.conn.execute(
            "SELECT key, attrs FROM world_entity WHERE type = ? ORDER BY created_round DESC LIMIT 200",
            (self.content_type,),
        ).fetchall()

        scored: List[Dict[str, Any]] = []
        for r in rows:
            attrs = json.loads(r["attrs"])
            author = str(attrs.get("author", ""))
            if author == viewer:
                continue
            age = max(0, current_round - int(attrs.get("round", 0)))
            likes = self.state.count_links_to(r["key"], "likes")
            reposts = self.state.count_links_to(r["key"], "reposts")

            recency = self.recency_weight / (1.0 + age)
            popularity = self.popularity_weight * math.log1p(likes + 2 * reposts)
            affinity = self.echo_chamber if author in followed else 0.0

            scored.append({
                "key": r["key"],
                "author": author,
                "content": attrs.get("content", ""),
                "round": attrs.get("round", 0),
                "likes": likes,
                "reposts": reposts,
                "score": recency + popularity + affinity,
            })

        scored.sort(key=lambda p: p["score"], reverse=True)
        return {"feed": scored[: int(limit)]}

    def trending(self, ctx: Dict[str, Any], limit: int = 5, **_ignored) -> Dict[str, Any]:
        """Most-engaged content across the whole world."""
        rows = self.state.conn.execute(
            "SELECT key, attrs FROM world_entity WHERE type = ?", (self.content_type,)
        ).fetchall()
        items = []
        for r in rows:
            attrs = json.loads(r["attrs"])
            engagement = (
                self.state.count_links_to(r["key"], "likes")
                + 2 * self.state.count_links_to(r["key"], "reposts")
            )
            items.append({
                "key": r["key"],
                "author": attrs.get("author"),
                "content": attrs.get("content", ""),
                "engagement": engagement,
            })
        items.sort(key=lambda p: p["engagement"], reverse=True)
        return {"trending": items[: int(limit)]}

    def engage(
        self,
        ctx: Dict[str, Any],
        target: str = "",
        relation: str = "likes",
        **_ignored,
    ) -> Dict[str, Any]:
        """
        Register engagement with a piece of content, rejecting the duplicates
        and self-engagement that would otherwise inflate the numbers.
        """
        actor = str(ctx.get("actor"))
        target = str(target)
        entity = self.state.get_entity(target)
        if entity is None:
            raise StateError(f"content '{target}' does not exist")
        if str(entity.get("author")) == actor:
            raise StateError("cannot engage with your own content")

        existing = [l for l in self.state.links_from(actor, relation) if l["dst"] == target]
        if existing:
            raise StateError(f"already registered '{relation}' on {target}")

        self.state.link(actor, relation, target)
        total = self.state.count_links_to(target, relation)
        return {"target": target, "relation": relation, "total": total}
