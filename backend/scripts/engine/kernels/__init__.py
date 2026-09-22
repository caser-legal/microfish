"""
Simulation kernels.

Some mechanics are too intricate to express as declarative effects: matching
an order book, decaying an epidemic curve, ranking a feed. Those live here as
ordinary Python, and domain packs invoke them through effects:

    {"op": "kernel.orderbook.submit", "book": "BTC-100K", "side": "$args.side", ...}

Kernels are pre-written and trusted. A pack can only call kernels that the
engine registers, and only through this narrow interface, so a pack never
executes arbitrary code.
"""

from .ledger import LedgerKernel
from .orderbook import OrderBookKernel
from .content import ContentKernel
from .diffusion import DiffusionKernel

KERNEL_TYPES = {
    "ledger": LedgerKernel,
    "orderbook": OrderBookKernel,
    "content": ContentKernel,
    "diffusion": DiffusionKernel,
}


def build_kernels(names, state, config=None):
    """Instantiate the kernels a pack asked for."""
    config = config or {}
    kernels = {}
    for name in names:
        cls = KERNEL_TYPES.get(name)
        if cls is None:
            raise ValueError(f"unknown kernel '{name}'; available: {sorted(KERNEL_TYPES)}")
        kernels[name] = cls(state, config.get(name, {}))
    return kernels


__all__ = [
    "LedgerKernel",
    "OrderBookKernel",
    "ContentKernel",
    "DiffusionKernel",
    "KERNEL_TYPES",
    "build_kernels",
]
