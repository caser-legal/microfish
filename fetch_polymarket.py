import requests
import json
import time
from datetime import datetime

# -- YOUR CREDENTIALS ------------------------------------------
# Set POLY_PRIVATE_KEY, POLY_API_KEY, POLY_API_SECRET, and POLY_PASSPHRASE
# in the environment. Do not commit them.
import os
PRIVATE_KEY   = os.environ["POLY_PRIVATE_KEY"]
API_KEY       = os.environ["POLY_API_KEY"]
API_SECRET    = os.environ["POLY_API_SECRET"]
PASSPHRASE    = os.environ["POLY_PASSPHRASE"]

# -- API ENDPOINTS ----------------------------------------------
CLOB_BASE     = "https://clob.polymarket.com"
GAMMA_BASE    = "https://gamma-api.polymarket.com"

# -- FIND BTC MARKETS ------------------------------------------
def get_btc_markets():
    """Fetch active crypto markets and filter for Bitcoin-related ones."""
    # Try the new polymarket API format
    r = requests.get(f"{GAMMA_BASE}/markets?tag=crypto&active=true&limit=100")
    if r.status_code != 200:
        print(f"Warning: Gamma API returned {r.status_code}, trying alternative...")
        # Fallback to searching all markets
        r = requests.get(f"{GAMMA_BASE}/markets?limit=100")
    
    markets = r.json()
    
    # Look for current BTC price markets (2025-2026)
    btc = []
    for m in markets:
        question = m.get("question", "").lower()
        title = m.get("title", "").lower()
        # Check if it's a current/recent BTC market
        if ("bitcoin" in question or "btc" in question or 
            "bitcoin" in title or "btc" in title):
            # Filter out very old markets (before 2024)
            end_date = m.get("endDate", "")
            if end_date and "2020" not in end_date and "2021" not in end_date:
                btc.append(m)
            elif not end_date:
                btc.append(m)
    
    return btc

# -- PULL PRICE HISTORY ----------------------------------------
def get_price_history(token_id, interval="5m", limit=10):
    """Get historical price data for a token."""
    path = f"/prices-history?token_id={token_id}&interval={interval}&limit={limit}"
    r = requests.get(f"{CLOB_BASE}{path}")
    return r.json().get("history", [])

# -- PULL ORDERBOOK (PUBLIC) -----------------------------------
def get_orderbook(token_id):
    """Get public orderbook data."""
    path = f"/book?token_id={token_id}"
    r = requests.get(f"{CLOB_BASE}{path}")
    return r.json()

# -- GET MARKET DETAILS ----------------------------------------
def get_market_details(market_id):
    """Get detailed market information."""
    r = requests.get(f"{GAMMA_BASE}/markets/{market_id}")
    return r.json()

# -- BUILD MICROFISH SEED FILE ----------------------------------
def build_seed_file(market, token_id, interval="5m", limit=10):
    """Generate a MicroFish seed file with Polymarket data."""
    prices = get_price_history(token_id, interval, limit)
    book   = get_orderbook(token_id)
    
    # Extract orderbook data
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    
    best_bid = bids[0].get("price", "N/A") if bids else "N/A"
    best_ask = asks[0].get("price", "N/A") if asks else "N/A"
    
    # Calculate spread
    try:
        spread = float(best_ask) - float(best_bid) if best_bid != "N/A" and best_ask != "N/A" else 0
    except:
        spread = 0

    seed  = f"# Polymarket BTC Prediction Market - Live Session\n"
    seed += f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    seed += f"# Market: {market.get('question', 'BTC Market')}\n\n"
    
    seed += f"## Current Orderbook Snapshot\n"
    seed += f"**Best Bid:** {best_bid} cents (YES position)\n"
    seed += f"**Best Ask:** {best_ask} cents (YES position)\n"
    seed += f"**Spread:** {spread:.4f} cents\n\n"
    
    seed += f"## Top 5 Order Levels\n"
    seed += "### Bids (Buy YES)\n"
    seed += "| Price | Size |\n"
    seed += "|-------|------|\n"
    for bid in bids[:5]:
        seed += f"| {bid.get('price', '?')} | {bid.get('size', '?')} |\n"
    
    seed += "\n### Asks (Sell YES)\n"
    seed += "| Price | Size |\n"
    seed += "|-------|------|\n"
    for ask in asks[:5]:
        seed += f"| {ask.get('price', '?')} | {ask.get('size', '?')} |\n"
    
    seed += f"\n## Price History (last {limit} candles - {interval})\n"
    seed += "| Time | Price (YES odds) | Volume |\n"
    seed += "|------|------------------|--------|\n"
    
    for candle in prices:
        t = datetime.fromtimestamp(candle.get("t", 0)).strftime("%H:%M:%S")
        p = candle.get("p", "?")
        v = candle.get("v", "?")
        seed += f"| {t} | {p} | {v} |\n"
    
    seed += "\n## Market Context\n"
    seed += "- **Market Type:** Polymarket BTC binary prediction\n"
    seed += "- **Payout:** $1 USDC winner-takes-all\n"
    seed += "- **Fee Structure:** Highest at 50/50 odds, decreases at extremes\n"
    seed += "- **Latency:** ~250ms delay between Binance spot and Polymarket\n"
    seed += "- **Trading Hours:** 24/7 crypto markets\n\n"
    
    seed += "## Agent Simulation Guidelines\n"
    seed += "When running simulations with this data:\n"
    seed += "1. Odds represent probability perception (50 cents = 50% chance)\n"
    seed += "2. Price movements reflect sentiment shifts\n"
    seed += "3. Orderbook depth shows liquidity and conviction\n"
    seed += "4. Spread indicates market maker confidence\n\n"
    
    seed += "## Suggested Agent Types for Trading Simulation\n"
    seed += "- **Momentum Traders:** Follow recent price direction\n"
    seed += "- **Mean Reversion:** Fade extreme moves (>70 or <30 cents)\n"
    seed += "- **Arbitrageurs:** Watch for spot vs prediction drift\n"
    seed += "- **Market Makers:** Provide liquidity near fair value\n"
    seed += "- **Noise Traders:** Random emotional decisions\n"

    filename = "polymarket_seed.md"
    with open(filename, "w") as f:
        f.write(seed)
    
    print(f"\n[OK] Seed file written: {filename}")
    print("\n" + "="*50)
    print(seed)
    print("="*50)
    
    return filename

# -- MAIN EXECUTION --------------------------------------------
if __name__ == "__main__":
    print("="*60)
    print("       Polymarket BTC Data Fetcher for MicroFish")
    print("="*60)
    
    print("\nSearching for active BTC markets...")
    markets = get_btc_markets()
    
    if not markets:
        # Fallback: use any BTC market even if old
        print("\nWarning: No current BTC markets found, checking all time...")
        r = requests.get(f"{GAMMA_BASE}/markets?tag=crypto&limit=200")
        all_markets = r.json()
        markets = [m for m in all_markets if 
                   "bitcoin" in m.get("question","").lower() or 
                   "btc" in m.get("question","").lower()]
    
    if not markets:
        print("\nError: No BTC markets found at all!")
        exit(1)
    
    print("\n=== Found BTC Markets ===")
    for i, m in enumerate(markets[:15]):
        end_date = m.get('endDate', 'N/A')
        print(f"{i+1}. ID: {m['id'][:8]}... | End: {end_date[:10] if len(end_date)>10 else end_date} | {m.get('question', m.get('title', 'No title'))[:60]}")
    
    # Use the first BTC market
    market = markets[0]
    token_ids = market.get("clobTokenIds", [])
    
    if not token_ids:
        print(f"\nError: No token IDs found for market: {market.get('question')}")
        exit(1)
    
    token_id = token_ids[0]
    
    print(f"\nSelected Market:")
    print(f"   Question: {market.get('question')}")
    print(f"   Token ID: {token_id}")
    
    print(f"\nFetching orderbook and price history...")
    
    try:
        build_seed_file(market, token_id, interval="5m", limit=10)
        print("\nReady to use with MicroFish!")
        print("\nNext steps:")
        print("1. Run: npm run dev")
        print("2. Open: http://localhost:3000")
        print("3. Drag in polymarket_seed.md")
        print("4. Paste your simulation prompt")
    except Exception as e:
        print(f"\nError fetching data: {e}")
        exit(1)
