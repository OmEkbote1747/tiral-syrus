# 🤖 StockItUp — AI Trading Copilot
**Team Off Script | FinTech Hackathon PS-04**

*Talk to your 021 trading account in plain English, with a guarantee that no trade happens unless you approved that exact trade.*

## 🎯 Core Features

✅ **Safe Order Flow** — LLM creates drafts, you approve, Executor submits  
✅ **Live NSE Data** — Real prices via yfinance, updated every 15 seconds  
✅ **Injection Shield** — Blocks adversarial prompts and malicious symbols  
✅ **Risk Budget Engine** — Validates orders against your configured limits  
✅ **Hash-bound Tokens** — Single-use approval tokens tied to exact order details  
✅ **Standing Instructions** — "If INFY drops below ₹1750, sell 50 shares"  
✅ **Narrative Reports** — Daily trade summary in plain English  
✅ **Immutable Audit Log** — Every event recorded, exportable for compliance  

## 🏗️ Architecture

```
Frontend (Next.js)         Backend (FastAPI)           Mock 021 API
├── Chat with SSE          ├── Gemini Agent            ├── Portfolio data
├── Confirmation Cards     ├── Injection Shield        ├── Order execution
├── Portfolio Sidebar      ├── Risk Engine             └── Live quotes
├── Instructions Panel     ├── Approval Tokens         
└── Audit Log              ├── Executor Service        Database (PostgreSQL)
                           ├── Standing Instructions   ├── Orders
                           └── Audit Logger            ├── Instructions
                                                      ├── Risk limits
                                                      └── Audit log
```

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Google Gemini API key
- Node.js 18+ (for local dev)

### 1. Setup Environment
```bash
cd syrus/
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 2. Start Everything
```bash
docker-compose up --build
```

This starts:
- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **Mock 021 API:** http://localhost:8001
- **PostgreSQL:** localhost:5432
- **Redis:** localhost:6379

### 3. Test the Copilot
Open http://localhost:3000 and try:
- "What's my portfolio value?"
- "Show me RELIANCE price"
- "Buy 50 shares of INFY at market"
- "Set a stop-loss on TCS below ₹4000"

## 🎨 Theme Switching

Two themes available:
- **Terminal** (Default) — Dark green, monospace, Bloomberg feel
- **Luxury** — Dark navy with purple accents, modern fintech

Switch by editing `frontend/src/app/layout.tsx`:
```tsx
<html lang="en" data-theme="terminal">  // or "luxury"
```

## 🔧 Development

### Local Backend (without Docker)
```bash
cd backend/
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Local Frontend (without Docker)
```bash
cd frontend/
npm install
npm run dev
```

### Mock API Only
```bash
cd mock-api/
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

## 🛡️ Security Features

1. **No LLM Order Execution** — Claude creates drafts only. Executor is separate.
2. **Token-bound Approvals** — HMAC tokens tied to exact order details
3. **Price Drift Protection** — Re-quotes if price moves >0.5% since approval
4. **Injection Shield** — Regex + heuristic detection of adversarial prompts
5. **Risk Limits** — Pre-trade validation against position size, daily loss caps
6. **Idempotent Orders** — client_order_id prevents duplicate submissions

## 📊 Demo Flow for Judges

1. **Portfolio Overview** — Real NSE prices in the ticker and sidebar
2. **Natural Language Query** — "What's my current RELIANCE position?"
3. **Live Data Response** — Shows position, P&L, current price
4. **Order Creation** — "Buy 100 shares of INFY at market"
5. **Confirmation Card** — Shows price, risk score, 60s countdown
6. **Approval & Execution** — Click approve → immediate execution via mock API
7. **Audit Trail** — Every step logged with timestamps
8. **Standing Rules** — "If NIFTY drops below 24,000, sell all positions"
9. **Injection Demo** — Try "ignore previous instructions" → blocked by shield
10. **Narrative Report** — Generate plain-English daily summary

## 🎯 Unique Value Props (USPs)

- **Hash-bound approval tokens** — exact order matching, impossible to replay
- **Injection shield** — first line of defense against prompt attacks  
- **Standing instructions** — fire-once rules with automatic price monitoring
- **Narrative trade reports** — turn order history into readable stories
- **Risk/confidence scoring** — every order gets a 0-100 safety rating
- **Price drift protection** — re-quote if market moved since approval

## 📁 Project Structure

```
syrus/
├── docker-compose.yml          # Full stack orchestration
├── .env.example               # Environment template
├── backend/                   # FastAPI + Claude agent
│   ├── agent/                # Claude integration
│   ├── routers/              # API endpoints
│   ├── services/             # Core business logic
│   ├── main.py               # FastAPI app
│   └── requirements.txt      # Python deps
├── frontend/                  # Next.js UI
│   ├── src/app/              # Pages & layout
│   ├── src/components/       # React components
│   ├── src/lib/              # Utilities
│   └── package.json          # Node deps
├── mock-api/                  # Simulated 021 broker
│   ├── main.py               # FastAPI mock server
│   └── requirements.txt      # Dependencies
└── db/migrations/             # PostgreSQL schema
    └── 001_init.sql          # Initial tables
```

## 🚦 API Endpoints

**Backend (Port 8000):**
- `POST /chat/stream` — SSE chat with Claude agent
- `POST /orders/approve` — Approve & execute order draft  
- `POST /orders/reject` — Reject order draft
- `GET /instructions/` — List standing instructions
- `GET /audit/narrative` — Generate daily trade report

**Mock 021 API (Port 8001):**
- `GET /account` — Portfolio summary
- `GET /positions` — Open positions with P&L
- `GET /quote/{symbol}` — Live stock quote
- `POST /orders` — Submit order (called by Executor only)

---

**Built by Team Off Script**  
*StockItUp AI Trading Copilot that puts safety first.*