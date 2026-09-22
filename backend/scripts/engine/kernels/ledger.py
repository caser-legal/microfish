"""
Ledger kernel.

Position and profit-and-loss accounting. This is what makes "which archetype
was most profitable" a computed answer rather than an LLM assertion.

Tracks per-holder:
  <resource>              current quantity
  <resource>_cost_basis   average cost of the open position
  realized_pnl            profit locked in by closing trades
  unrealized_pnl          mark-to-market on the open position
"""

from __future__ import annotations

from typing import Any, Dict

from ..state import StateError


class LedgerKernel:
    def __init__(self, state, config: Dict[str, Any] | None = None):
        self.state = state
        self.config = config or {}
        self.cash_resource = self.config.get("cash_resource", "cash")

    def trade(
        self,
        ctx: Dict[str, Any],
        holder: str = None,
        resource: str = "position",
        quantity: float = 0.0,
        price: float = 0.0,
        **_ignored,
    ) -> Dict[str, Any]:
        """
        Record a trade and update realized P&L using average-cost accounting.

        quantity > 0 buys (pays cash), quantity < 0 sells (receives cash).
        Realized P&L is booked only on the portion of the trade that reduces
        an existing opposite position.
        """
        holder = str(holder or ctx.get("actor"))
        quantity = float(quantity)
        price = float(price)
        if quantity == 0:
            raise StateError("trade quantity must be non-zero")
        if price < 0:
            raise StateError("trade price must be non-negative")

        cash_delta = -quantity * price
        # Reject the trade up front if the buyer cannot pay for it.
        if cash_delta < 0:
            available = self.state.balance(holder, self.cash_resource)
            if available + cash_delta < 0:
                raise StateError(
                    f"insufficient {self.cash_resource}: {holder} holds {available:.2f}, "
                    f"trade costs {abs(cash_delta):.2f}"
                )

        prev_qty = self.state.balance(holder, resource)
        prev_basis = float(self.state.get_attr(holder, f"{resource}_cost_basis", 0.0) or 0.0)
        realized = 0.0

        closing = (prev_qty > 0 > quantity) or (prev_qty < 0 < quantity)
        if closing:
            closed = min(abs(quantity), abs(prev_qty))
            direction = 1.0 if prev_qty > 0 else -1.0
            realized = closed * (price - prev_basis) * direction

        new_qty = prev_qty + quantity
        if prev_qty == 0 or (prev_qty > 0) != (new_qty > 0) and new_qty != 0:
            # Opened a fresh position, or flipped through zero to the other side.
            new_basis = price
        elif abs(new_qty) > abs(prev_qty):
            # Added to the position: blend the average cost.
            total = abs(prev_qty) * prev_basis + abs(quantity) * price
            new_basis = total / abs(new_qty) if new_qty else price
        else:
            # Reduced the position: basis is unchanged.
            new_basis = prev_basis
        if new_qty == 0:
            new_basis = 0.0

        self.state.add_resource(holder, self.cash_resource, cash_delta)
        self.state.add_resource(holder, resource, quantity)
        self.state.set_attr(holder, f"{resource}_cost_basis", new_basis)

        if realized:
            total_realized = float(self.state.get_attr(holder, "realized_pnl", 0.0) or 0.0)
            self.state.set_attr(holder, "realized_pnl", total_realized + realized)

        return {
            "filled_quantity": quantity,
            "fill_price": price,
            "cash_delta": cash_delta,
            "realized_pnl": realized,
            "position": new_qty,
        }

    def mark_to_market(
        self, ctx: Dict[str, Any], resource: str = "position", price: float = 0.0, **_ignored
    ) -> Dict[str, Any]:
        """Revalue every open position at the given price."""
        price = float(price)
        holders = self.state.all_holders(resource)
        marked = 0
        for holder, qty in holders.items():
            if qty == 0:
                continue
            basis = float(self.state.get_attr(holder, f"{resource}_cost_basis", 0.0) or 0.0)
            self.state.set_attr(holder, "unrealized_pnl", (price - basis) * qty)
            marked += 1
        return {"marked_holders": marked, "mark_price": price}

    def settle(
        self,
        ctx: Dict[str, Any],
        resource: str = "position",
        price: float = 0.0,
        **_ignored,
    ) -> Dict[str, Any]:
        """
        Resolve the market at a final price: close all positions into cash and
        fold unrealized P&L into realized. This is what produces final,
        comparable P&L across agents.
        """
        price = float(price)
        holders = self.state.all_holders(resource)
        settled = {}
        for holder, qty in holders.items():
            if qty == 0:
                continue
            basis = float(self.state.get_attr(holder, f"{resource}_cost_basis", 0.0) or 0.0)
            pnl = (price - basis) * qty
            self.state.add_resource(holder, self.cash_resource, qty * price)
            self.state.add_resource(holder, resource, -qty)
            total_realized = float(self.state.get_attr(holder, "realized_pnl", 0.0) or 0.0)
            self.state.set_attr(holder, "realized_pnl", total_realized + pnl)
            self.state.set_attr(holder, "unrealized_pnl", 0.0)
            self.state.set_attr(holder, f"{resource}_cost_basis", 0.0)
            settled[holder] = pnl
        return {"settled_holders": len(settled), "settlement_price": price}
