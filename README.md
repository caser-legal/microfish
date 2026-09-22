# MicroFish

**AI-Powered Swarm Intelligence Simulation Engine**

Upload any document, simulate complex social dynamics with autonomous AI agents, and identify optimal strategies.

---

## Deploy your own instance

1. Clone this repo on the machine that will run it.
2. `npm run setup:all`
3. `cp .env.example .env` and fill in your LLM and Zep keys.
4. Do not add `secrets/`, Apple `.p8` keys, `.pem` files, or a copied `.zshrc`. Those are not part of the app.
5. `npm run dev` (UI on port 3000, API on port 5001) or `./fish.sh`.

## Quick Start

### 1. Install Dependencies

```bash
cd /path/to/microfish

# Install all dependencies (frontend + backend)
npm run setup:all
```

### 2. Configure Environment

Copy the example env file and put **your** keys in it. `.env` is gitignored. Do not commit API keys, `secrets/`, App Store Connect keys, or shell backups.

```bash
cp .env.example .env
```

```env
LLM_API_KEY=your_llm_api_key_here
LLM_BASE_URL=https://your-llm-host.example/v1
LLM_MODEL_NAME=your-model-name
ZEP_API_KEY=your_zep_key_here
LLM_BOOST_API_KEY=your_boost_api_key_here
LLM_BOOST_BASE_URL=https://your-boost-host.example/v1
LLM_BOOST_MODEL_NAME=your-boost-model-name
```

**Get Zep API Key:**
1. Go to https://app.getzep.com/
2. Sign up for free account
3. Copy your API key to `.env`

### 3. Start MicroFish

```bash
# From a checkout on your machine (fish.sh uses its own directory)
./fish.sh

# Or, without the launcher:
npm run dev
# Frontend: http://localhost:3000
# Backend:  http://localhost:5001
```

---

## How to Use

### Step 1: Upload Reality Seed

1. Open http://localhost:3000
2. Drag & drop a document (PDF, MD, TXT)
3. Or use the provided `polymarket_seed.md`

### Step 2: Enter Simulation Prompt

Paste your simulation requirements. Example for Polymarket:

```
Run less than 40 rounds first to test.

Simulate diverse crypto traders (market makers, arbitrageurs, 
momentum traders, mean reversion, news followers, degens, whales) 
reacting to:
- Live orderbook data from seed file
- Random crypto news events
- BTC price movements  
- Social media sentiment

Track which agent types are most profitable.
```

### Step 3: Build Knowledge Graph

After ontology generation completes:
1. Click "Build Graph"
2. Wait for entity extraction (uses Zep API)
3. Graph will show extracted entities & relationships

### Step 4: Configure Simulation

Set up agent populations:
- **Market Makers**: 5-10 (provide liquidity)
- **Momentum Traders**: 15-25 (follow trends)
- **Mean Reversion**: 10-15 (contrarians)
- **News Followers**: 20-30 (react to events)
- **Degens**: 10-20 (high-risk bets)
- **Whales**: 2-5 (market movers)

### Step 5: Run Simulation

1. Set round count (start with <40 for testing)
2. Click "Start Simulation"
3. Watch real-time agent interactions
4. View final report with insights

### Step 6: Deep Interaction

After simulation:
- Chat with any agent
- Ask Report Agent questions
- Export findings

---

## Commands

| Command | Description |
|---------|-------------|
| `microfish-start` or `ms` | Start backend + frontend, opens browser |
| `microfish-stop` or `mst` | Stop all services |
| `microfish-logs` or `msl` | View live logs |
| `microfish-status` or `mss` | Check running status |
| `npm run dev` | Start both (manual) |
| `npm run backend` | Backend only |
| `npm run frontend` | Frontend only |

---

## Polymarket Integration

Fetch live Polymarket data for trading simulations:

```bash
cd /path/to/microfish
uv run python fetch_polymarket.py
```

This generates `polymarket_seed.md` with:
- Current orderbook data
- Price history
- Market context
- Agent type suggestions

Then upload this file and use the simulation prompt from `polymarket_simulation_prompt.md`.

---

## Troubleshooting

### Graph Build Fails (401 Unauthorized)
- Restart backend after adding Zep key: `pkill -f "python.*run.py"` then `npm run backend`
- Verify Zep key is valid at https://app.getzep.com/

### LLM Connection Errors
- Ensure Claude Code is running on port 20128
- Test: `curl http://localhost:20128/v1/models`
- Update `LLM_BASE_URL` in `.env` if different port

### Port Already in Use
```bash
# Check what's using the port
lsof -ti:3000  # frontend
lsof -ti:5001  # backend

# Kill processes
kill $(lsof -ti:3000)
kill $(lsof -ti:5001)

# Or use: microfish-stop
```

### Ontology Generation Fails
- Check LLM model is available: `curl http://localhost:20128/v1/models`
- Try different model in `.env` (e.g., `coder`, `qwen3-max`)
- Ensure document isn't too large (max 50MB)

---

## Project Structure

```
microfish/
+-- backend/
|   +-- app/
|   |   +-- api/           # Flask routes
|   |   +-- models/        # Data models
|   |   +-- services/      # Business logic
|   |   +-- utils/         # Helpers
|   +-- run.py             # Entry point
+-- frontend/
|   +-- src/
|       +-- api/           # API client
|       +-- components/    # Vue components
|       +-- views/         # Pages
+-- .env                   # Configuration (DO NOT COMMIT)
+-- .env.example           # Template
+-- fetch_polymarket.py    # Polymarket data fetcher
+-- polymarket_seed.md     # Sample seed file
+-- polymarket_simulation_prompt.md  # Sample prompt
+-- start.sh               # Startup script
+-- stop.sh                # Shutdown script
```

---

## Configuration Options

### LLM Models

Works with any OpenAI-compatible API:

```env
# Local (Claude Code / other proxy)
LLM_BASE_URL=http://localhost:20128/v1
LLM_MODEL_NAME=coder

# Or direct provider APIs
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini

LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
```

### Simulation Defaults

```env
OASIS_DEFAULT_MAX_ROUNDS=10
REPORT_AGENT_MAX_TOOL_CALLS=5
REPORT_AGENT_TEMPERATURE=0.5
```

---

## Cost Estimates

- **Ontology Generation**: ~$0.50-2 per document
- **Graph Building**: Free (Zep free tier sufficient)
- **Simulation**: ~$0.10 per round x agent count
- **Report Generation**: ~$1-3

**Typical 40-round simulation**: ~$5-10 total

---

## License

**Proprietary** - All rights reserved.

Private project. No reproduction, distribution, or transmission without written permission.

---

## Support

Internal use only. Contact the development team for access.

Last updated: March 2026
