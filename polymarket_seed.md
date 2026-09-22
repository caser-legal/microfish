# Polymarket BTC Prediction Market - Live Session
# Generated: 2026-03-16

## Market Overview
**Topic:** Bitcoin Price Prediction & Crypto Trading Sentiment
**Platform:** Polymarket (Decentralized Prediction Market)
**Data Source:** Live orderbook + price history from CLOB API

## Current Market Context
- **Market Type:** Binary prediction markets on crypto events
- **Payout:** $1 USDC winner-takes-all
- **Trading Hours:** 24/7 crypto markets
- **Latency:** ~250ms delay between spot exchanges and Polymarket
- **Fee Structure:** Maker/taker fees apply, highest at 50/50 odds

## Agent Simulation Guidelines
When running simulations with this Polymarket data:

1. **Odds Interpretation:** 50 cents = 50% perceived probability
2. **Price Movements:** Reflect sentiment shifts in real-time
3. **Orderbook Depth:** Shows liquidity and trader conviction
4. **Spread Analysis:** Indicates market maker confidence

## Suggested Agent Types for Trading Simulation

### Institutional Agents
- **Market Makers:** Provide liquidity near fair value, manage inventory risk
- **Arbitrageurs:** Watch for spot vs prediction drift across platforms
- **Whales:** Large position movers, can influence short-term odds

### Retail Agents
- **Momentum Traders:** Follow recent price direction and trends
- **Mean Reversion:** Fade extreme moves (>70 or <30 cents)
- **News Followers:** React to crypto Twitter, regulatory announcements
- **Degens:** High-risk emotional bets on long-shot outcomes

### Information Agents
- **On-Chain Analysts:** Track whale wallets, exchange flows
- **Social Sentiment:** Monitor crypto Twitter, Reddit, Telegram
- **Technical Analysts:** Chart patterns, support/resistance levels

## Simulation Parameters to Consider
- **Volatility:** Crypto markets move fast - agents need quick reaction times
- **Correlation:** BTC movements affect all crypto prediction markets
- **Liquidity Constraints:** Thin markets = larger spreads = harder to exit
- **Information Asymmetry:** Some agents have faster/better data feeds

## Typical Market Scenarios to Simulate
1. **Breaking News Event:** SEC announcement, exchange hack, regulatory crackdown
2. **Technical Breakout:** BTC crosses key psychological level ($100K, etc.)
3. **Whale Movement:** Large wallet transfers trigger speculation
4. **Social Media Hype:** Influencer tweet causes FOMO/FUD cascade
5. **Macro Event:** Fed decision, inflation data affecting risk assets
