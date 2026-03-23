# Veritas

**The world's first AI-powered arbitration protocol — because justice shouldn't require a fortune or a lifetime.**

---

## The Problem

Dispute resolution is broken. A simple contract disagreement costs **$91,000+ in legal fees** and takes **12–18 months** to resolve. Cross-border disputes are worse. Small businesses and individuals are priced out of justice entirely.

Arbitration was supposed to fix this. It didn't. It just became litigation with fewer rules and the same bills.

## The Solution

**Veritas** replaces human arbitrators with AI-consensus validators running on [GenLayer](https://genlayer.com/) — a blockchain purpose-built for intelligent contracts that can *reason*.

Instead of paying three arbitrators $500/hour to read briefs for six months, Veritas submits disputes to a decentralized network of AI validators that:

- **Read and analyze** evidence, contracts, and applicable law
- **Deliberate** through GenLayer's consensus mechanism — multiple AI validators independently reason, then converge on a verdict
- **Execute** binding outcomes on-chain, automatically

The result: disputes resolved in **minutes**, not months. For **dollars**, not tens of thousands.

---

## How It Works

### 1. File
A party submits a dispute — the contract, the evidence, the claim. Everything is recorded immutably on-chain.

### 2. Deliberate
GenLayer's intelligent contract triggers AI-powered arbitration. Multiple validators independently analyze the case using LLM reasoning, then reach consensus through GenLayer's optimistic rollup mechanism. No single point of failure. No bias.

### 3. Resolve
A binding verdict is issued on-chain. Smart contract escrow releases funds accordingly. Done.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Blockchain** | GenLayer Testnet (Bradbury) — AI-consensus L1 |
| **Intelligent Contracts** | Python (GenLayer's native contract language) |
| **Backend** | Python, FastAPI, SQLite (SQLAlchemy) |
| **Frontend** | HTML, CSS, JavaScript |
| **AI Consensus** | GenLayer's built-in LLM validator network |
| **Evidence Storage** | On-chain hashes + local file storage (SHA-256 content-addressed) |

### Why GenLayer?

GenLayer is the only blockchain where smart contracts can **think**. Traditional blockchains execute deterministic code. GenLayer contracts call LLMs, access the web, and reach consensus on *subjective* outputs — exactly what arbitration requires.

---

## Project Structure

```
11-Veritas/
├── src/
│   ├── contracts/       # Python intelligent contracts (GenLayer)
│   ├── backend/         # FastAPI server with SQLite persistence
│   └── frontend/        # Static HTML/CSS/JS landing page
├── docs/                # Technical documentation
├── design/              # UI/UX assets
├── pitch/               # Pitch deck and materials
└── marketing/           # Brand assets
```

---

## Team

| Role | Focus |
|---|---|
| **Smart Contract Engineer** | GenLayer intelligent contracts, arbitration logic |
| **Full-Stack Developer** | Next.js frontend, API integration |
| **Product / Design** | UX, landing page, pitch narrative |

---

## Hackathon Submission Checklist

- [x] Project registered on DoraHacks (GenLayer Testnet Bradbury)
- [x] README with vision, architecture, and instructions
- [x] Intelligent contract deployed to GenLayer testnet
- [ ] Frontend connected to GenLayer testnet
- [ ] Demo video (< 3 min)
- [ ] Pitch deck finalized
- [x] Landing page live

---

## Getting Started

```bash
# Backend
cd src/backend
pip install -r requirements.txt
# Set required environment variables (see .env.example):
#   JWT_SECRET=<your-secret-key>
#   ARBITRATION_CONTRACT_ADDRESS=<deployed-contract-address>
#   GENLAYER_RPC_URL=http://localhost:4000/api
python server.py

# Frontend — open the static landing page
open src/frontend/index.html

# Contracts — deploy to GenLayer testnet
cd src/contracts
# Follow GenLayer deployment docs
```

---

## License

MIT

---

<p align="center">
  <strong>Veritas</strong> — Truth needs no advocate. Just consensus.
</p>
