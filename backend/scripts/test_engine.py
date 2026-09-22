#!/usr/bin/env python3
"""
Engine self-test.

Exercises the simulation engine with a scripted stub LLM, so the mechanics can
be verified without spending tokens. Checks the properties that matter:

  1. Actions mutate shared world state.
  2. Actions FAIL when state constraints reject them, with a usable reason.
  3. Profit and loss is computed from actual fills, not asserted.
  4. Metrics aggregate real state.
  5. Every domain pack runs on the same engine.

Run:  python scripts/test_engine.py
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.agent import AgentProfile                      # noqa: E402
from engine.pack import load_builtin                        # noqa: E402
from engine.runner import run_simulation                    # noqa: E402
from engine.state import StateError, WorldState             # noqa: E402
from engine.kernels.ledger import LedgerKernel              # noqa: E402
from engine.kernels.orderbook import OrderBookKernel        # noqa: E402


PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))
    return condition


class ScriptedLLM:
    """Replays a fixed list of responses, cycling if it runs out."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def chat(self, messages, temperature=0.7, max_tokens=None, response_format=None):
        response = self.responses[self.calls % len(self.responses)]
        self.calls += 1
        return response


# ----------------------------------------------------------------------

def test_state_constraints():
    print("\n[1] World state constraints")
    state = WorldState(":memory:", allow_negative=["position"])

    state.set_resource("alice", "cash", 100)
    check("balance reads back", state.balance("alice", "cash") == 100)

    state.add_resource("alice", "cash", -40)
    check("debit applies", state.balance("alice", "cash") == 60)

    try:
        state.add_resource("alice", "cash", -1000)
        check("overdraft is rejected", False, "no error raised")
    except StateError as exc:
        check("overdraft is rejected", True, str(exc)[:60])

    check("balance unchanged after rejection", state.balance("alice", "cash") == 60)

    state.add_resource("alice", "position", -5)
    check("short position allowed when declared", state.balance("alice", "position") == -5)

    state.set_resource("bob", "cash", 50)
    state.transfer("bob", "alice", "cash", 30)
    check("transfer moves both legs",
          state.balance("bob", "cash") == 20 and state.balance("alice", "cash") == 90)

    state.close()


def test_pnl_is_computed():
    print("\n[2] P&L computed from fills")
    state = WorldState(":memory:", allow_negative=["position"])
    ledger = LedgerKernel(state, {"cash_resource": "cash"})
    state.set_resource("trader", "cash", 1000)
    state.put_entity("trader", "Agent", {"name": "Trader"})

    ledger.trade({"actor": "trader"}, holder="trader", resource="position",
                 quantity=100, price=0.40)
    check("buy debits cash", state.balance("trader", "cash") == 960,
          f"cash={state.balance('trader', 'cash')}")
    check("buy credits position", state.balance("trader", "position") == 100)

    out = ledger.trade({"actor": "trader"}, holder="trader", resource="position",
                       quantity=-100, price=0.60)
    realized = state.get_attr("trader", "realized_pnl")
    check("realized P&L computed correctly", abs(realized - 20.0) < 1e-6,
          f"expected 20.0 (100 x (0.60-0.40)), got {realized}")
    check("position closed", state.balance("trader", "position") == 0)
    check("cash reflects the gain", abs(state.balance("trader", "cash") - 1020.0) < 1e-6,
          f"cash={state.balance('trader', 'cash')}")

    state.set_resource("poor", "cash", 5)
    try:
        ledger.trade({"actor": "poor"}, holder="poor", resource="position",
                     quantity=100, price=0.50)
        check("unaffordable trade rejected", False, "no error raised")
    except StateError as exc:
        check("unaffordable trade rejected", True, str(exc)[:70])

    state.close()


def test_orderbook_matching():
    print("\n[3] Order book matching")
    state = WorldState(":memory:", allow_negative=["position"])
    book = OrderBookKernel(state, {"cash_resource": "cash", "position_resource": "position"})
    state.put_entity("MKT", "Market", {"last": 0.5})
    for who in ("maker", "taker"):
        state.set_resource(who, "cash", 1000)
        state.put_entity(who, "Agent", {"name": who})

    res = book.submit({"actor": "maker", "round": 1}, book="MKT", side="sell",
                      size=100, limit=0.60, actor="maker")
    check("unmatched order rests", res["rested"] == 100 and res["filled"] == 0)
    check("best ask visible", book.best_ask("MKT") == 0.60)

    res = book.submit({"actor": "taker", "round": 1}, book="MKT", side="buy",
                      size=60, limit=0.65, actor="taker")
    check("crossing order fills", res["filled"] == 60, f"filled={res['filled']}")
    check("fill takes the resting price", res["avg_fill_price"] == 0.60)
    check("taker holds position", state.balance("taker", "position") == 60)
    check("maker is short", state.balance("maker", "position") == -60)
    check("last price updated", state.get_attr("MKT", "last") == 0.60)

    try:
        book.submit({"actor": "taker", "round": 1}, book="MKT", side="buy",
                    size=100000, limit=0.99, actor="taker")
        check("unaffordable order rejected", False, "no error raised")
    except StateError as exc:
        check("unaffordable order rejected", True, str(exc)[:70])

    state.close()


async def test_domain_run(domain, responses, expect_metric):
    print(f"\n[4] End-to-end run: {domain}")
    pack = load_builtin(domain)
    llm = ScriptedLLM(responses)

    profiles = [
        AgentProfile(agent_id=i, name=f"Agent{i}", archetype=arch,
                     activity_level=1.0, active_hours=list(range(24)))
        for i, arch in enumerate(["alpha", "alpha", "beta", "beta"])
    ]

    tmp = tempfile.mkdtemp(prefix=f"mf_{domain}_")
    try:
        out = await run_simulation(
            pack=pack, agent_profiles=profiles, llm_client=llm,
            output_dir=tmp, total_rounds=4, minutes_per_round=60,
            min_agents_per_round=2, max_agents_per_round=4,
            logger=lambda m: None,
        )
        track = pack.tracks[0]
        track_result = out[track]

        check(f"{domain}: actions executed", track_result["total_actions"] > 0,
              f"{track_result['total_actions']} actions")
        check(f"{domain}: world state mutated", track_result["state"]["events"] > 0,
              f"{track_result['state']['events']} events recorded")

        metrics = track_result["metrics"]
        check(f"{domain}: metric '{expect_metric}' computed",
              expect_metric in metrics and "error" not in metrics[expect_metric],
              json.dumps(metrics.get(expect_metric, {}).get("value"), default=str)[:110])

        log_path = os.path.join(tmp, track, "actions.jsonl")
        check(f"{domain}: action log written", os.path.exists(log_path))

        if os.path.exists(log_path):
            with open(log_path) as f:
                entries = [json.loads(l) for l in f if l.strip()]
            acts = [e for e in entries if "action_type" in e]
            check(f"{domain}: full args preserved in log",
                  all("action_args" in e for e in acts),
                  f"{len(acts)} action entries")
        return track_result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def test_failures_are_recorded():
    print("\n[5] Rejections are recorded with reasons")
    pack = load_builtin("market")
    # Every agent tries to buy far beyond its cash.
    llm = ScriptedLLM([
        '{"action": "PLACE_ORDER", "args": {"side": "buy", "size": 999999, "limit": 0.99}, "reasoning": "overbid"}'
    ])
    profiles = [
        AgentProfile(agent_id=i, name=f"T{i}", archetype="degen",
                     activity_level=1.0, active_hours=list(range(24)))
        for i in range(3)
    ]

    tmp = tempfile.mkdtemp(prefix="mf_fail_")
    try:
        out = await run_simulation(
            pack=pack, agent_profiles=profiles, llm_client=llm, output_dir=tmp,
            total_rounds=2, min_agents_per_round=3, logger=lambda m: None,
        )
        result = out["main"]
        check("impossible actions were rejected", result["total_failures"] > 0,
              f"{result['total_failures']} rejections")

        rejection = result["metrics"].get("rejection_analysis", {}).get("value", {})
        reasons = rejection.get("top_reasons", {})
        check("rejection reasons captured", bool(reasons),
              list(reasons.keys())[0][:70] if reasons else "none")

        with open(os.path.join(tmp, "main", "actions.jsonl")) as f:
            entries = [json.loads(l) for l in f if l.strip()]
        failed = [e for e in entries if e.get("success") is False]
        check("failures written to action log with reason",
              failed and all(e.get("failure_reason") for e in failed),
              f"{len(failed)} failed entries")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def test_pnl_differentiates_archetypes():
    """
    The headline capability: after a price collapse, the archetype that was
    positioned correctly must show a computed profit and the other a loss.
    """
    print("\n[6] P&L differentiates archetypes through a shock")

    class ByArchetype:
        def chat(self, messages, temperature=0.7, max_tokens=None, response_format=None):
            system = messages[0]["content"]
            if "BULL" in system:
                return ('{"action": "PLACE_ORDER", "args": '
                        '{"side": "buy", "size": 100, "limit": 0.95}}')
            return ('{"action": "PLACE_ORDER", "args": '
                    '{"side": "sell", "size": 100, "limit": 0.90}}')

    pack = load_builtin("market")
    profiles = [
        AgentProfile(agent_id=0, name="BULL_one", archetype="bull",
                     activity_level=1.0, active_hours=list(range(24))),
        AgentProfile(agent_id=1, name="BEAR_one", archetype="bear",
                     activity_level=1.0, active_hours=list(range(24))),
    ]

    tmp = tempfile.mkdtemp(prefix="mf_pnl_")
    try:
        out = await run_simulation(
            pack=pack, agent_profiles=profiles, llm_client=ByArchetype(),
            output_dir=tmp, total_rounds=16, min_agents_per_round=2,
            logger=lambda m: None,
        )
        totals = out["main"]["metrics"]["pnl_by_archetype"]["value"]["totals"]
        bull, bear = totals.get("bull", 0.0), totals.get("bear", 0.0)

        check("shorts profit from the collapse", bear > 0, f"bear P&L = {bear}")
        check("longs lose from the collapse", bull < 0, f"bull P&L = {bull}")
        check("P&L is zero-sum between counterparties", abs(bull + bear) < 1e-6,
              f"{bull} + {bear} = {bull + bear}")
        return totals
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def test_bad_llm_output():
    print("\n[6] Malformed model output is handled")
    pack = load_builtin("market")
    llm = ScriptedLLM([
        "I think I will buy some contracts today.",   # prose, no JSON
        '{"action": "NOT_A_VERB", "args": {}}',        # unknown verb
        '{"action": "PLACE_ORDER", "args": {}}',       # missing required args
        '{"action": "HOLD", "args": {}}',              # valid
    ])
    profiles = [
        AgentProfile(agent_id=i, name=f"A{i}", archetype="test",
                     activity_level=1.0, active_hours=list(range(24)))
        for i in range(4)
    ]
    tmp = tempfile.mkdtemp(prefix="mf_bad_")
    try:
        out = await run_simulation(
            pack=pack, agent_profiles=profiles, llm_client=llm, output_dir=tmp,
            total_rounds=2, min_agents_per_round=4, logger=lambda m: None,
        )
        check("simulation survives malformed output", out["main"]["total_actions"] > 0,
              f"{out['main']['total_actions']} attempts, "
              f"{out['main']['total_failures']} rejected")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def main():
    print("=" * 64)
    print("MicroFish engine self-test")
    print("=" * 64)

    test_state_constraints()
    test_pnl_is_computed()
    test_orderbook_matching()

    # Market: agents alternate buying and selling so trades actually cross.
    market_result = await test_domain_run(
        "market",
        [
            '{"action": "PLACE_ORDER", "args": {"side": "sell", "size": 50, "limit": 0.55}, "reasoning": "offer"}',
            '{"action": "PLACE_ORDER", "args": {"side": "buy", "size": 50, "limit": 0.60}, "reasoning": "lift"}',
            '{"action": "POST_ANALYSIS", "args": {"content": "Spread is wide", "stance": "neutral"}, "reasoning": "note"}',
            '{"action": "HOLD", "args": {}, "reasoning": "wait"}',
        ],
        "pnl_by_archetype",
    )

    await test_domain_run(
        "social",
        [
            '{"action": "CREATE_POST", "args": {"content": "This policy is a mistake."}, "reasoning": "state view"}',
            '{"action": "CREATE_POST", "args": {"content": "Actually the data supports it."}, "reasoning": "counter"}',
            '{"action": "LIKE_POST", "args": {"post_id": "post_1"}, "reasoning": "agree"}',
            '{"action": "REPOST", "args": {"post_id": "post_1"}, "reasoning": "amplify"}',
        ],
        "action_mix",
    )

    await test_domain_run(
        "allocation",
        [
            '{"action": "CLAIM_FUNDS", "args": {"amount": 50000, "justification": "Our district is underserved"}, "reasoning": "claim"}',
            '{"action": "MAKE_CASE", "args": {"content": "The allocation formula is outdated"}, "reasoning": "argue"}',
            '{"action": "CONCEDE", "args": {"amount": 10000, "reason": "Goodwill gesture"}, "reasoning": "concede"}',
            '{"action": "WAIT", "args": {}, "reasoning": "observe"}',
        ],
        "budget_by_archetype",
    )

    await test_failures_are_recorded()
    shock_pnl = await test_pnl_differentiates_archetypes()
    await test_bad_llm_output()

    print("\n" + "=" * 64)
    passed = sum(1 for s, _, _ in results if s == PASS)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    print(f"RESULT: {passed} passed, {failed} failed")

    if shock_pnl:
        print("\nComputed P&L by archetype through the price collapse "
              "(from actual fills, not asserted):")
        print(f"  {json.dumps(shock_pnl, indent=2, default=str)}")

    if failed:
        print("\nFailures:")
        for status, name, detail in results:
            if status == FAIL:
                print(f"  - {name}: {detail}")
    print("=" * 64)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
