"""
Effect evaluator.

Domain packs describe what an action *does* as data, not code:

    {"op": "transfer", "from": "$actor", "to": "market", "resource": "cash",
     "amount": {"mul": ["$args.size", "$args.limit"]}}

This module resolves those references against the current context and applies
them to world state. There is deliberately no `eval` and no code execution:
the only things a pack can do are the primitive ops below plus the registered
kernels. A malicious or malformed pack can produce a bad simulation, but it
cannot execute arbitrary Python.

Every effect list is applied transactionally by the caller. If any effect
raises EffectError, the whole action is rolled back and recorded as a failure.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .state import StateError, WorldState


class EffectError(Exception):
    """Raised when an effect cannot be applied."""


# ----------------------------------------------------------------------
# Reference resolution
# ----------------------------------------------------------------------

def resolve(value: Any, ctx: Dict[str, Any], state: WorldState) -> Any:
    """
    Resolve a value expression.

    Strings beginning with '$' are paths into the context:
        $actor              -> the acting agent's id
        $args.size          -> an argument the agent supplied
        $round              -> current round number
        $entity.BTC.last    -> an attribute of entity "BTC"
        $balance.cash       -> the actor's balance of "cash"

    Dicts with a single arithmetic key are computed:
        {"mul": [a, b]}, {"add": [...]}, {"sub": [a, b]}, {"div": [a, b]},
        {"neg": a}, {"min": [...]}, {"max": [...]}, {"abs": a}

    Everything else is returned as-is.
    """
    if isinstance(value, str) and value.startswith("$"):
        return _resolve_path(value[1:], ctx, state)

    if isinstance(value, dict) and len(value) == 1:
        op, operand = next(iter(value.items()))
        if op in _ARITH:
            if isinstance(operand, list):
                args = [resolve(v, ctx, state) for v in operand]
            else:
                args = [resolve(operand, ctx, state)]
            try:
                return _ARITH[op](args)
            except ZeroDivisionError:
                raise EffectError("division by zero")
            except (TypeError, ValueError) as exc:
                raise EffectError(f"bad arithmetic in {op}: {exc}")

    if isinstance(value, list):
        return [resolve(v, ctx, state) for v in value]

    return value


def _to_num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        raise EffectError(f"expected a number, got {x!r}")


_ARITH: Dict[str, Callable[[List[Any]], Any]] = {
    "add": lambda a: sum(_to_num(x) for x in a),
    "sub": lambda a: _to_num(a[0]) - sum(_to_num(x) for x in a[1:]),
    "mul": lambda a: _mul(a),
    "div": lambda a: _to_num(a[0]) / _to_num(a[1]),
    "neg": lambda a: -_to_num(a[0]),
    "abs": lambda a: abs(_to_num(a[0])),
    "min": lambda a: min(_to_num(x) for x in a),
    "max": lambda a: max(_to_num(x) for x in a),
}


def _mul(values: List[Any]) -> float:
    result = 1.0
    for v in values:
        result *= _to_num(v)
    return result


def _resolve_path(path: str, ctx: Dict[str, Any], state: WorldState) -> Any:
    parts = path.split(".")
    head = parts[0]

    if head == "entity":
        if len(parts) < 3:
            raise EffectError(f"$entity path needs key and attribute: ${path}")
        key = _maybe_ctx(parts[1], ctx)
        return state.get_attr(key, ".".join(parts[2:]))

    if head == "balance":
        if len(parts) == 2:
            return state.balance(str(ctx.get("actor", "")), parts[1])
        if len(parts) == 3:
            return state.balance(_maybe_ctx(parts[1], ctx), parts[2])
        raise EffectError(f"$balance path malformed: ${path}")

    if head == "count_links_to":
        if len(parts) != 3:
            raise EffectError(f"$count_links_to needs target and relation: ${path}")
        return state.count_links_to(_maybe_ctx(parts[1], ctx), parts[2])

    # Plain context lookup, walking nested dicts: $args.size, $actor, $round
    current: Any = ctx
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


def _maybe_ctx(token: str, ctx: Dict[str, Any]) -> str:
    """Allow an embedded reference as a path segment, e.g. $entity.$args.id.attr"""
    if token.startswith("$"):
        token = token[1:]
    if token in ctx:
        return str(ctx[token])
    # Support args.foo inside a segment position
    if "." in token:
        cur: Any = ctx
        for p in token.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return token
        return str(cur)
    return token


# ----------------------------------------------------------------------
# Effect evaluator
# ----------------------------------------------------------------------

class EffectEvaluator:
    """Applies declarative effects to world state."""

    def __init__(self, state: WorldState, kernels: Optional[Dict[str, Any]] = None):
        self.state = state
        self.kernels = kernels or {}

    def apply_all(self, effects: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply a list of effects in order, sharing a mutable context so later
        effects can read what earlier ones produced (via "as").

        Returns the accumulated outcome dict.
        """
        outcome: Dict[str, Any] = {}
        for effect in effects:
            produced = self.apply(effect, ctx)
            if produced:
                outcome.update(produced)
                # Make results visible to subsequent effects.
                ctx.setdefault("result", {}).update(produced)
        return outcome

    def apply(self, effect: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(effect, dict) or "op" not in effect:
            raise EffectError(f"effect must be an object with an 'op': {effect!r}")

        op = effect["op"]

        # Conditional effects: {"op": "...", "when": {"gt": ["$balance.cash", 0]}}
        if "when" in effect and not self._truthy(effect["when"], ctx):
            return {}

        if op.startswith("kernel."):
            return self._apply_kernel(op, effect, ctx)

        handler = getattr(self, f"_op_{op}", None)
        if handler is None:
            raise EffectError(f"unknown effect op: {op}")
        return handler(effect, ctx) or {}

    # -- primitive ops -------------------------------------------------

    def _op_set(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        key = str(self._r(e.get("entity"), ctx))
        attr = str(e.get("attr"))
        value = self._r(e.get("value"), ctx)
        self.state.set_attr(key, attr, value)
        return {}

    def _op_add(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        holder = str(self._r(e.get("holder", "$actor"), ctx))
        resource = str(self._r(e.get("resource"), ctx))
        amount = _to_num(self._r(e.get("amount"), ctx))
        try:
            new_balance = self.state.add_resource(holder, resource, amount)
        except StateError as exc:
            raise EffectError(str(exc))
        return {f"{resource}_balance": new_balance}

    def _op_transfer(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        src = str(self._r(e.get("from", "$actor"), ctx))
        dst = str(self._r(e.get("to"), ctx))
        resource = str(self._r(e.get("resource"), ctx))
        amount = _to_num(self._r(e.get("amount"), ctx))
        try:
            self.state.transfer(src, dst, resource, amount)
        except StateError as exc:
            raise EffectError(str(exc))
        return {}

    def _op_append(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new entity with a generated key. Used for posts, orders, offers."""
        type_ = str(self._r(e.get("type", "Thing"), ctx))
        attrs_spec = e.get("attrs", {}) or {}
        attrs = {k: self._r(v, ctx) for k, v in attrs_spec.items()}
        attrs.setdefault("author", ctx.get("actor"))
        attrs.setdefault("round", ctx.get("round", 0))

        seq = self.state.conn.execute(
            "SELECT COUNT(*) FROM world_entity WHERE type = ?", (type_,)
        ).fetchone()[0]
        key = f"{type_.lower()}_{seq + 1}"

        self.state.put_entity(key, type_, attrs)
        alias = e.get("as", "created_key")
        return {alias: key}

    def _op_link(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        src = str(self._r(e.get("from", "$actor"), ctx))
        dst = str(self._r(e.get("to"), ctx))
        rel = str(self._r(e.get("rel"), ctx))
        if not dst or dst == "None":
            raise EffectError(f"link target is missing for relation '{rel}'")
        if src == dst:
            raise EffectError(f"cannot link '{src}' to itself via '{rel}'")
        self.state.link(src, rel, dst)
        return {}

    def _op_unlink(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        src = str(self._r(e.get("from", "$actor"), ctx))
        dst = str(self._r(e.get("to"), ctx))
        rel = str(self._r(e.get("rel"), ctx))
        self.state.unlink(src, rel, dst)
        return {}

    def _op_require(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Guard: fail the action when a condition does not hold."""
        if not self._truthy(e.get("cond"), ctx):
            raise EffectError(str(e.get("message", "requirement not met")))
        return {}

    def _op_noop(self, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    # -- kernels -------------------------------------------------------

    def _apply_kernel(self, op: str, e: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        _, _, rest = op.partition("kernel.")
        name, _, method = rest.partition(".")
        kernel = self.kernels.get(name)
        if kernel is None:
            raise EffectError(f"unknown kernel: {name}")
        fn = getattr(kernel, method, None)
        if fn is None or not callable(fn) or method.startswith("_"):
            raise EffectError(f"kernel '{name}' has no method '{method}'")

        params = {
            k: self._r(v, ctx)
            for k, v in e.items()
            if k not in ("op", "when", "as")
        }
        try:
            result = fn(ctx=ctx, **params)
        except EffectError:
            raise
        except StateError as exc:
            raise EffectError(str(exc))
        except TypeError as exc:
            raise EffectError(f"kernel {name}.{method} rejected arguments: {exc}")
        return result if isinstance(result, dict) else {}

    # -- helpers -------------------------------------------------------

    def _r(self, value: Any, ctx: Dict[str, Any]) -> Any:
        return resolve(value, ctx, self.state)

    def _truthy(self, cond: Any, ctx: Dict[str, Any]) -> bool:
        if cond is None:
            return True
        if isinstance(cond, dict) and len(cond) == 1:
            op, operand = next(iter(cond.items()))
            if op in _COMPARE:
                args = [self._r(v, ctx) for v in operand]
                try:
                    return _COMPARE[op](args)
                except (TypeError, ValueError):
                    return False
            if op == "not":
                return not self._truthy(operand, ctx)
            if op == "all":
                return all(self._truthy(c, ctx) for c in operand)
            if op == "any":
                return any(self._truthy(c, ctx) for c in operand)
        return bool(self._r(cond, ctx))


_COMPARE: Dict[str, Callable[[List[Any]], bool]] = {
    "gt": lambda a: _to_num(a[0]) > _to_num(a[1]),
    "gte": lambda a: _to_num(a[0]) >= _to_num(a[1]),
    "lt": lambda a: _to_num(a[0]) < _to_num(a[1]),
    "lte": lambda a: _to_num(a[0]) <= _to_num(a[1]),
    "eq": lambda a: a[0] == a[1],
    "neq": lambda a: a[0] != a[1],
    "exists": lambda a: a[0] is not None and a[0] != "",
}
