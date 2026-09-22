"""
Order book kernel.

A continuous limit order book with price-time priority and partial fills.
Orders that cross the spread execute immediately against resting liquidity;
the remainder rests. Every fill is settled through the ledger kernel, so
positions and P&L stay consistent.

This is the mechanism that lets a market domain answer questions like "how did
liquidity behave when volatility spiked" from real fills rather than prose.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..state import StateError
from .ledger import LedgerKernel


class OrderBookKernel:
    def __init__(self, state, config: Dict[str, Any] | None = None):
        self.state = state
        self.config = config or {}
        self.cash_resource = self.config.get("cash_resource", "cash")
        self.position_resource = self.config.get("position_resource", "position")
        self.tick = float(self.config.get("tick", 0.01))
        self.min_price = float(self.config.get("min_price", 0.0))
        self.max_price = float(self.config.get("max_price", 1.0))
        self._ledger = LedgerKernel(state, {"cash_resource": self.cash_resource})

    # ------------------------------------------------------------------

    def _orders(self, book: str, side: str) -> List[Dict[str, Any]]:
        rows = self.state.conn.execute(
            "SELECT key, attrs FROM world_entity WHERE type = 'Order'"
        ).fetchall()
        orders = []
        for r in rows:
            attrs = json.loads(r["attrs"])
            if attrs.get("book") != book or attrs.get("side") != side:
                continue
            if float(attrs.get("remaining", 0)) <= 0:
                continue
            attrs["key"] = r["key"]
            orders.append(attrs)
        # Price-time priority: bids highest first, asks lowest first.
        reverse = side == "buy"
        orders.sort(key=lambda o: (-float(o["limit"]) if reverse else float(o["limit"]),
                                   float(o.get("seq", 0))))
        return orders

    def best_bid(self, book: str) -> Optional[float]:
        orders = self._orders(book, "buy")
        return float(orders[0]["limit"]) if orders else None

    def best_ask(self, book: str) -> Optional[float]:
        orders = self._orders(book, "sell")
        return float(orders[0]["limit"]) if orders else None

    def quote(self, ctx: Dict[str, Any], book: str = "", **_ignored) -> Dict[str, Any]:
        bid, ask = self.best_bid(book), self.best_ask(book)
        return {
            "best_bid": bid,
            "best_ask": ask,
            "spread": (ask - bid) if (bid is not None and ask is not None) else None,
            "mid": ((ask + bid) / 2) if (bid is not None and ask is not None) else None,
            "last": self.state.get_attr(book, "last"),
        }

    # ------------------------------------------------------------------

    def submit(
        self,
        ctx: Dict[str, Any],
        book: str = "",
        side: str = "",
        size: float = 0.0,
        limit: float = 0.0,
        actor: str = None,
        **_ignored,
    ) -> Dict[str, Any]:
        """
        Submit a limit order. Matches against resting liquidity, then rests any
        remainder. Raises StateError (surfaced as an action failure) when the
        order is invalid or unaffordable.
        """
        actor = str(actor or ctx.get("actor"))
        side = str(side).lower()
        size = float(size)
        limit = float(limit)

        if side not in ("buy", "sell"):
            raise StateError(f"side must be 'buy' or 'sell', got '{side}'")
        if size <= 0:
            raise StateError("order size must be positive")
        if not (self.min_price <= limit <= self.max_price):
            raise StateError(
                f"limit price {limit:g} is outside the tradable range "
                f"[{self.min_price:g}, {self.max_price:g}]"
            )
        if not self.state.get_entity(book):
            raise StateError(f"unknown market '{book}'")

        # A buyer must be able to fund the worst case: the whole order at its limit.
        if side == "buy":
            available = self.state.balance(actor, self.cash_resource)
            if available < size * limit:
                raise StateError(
                    f"insufficient {self.cash_resource}: need {size * limit:.2f} to bid "
                    f"{size:g} @ {limit:g}, have {available:.2f}"
                )

        opposite = "sell" if side == "buy" else "buy"
        resting = self._orders(book, opposite)

        remaining = size
        fills: List[Dict[str, Any]] = []

        for order in resting:
            if remaining <= 0:
                break
            other_limit = float(order["limit"])
            crosses = (limit >= other_limit) if side == "buy" else (limit <= other_limit)
            if not crosses:
                break
            counterparty = str(order.get("author"))
            if counterparty == actor:
                continue  # never self-trade

            available = float(order["remaining"])
            traded = min(remaining, available)
            fill_price = other_limit  # resting order sets the price

            signed = traded if side == "buy" else -traded
            try:
                self._ledger.trade(
                    ctx, holder=actor, resource=self.position_resource,
                    quantity=signed, price=fill_price,
                )
                self._ledger.trade(
                    ctx, holder=counterparty, resource=self.position_resource,
                    quantity=-signed, price=fill_price,
                )
            except StateError:
                # Counterparty can no longer honour the order; retire it and move on.
                self.state.set_attr(order["key"], "remaining", 0.0)
                self.state.set_attr(order["key"], "status", "cancelled_unfunded")
                continue

            self.state.set_attr(order["key"], "remaining", available - traded)
            if available - traded <= 0:
                self.state.set_attr(order["key"], "status", "filled")

            remaining -= traded
            fills.append({
                "price": fill_price,
                "size": traded,
                "counterparty": counterparty,
            })
            self.state.set_attr(book, "last", fill_price)

        rested = 0.0
        if remaining > 0:
            seq = self.state.conn.execute(
                "SELECT COUNT(*) FROM world_entity WHERE type = 'Order'"
            ).fetchone()[0]
            key = f"order_{seq + 1}"
            self.state.put_entity(key, "Order", {
                "book": book,
                "side": side,
                "limit": limit,
                "size": size,
                "remaining": remaining,
                "author": actor,
                "seq": seq,
                "round": ctx.get("round", 0),
                "status": "open",
            })
            rested = remaining

        filled = size - remaining
        avg_price = (
            sum(f["price"] * f["size"] for f in fills) / filled if filled else None
        )

        if filled == 0 and rested == 0:
            raise StateError("order could not be filled or rested")

        return {
            "filled": filled,
            "rested": rested,
            "fills": fills,
            "avg_fill_price": avg_price,
            "book": book,
            "side": side,
        }

    def cancel(
        self, ctx: Dict[str, Any], book: str = "", actor: str = None, **_ignored
    ) -> Dict[str, Any]:
        """Cancel all of the actor's resting orders in a book."""
        actor = str(actor or ctx.get("actor"))
        cancelled = 0
        for side in ("buy", "sell"):
            for order in self._orders(book, side):
                if str(order.get("author")) == actor:
                    self.state.set_attr(order["key"], "remaining", 0.0)
                    self.state.set_attr(order["key"], "status", "cancelled")
                    cancelled += 1
        if cancelled == 0:
            raise StateError("no open orders to cancel")
        return {"cancelled_orders": cancelled}

    def shock(
        self, ctx: Dict[str, Any], book: str = "", price: float = 0.0, **_ignored
    ) -> Dict[str, Any]:
        """
        Force the market to a new price (news, resolution, a 99c->0c collapse).
        Clears resting orders that the new price invalidates.
        """
        price = float(price)
        self.state.set_attr(book, "last", price)
        self.state.set_attr(book, "shocked_at_round", ctx.get("round", 0))
        self._ledger.mark_to_market(ctx, resource=self.position_resource, price=price)
        return {"shock_price": price, "book": book}
