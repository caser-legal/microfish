"""
Observation builder.

Assembles what one agent can see at the start of its turn, according to the
pack's observation spec. Nothing here is domain-specific: a trader sees quotes
and positions because the market pack asked for them, not because the engine
knows what a trader is.

Critically, every observation includes the agent's own last failed action and
the reason it failed. That feedback loop is what lets agents adapt to binding
constraints instead of repeating impossible actions forever.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .effects import resolve
from .state import WorldState


class ObservationBuilder:
    def __init__(self, state: WorldState, pack, kernels: Optional[Dict[str, Any]] = None):
        self.state = state
        self.pack = pack
        self.kernels = kernels or {}
        self.spec = pack.observation or {}

    def build(self, actor: str, round_num: int, track: str = "main") -> Dict[str, Any]:
        ctx = {"actor": actor, "round": round_num, "track": track}
        observation: Dict[str, Any] = {
            "round": round_num,
            "you": self._self_view(actor),
        }

        for name, block in (self.spec.get("blocks") or {}).items():
            try:
                observation[name] = self._build_block(block, ctx)
            except Exception as exc:  # a bad block must not kill the turn
                observation[name] = {"error": str(exc)}

        last_failure = self.state.last_failure_for(actor)
        if last_failure:
            observation["last_action_failed"] = {
                "action": last_failure["verb"],
                "reason": last_failure["failure_reason"],
                "round": last_failure["round"],
            }

        recent = self.state.recent_events(limit=int(self.spec.get("recent_events", 6)))
        observation["recent_world_events"] = [
            {
                "actor": e["actor"],
                "action": e["verb"],
                "success": e["success"],
                "round": e["round"],
            }
            for e in recent
            if e["actor"] != actor
        ]

        return observation

    # ------------------------------------------------------------------

    def _self_view(self, actor: str) -> Dict[str, Any]:
        entity = self.state.get_entity(actor) or {}
        view: Dict[str, Any] = {"id": actor}

        holdings = self.state.holdings(actor)
        if holdings:
            view["holdings"] = {k: round(v, 4) for k, v in holdings.items()}

        for attr in (self.spec.get("self_attrs") or []):
            if attr in entity:
                view[attr] = entity[attr]

        for field in ("realized_pnl", "unrealized_pnl"):
            if field in entity:
                view[field] = round(float(entity[field]), 4)

        return view

    def _build_block(self, block: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
        source = block.get("source")

        if source == "kernel":
            kernel = self.kernels.get(block.get("kernel"))
            if kernel is None:
                return {"error": f"kernel '{block.get('kernel')}' not available"}
            method = getattr(kernel, block.get("method", ""), None)
            if method is None or not callable(method):
                return {"error": f"kernel method '{block.get('method')}' not found"}
            params = {
                k: resolve(v, ctx, self.state)
                for k, v in (block.get("params") or {}).items()
            }
            result = method(ctx=ctx, **params)
            return result

        if source == "entities":
            type_ = block.get("type", "Thing")
            limit = int(block.get("limit", 10))
            fields = block.get("fields")
            items = self.state.entities_of_type(type_, limit=limit)
            if fields:
                items = [{k: item.get(k) for k in (["key"] + list(fields))} for item in items]
            return items

        if source == "links":
            rel = block.get("rel", "")
            direction = block.get("direction", "from")
            target = str(resolve(block.get("of", "$actor"), ctx, self.state))
            links = (
                self.state.links_from(target, rel)
                if direction == "from"
                else self.state.links_to(target, rel)
            )
            key = "dst" if direction == "from" else "src"
            return [l[key] for l in links][: int(block.get("limit", 20))]

        if source == "resource_leaderboard":
            resource = block.get("resource", "")
            holders = self.state.all_holders(resource)
            ranked = sorted(holders.items(), key=lambda kv: kv[1], reverse=True)
            limit = int(block.get("limit", 5))
            return [{"holder": h, "amount": round(a, 4)} for h, a in ranked[:limit]]

        if source == "attr":
            key = str(resolve(block.get("entity", ""), ctx, self.state))
            entity = self.state.get_entity(key)
            if entity is None:
                return None
            fields = block.get("fields")
            if fields:
                return {k: entity.get(k) for k in fields}
            return entity

        return {"error": f"unknown observation source '{source}'"}

    # ------------------------------------------------------------------

    @staticmethod
    def render(observation: Dict[str, Any]) -> str:
        """Render an observation as readable text for the agent prompt."""
        lines: List[str] = [f"Round {observation.get('round', 0)}"]

        you = observation.get("you") or {}
        if len(you) > 1:
            lines.append("")
            lines.append("YOUR CURRENT STATE:")
            for k, v in you.items():
                if k == "id":
                    continue
                lines.append(f"  {k}: {_fmt(v)}")

        failure = observation.get("last_action_failed")
        if failure:
            lines.append("")
            lines.append(
                f"YOUR LAST ACTION FAILED: {failure['action']} was rejected because "
                f"{failure['reason']}. Do not repeat it unchanged."
            )

        for name, value in observation.items():
            if name in ("round", "you", "last_action_failed", "recent_world_events"):
                continue
            rendered = _fmt(value)
            if rendered and rendered not in ("[]", "{}", "None"):
                lines.append("")
                lines.append(f"{name.replace('_', ' ').upper()}:")
                lines.append(f"  {rendered}")

        events = observation.get("recent_world_events") or []
        if events:
            lines.append("")
            lines.append("WHAT OTHERS JUST DID:")
            for e in events[:6]:
                status = "" if e["success"] else " (failed)"
                lines.append(f"  {e['actor']}: {e['action']}{status}")

        return "\n".join(lines)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, dict):
        return ", ".join(f"{k}={_fmt(v)}" for k, v in value.items() if v is not None)
    if isinstance(value, list):
        if not value:
            return "[]"
        rendered = []
        for item in value[:8]:
            if isinstance(item, dict):
                inner = ", ".join(
                    f"{k}={_fmt(v)}" for k, v in item.items()
                    if k in ("key", "author", "content", "holder", "amount",
                             "likes", "engagement", "price", "size", "best_bid",
                             "best_ask", "last")
                )
                rendered.append(f"({inner})" if inner else str(item))
            else:
                rendered.append(str(item))
        return "; ".join(rendered)
    return str(value)
