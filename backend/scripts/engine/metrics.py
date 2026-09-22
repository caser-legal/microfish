"""
Metrics engine.

Computes quantitative outcomes from world state. This is the piece that makes
"which archetype was most profitable" answerable: the number comes from the
ledger, not from asking an LLM to estimate it.

Metrics are declared in the pack:

    {"name": "pnl_by_archetype", "op": "group_sum",
     "over": "agent.realized_pnl", "by": "agent.archetype"}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .state import WorldState


class MetricsEngine:
    def __init__(self, state: WorldState, pack):
        self.state = state
        self.pack = pack
        self.specs = {m["name"]: m for m in (pack.metrics or [])}

    def available(self) -> List[Dict[str, str]]:
        return [
            {"name": name, "description": spec.get("description", ""), "op": spec["op"]}
            for name, spec in self.specs.items()
        ]

    def compute(self, name: str, round_range: Optional[List[int]] = None) -> Dict[str, Any]:
        spec = self.specs.get(name)
        if spec is None:
            return {
                "error": f"unknown metric '{name}'",
                "available": list(self.specs.keys()),
            }
        op = spec["op"]
        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            return {"error": f"unsupported metric op '{op}'"}
        try:
            value = handler(spec, round_range)
        except Exception as exc:
            return {"error": f"metric '{name}' failed: {exc}"}
        return {
            "metric": name,
            "description": spec.get("description", ""),
            "value": value,
        }

    def compute_all(self) -> Dict[str, Any]:
        return {name: self.compute(name) for name in self.specs}

    # ------------------------------------------------------------------
    # Metric operations
    # ------------------------------------------------------------------

    def _op_group_sum(self, spec, round_range) -> Dict[str, Any]:
        """Sum a per-agent value, grouped by a per-agent attribute."""
        over = _strip(spec["over"])
        by = _strip(spec["by"])
        groups: Dict[str, float] = {}
        counts: Dict[str, int] = {}

        for agent in self._agents():
            group = str(agent.get(by, "ungrouped"))
            value = _num(agent.get(over, 0.0))
            groups[group] = groups.get(group, 0.0) + value
            counts[group] = counts.get(group, 0) + 1

        return {
            "totals": {k: round(v, 4) for k, v in _sorted_desc(groups)},
            "averages": {
                k: round(groups[k] / counts[k], 4) for k, _ in _sorted_desc(groups)
            },
            "members": counts,
        }

    def _op_group_avg(self, spec, round_range) -> Dict[str, Any]:
        result = self._op_group_sum(spec, round_range)
        return {"averages": result["averages"], "members": result["members"]}

    def _op_rank(self, spec, round_range) -> List[Dict[str, Any]]:
        """Rank individual agents by a value."""
        over = _strip(spec["over"])
        limit = int(spec.get("limit", 10))
        label = _strip(spec.get("label", "name"))
        rows = [
            {
                "agent": agent.get(label, agent.get("key")),
                "value": round(_num(agent.get(over, 0.0)), 4),
                "group": agent.get(_strip(spec.get("by", "archetype")), None),
            }
            for agent in self._agents()
        ]
        rows.sort(key=lambda r: r["value"], reverse=True)
        return rows[:limit]

    def _op_count(self, spec, round_range) -> Dict[str, Any]:
        """Count events, optionally filtered by verb / success, grouped by a field."""
        clauses, params = [], []
        if spec.get("verb"):
            clauses.append("verb = ?")
            params.append(spec["verb"])
        if spec.get("success_only"):
            clauses.append("success = 1")
        if spec.get("failures_only"):
            clauses.append("success = 0")
        if round_range:
            clauses.append("round BETWEEN ? AND ?")
            params.extend([round_range[0], round_range[-1]])

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        group_by = spec.get("by")

        if group_by in ("verb", "actor", "track", "round"):
            rows = self.state.conn.execute(
                f"SELECT {group_by} AS g, COUNT(*) AS n FROM world_event {where} "
                f"GROUP BY {group_by} ORDER BY n DESC",
                params,
            ).fetchall()
            return {str(r["g"]): int(r["n"]) for r in rows}

        row = self.state.conn.execute(
            f"SELECT COUNT(*) AS n FROM world_event {where}", params
        ).fetchone()
        return {"count": int(row["n"])}

    def _op_series(self, spec, round_range) -> List[Dict[str, Any]]:
        """A per-round time series of an entity attribute or event count."""
        attr = spec.get("attr")
        entity = spec.get("entity")

        if entity and attr:
            rows = self.state.conn.execute(
                "SELECT round, outcome FROM world_event WHERE success = 1 ORDER BY round"
            ).fetchall()
            series, seen = [], {}
            for r in rows:
                import json as _json
                outcome = _json.loads(r["outcome"])
                if attr in outcome:
                    seen[int(r["round"])] = _num(outcome[attr])
            for round_num in sorted(seen):
                series.append({"round": round_num, "value": round(seen[round_num], 4)})
            return series

        rows = self.state.conn.execute(
            "SELECT round, COUNT(*) AS n FROM world_event GROUP BY round ORDER BY round"
        ).fetchall()
        return [{"round": int(r["round"]), "value": int(r["n"])} for r in rows]

    def _op_failure_rate(self, spec, round_range) -> Dict[str, Any]:
        """How often actions were rejected, overall and by verb."""
        total = self.state.conn.execute("SELECT COUNT(*) AS n FROM world_event").fetchone()["n"]
        failed = self.state.conn.execute(
            "SELECT COUNT(*) AS n FROM world_event WHERE success = 0"
        ).fetchone()["n"]
        by_verb = self.state.conn.execute(
            "SELECT verb, COUNT(*) AS n FROM world_event WHERE success = 0 "
            "GROUP BY verb ORDER BY n DESC"
        ).fetchall()
        reasons = self.state.conn.execute(
            "SELECT failure_reason, COUNT(*) AS n FROM world_event WHERE success = 0 "
            "AND failure_reason IS NOT NULL GROUP BY failure_reason ORDER BY n DESC LIMIT 10"
        ).fetchall()
        return {
            "total_actions": int(total),
            "failed_actions": int(failed),
            "failure_rate": round(failed / total, 4) if total else 0.0,
            "by_verb": {r["verb"]: int(r["n"]) for r in by_verb},
            "top_reasons": {r["failure_reason"]: int(r["n"]) for r in reasons},
        }

    def _op_resource_total(self, spec, round_range) -> Dict[str, Any]:
        """Total and per-group holdings of a resource."""
        resource = spec["resource"]
        holders = self.state.all_holders(resource)
        by = _strip(spec.get("by", "")) if spec.get("by") else None

        result: Dict[str, Any] = {
            "total": round(sum(holders.values()), 4),
            "holders": len(holders),
        }
        if by:
            groups: Dict[str, float] = {}
            for holder, amount in holders.items():
                entity = self.state.get_entity(holder) or {}
                group = str(entity.get(by, "ungrouped"))
                groups[group] = groups.get(group, 0.0) + amount
            result["by_group"] = {k: round(v, 4) for k, v in _sorted_desc(groups)}
        return result

    # ------------------------------------------------------------------

    def _agents(self) -> List[Dict[str, Any]]:
        rows = self.state.conn.execute(
            "SELECT key FROM world_entity WHERE type = 'Agent'"
        ).fetchall()
        agents = []
        for r in rows:
            entity = self.state.get_entity(r["key"]) or {}
            entity.setdefault("key", r["key"])
            for resource, amount in self.state.holdings(r["key"]).items():
                entity.setdefault(resource, amount)
            agents.append(entity)
        return agents


def _strip(path: str) -> str:
    """'agent.realized_pnl' -> 'realized_pnl'"""
    text = str(path)
    return text.split(".", 1)[1] if text.startswith("agent.") else text


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _sorted_desc(mapping: Dict[str, float]):
    return sorted(mapping.items(), key=lambda kv: kv[1], reverse=True)
