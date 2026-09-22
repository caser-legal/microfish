# 02 / Simulation Prompt

**Engine:** MicroFish-V1.0

---

## Simulation Objective
Simulate a Polymarket crypto prediction market ecosystem with diverse agent types reacting to live market data, news events, and social sentiment to identify optimal trading strategies and market dynamics.

---

## Agent Configuration

### Population Mix (adjust based on simulation scale)
| Agent Type | Count | Behavior Profile |
|------------|-------|------------------|
| Market Makers | 5-10 | Provide liquidity, manage risk, profit from spread |
| Arbitrageurs | 3-5 | Cross-platform price watchers, quick execution |
| Momentum Traders | 15-25 | Follow trends, use technical indicators |
| Mean Reversion | 10-15 | Contrarian traders at extremes (>70/<30 cents) |
| News Followers | 20-30 | React to Twitter, Reddit, announcements |
| Degens | 10-20 | High-risk emotional bets, long-shot hunters |
| Whales | 2-5 | Large position movers, market influencers |

---

## Simulation Parameters

### Market Conditions
- **Starting Odds:** Based on current Polymarket orderbook (see seed file)
- **Volatility Level:** High (crypto-native behavior)
- **Liquidity Depth:** Variable - simulate thin vs deep markets
- **Information Delay:** 250ms latency for retail, instant for insiders

### Agent Capabilities
- **Perception:** Real-time odds, orderbook depth, social sentiment feed
- **Actions:** BUY_YES, BUY_NO, SELL_YES, SELL_NO, HOLD, RESEARCH
- **Memory:** Short-term (recent trades), Long-term (market patterns)
- **Communication:** Twitter-like posts, private signals (whale networks)

---

## Scenario Injection Points

### Event Type 1: Breaking News
```
Trigger: "SEC announces Bitcoin ETF decision in 48 hours"
Expected Impact: Volatility spike, divergence in agent predictions
Watch For: Information cascade, herding behavior
```

### Event Type 2: Technical Breakout
```
Trigger: "BTC crosses $100,000 psychological level"
Expected Impact: Momentum surge, FOMO entry from retail agents
Watch For: Mean reversion pressure at extremes
```

### Event Type 3: Whale Movement
```
Trigger: "Unknown wallet moves 10,000 BTC to exchange"
Expected Impact: Speculation wave, asymmetric information advantage
Watch For: Insider trading patterns, front-running behavior
```

### Event Type 4: Social Media Hype
```
Trigger: "Elon Musk tweets about crypto prediction markets"
Expected Impact: Influx of degen agents, irrational betting spikes
Watch For: Sentiment contagion across agent types
```

---

## Success Metrics

### Market Efficiency
- How quickly do odds reflect new information?
- Do prices converge to "fair value" after shocks?
- What's the persistent arbitrage opportunity size?

### Agent Performance
- Which strategies are profitable long-term?
- Do market makers survive volatility events?
- Is there alpha in contrarian vs momentum approaches?

### Systemic Risks
- Does herding cause market crashes?
- Can whale manipulation succeed consistently?
- Are there cascading liquidation scenarios?

---

## Output Requirements

### After Simulation Complete
1. **Market Dynamics Report:** Price evolution, volume patterns, liquidity changes
2. **Agent Leaderboard:** Top/bottom performers by strategy type
3. **Event Impact Analysis:** How each scenario affected market behavior
4. **Optimal Strategy Identification:** Best approaches under different conditions
5. **Risk Warnings:** Identified failure modes and fragility points

### Interactive Exploration
- Enable conversation with any agent type post-simulation
- Allow "what-if" scenario testing with modified parameters
- Generate trading playbook based on simulation learnings

---

## Notes for Report Agent
- Focus on identifying **actionable trading insights** not just academic observations
- Compare simulated outcomes against real Polymarket historical data if available
- Highlight any **counterintuitive findings** (e.g., degens outperforming institutions)
- Flag **regulatory concerns** if manipulation patterns emerge consistently

---

**Start Simulation ->**
