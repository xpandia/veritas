# Veritas -- GenLayer Bradbury Hackathon Submission

**Hackathon:** GenLayer Testnet Bradbury Hackathon (DoraHacks)
**Deadline:** Late March 2026
**Team:** Xpandia
**Repo:** https://github.com/xpandia/veritas

---

## Submission Text

### One-Liner

Veritas replaces $91,000 human arbitrators with GenLayer's AI-consensus validators -- resolving cross-border disputes in minutes for less than $1.

### The $91,000 Problem

Dispute resolution is broken. A simple contract disagreement today costs **$91,000+ in legal fees** and takes **12-18 months** to resolve. Cross-border disputes are worse -- jurisdictional complexity adds layers of cost and delay. For freelancers, small businesses, and anyone outside the Fortune 500, justice is priced out of reach.

Arbitration was supposed to fix this. It didn't. It became litigation with fewer rules and the same bills.

**Veritas makes that $91,000 less than $1.**

Not by cutting corners on the process -- by replacing the most expensive component (human judgment at $500/hour) with the only technology that can replicate it at scale: AI consensus on GenLayer.

### Why GenLayer is the Only Chain That Can Do This

This is not a project that "uses GenLayer because it's the hackathon sponsor." GenLayer is the **only** blockchain where this is technically possible.

Arbitration requires something no other chain provides: **smart contracts that can reason about subjective evidence and reach consensus on non-deterministic outputs.**

- **Ethereum/Solana/etc.:** Deterministic execution only. A smart contract cannot read a PDF, weigh conflicting testimony, or make a judgment call. You would need an off-chain oracle, which reintroduces centralization.
- **AI + traditional chains:** You could bolt an LLM onto any chain via an oracle, but then a single AI is the arbiter. No consensus. No trustlessness. Just a centralized AI with extra steps.
- **GenLayer:** Smart contracts natively call LLMs. Multiple validators independently analyze evidence and must reach consensus via the equivalence principle. The AI doesn't just execute -- it deliberates. And the network validates that deliberation.

**Veritas could not exist without GenLayer.** The `call_llm_with_principle` function is the entire innovation -- it turns "one AI's opinion" into "a consensus of independent AI analyses."

### What We Built

**Intelligent Contract (GenLayer native -- Python):**
- Full dispute lifecycle: FILED -> EVIDENCE_SUBMISSION -> DELIBERATION -> VERDICT -> APPEAL -> RESOLVED
- AI evidence analysis using `call_llm_with_principle` (GenLayer equivalence principle)
- Multi-round deliberation with rebuttals (up to 3 rounds)
- Consensus-based verdicts requiring validator supermajority on outcome AND escrow split (within 10%)
- Appeal mechanism with escalating fees and fresh deliberation (up to 2 appeals)
- On-chain escrow with automatic distribution per verdict
- ELO-style reputation scoring for all parties

**Backend (FastAPI + SQLite):**
- Complete case management API (CRUD + lifecycle transitions)
- Evidence upload with SHA-256 content-addressed storage
- JWT authentication
- AI analysis proxy to GenLayer contract
- Full demo mode that works standalone (no GenLayer RPC required)
- Demo endpoints for the complete flow: create -> analyze -> verdict -> resolve
- Pre-seeded with compelling demo data including a cross-border dispute story

**Frontend:**
- Landing page presenting the value proposition
- Case tracking UI

### The Demo: Maria vs TechCorp

To make the value proposition tangible, Veritas ships with a pre-loaded story:

**Maria Rodriguez** (freelance web developer, Buenos Aires) was hired by **TechCorp GmbH** (Berlin) to redesign their e-commerce platform for **$2,000**. She delivered everything on time. TechCorp's project manager emailed: *"All deliverables received and approved. Great work, Maria."*

Then they didn't pay. Three Stripe invoices -- declined. No response to follow-ups.

In the traditional system, Maria has no realistic recourse. Filing in German courts from Argentina? $91,000 minimum. International arbitration? Same price range, 12-18 months.

**On Veritas, this dispute was resolved in under 48 hours for less than $1:**

1. Maria files a dispute with 4 pieces of evidence (contract, emails, Stripe records, deliverable screenshots)
2. GenLayer validators independently analyze the evidence via AI
3. Three rounds of deliberation reach 92% validator consensus
4. **Verdict: Maria wins, 85/15 escrow split** -- $1,700 to Maria, $300 returned to TechCorp
5. Reputation updated: Maria +30 (530), TechCorp -20 (480)

The evidence was unambiguous: signed contract + delivery acknowledgment + non-payment records. No human arbitrator needed. No lawyer. No jurisdiction. Just evidence, AI consensus, and on-chain execution.

**Cost comparison for this single dispute:**

| | Traditional | Veritas |
|---|---|---|
| **Cost** | $91,000+ | < $1 |
| **Time** | 12-18 months | < 48 hours |
| **Accessible to Maria?** | No | Yes |
| **Cross-border complexity** | Extreme | None |
| **Transparency** | Closed proceedings | On-chain, auditable |
| **Enforcement** | Requires separate legal action | Automatic (escrow) |

### GenLayer's Revenue Share: Why This is a Real Business

GenLayer's perpetual revenue share model makes Veritas a sustainable protocol, not just a hackathon project:

- **Veritas charges a 2.5% platform fee** on every filing (configurable, stored on-chain as basis points)
- **GenLayer earns its revenue share** from every transaction on the network
- As dispute volume grows, both Veritas and GenLayer earn proportionally
- This creates a direct alignment of incentives: GenLayer's success = Veritas's success

The total addressable market for commercial arbitration is **$15B+ annually**. Even capturing 0.1% at 100x lower cost creates a significant revenue stream -- and every transaction generates value for the GenLayer ecosystem.

### Honest Assessment: Current State

We believe in transparency about what's built and what's next.

**Working today:**
- [x] Intelligent contract with complete arbitration lifecycle (file, evidence, analyze, deliberate, verdict, appeal, resolve)
- [x] AI-consensus analysis using GenLayer's equivalence principle
- [x] Backend API with full CRUD, auth, and SQLite persistence
- [x] Demo mode that runs standalone (no external dependencies)
- [x] Pre-seeded demo with 4 cases including the Maria vs TechCorp story
- [x] Evidence upload with SHA-256 content addressing
- [x] Reputation system (ELO-style, on-chain)
- [x] CORS-enabled API with Swagger docs at `/docs`

**In progress / next steps:**
- [ ] Frontend connected to GenLayer testnet (currently demo-mode)
- [ ] Contract deployed to Bradbury testnet (tested locally, deployment instructions in `DEPLOY_GENLAYER.md`)
- [ ] Demo video (script complete, recording pending)
- [ ] DoraHacks BUIDL page published
- [ ] IPFS/Arweave evidence storage (currently local filesystem)
- [ ] Multi-language support for international disputes

**What we'd build with more time:**
- Real-time case status via WebSocket
- Expert witness system (staked reputation validators)
- Template-based dispute filing for common categories (freelancer disputes, e-commerce, DeFi)
- Integration with legal notification systems for enforceability
- DAO governance for protocol parameter updates

### AI-Consensus Arbitration Flow

1. **File** -- Claimant submits dispute with category, description, and escrow deposit. Contract validates inputs, locks funds, initializes reputation.

2. **Evidence** -- Both parties upload evidence (documents, communications, transactions, testimony, expert reports). Each piece is content-addressed by SHA-256 hash and timestamped on-chain.

3. **AI Analysis** -- GenLayer validators independently query the LLM with structured evidence prompts. The equivalence principle ensures consensus on preliminary assessment and confidence level. This is not one AI deciding -- it is a consensus of independent AI analyses.

4. **Deliberation** -- Parties submit rebuttals, triggering additional analysis rounds. Each round re-analyzes all accumulated evidence. After max rounds, the contract moves to verdict.

5. **Verdict** -- Definitive ruling with outcome, escrow split, confidence, and multi-paragraph reasoning. Validators must agree on outcome category and escrow split within 10%.

6. **Appeal** -- Either party can appeal with escalating fees (base * 2^appeal_count). Appeals reset deliberation. Maximum 2 per dispute.

7. **Resolve** -- Escrow distributed per verdict. Reputation updated. Everything on-chain, auditable, final.

---

## Quick Start

```bash
# Clone
git clone https://github.com/xpandia/veritas.git
cd veritas

# Backend
cd src/backend
pip install -r requirements.txt
python server.py
# API: http://localhost:8000
# Docs: http://localhost:8000/docs

# Demo endpoints (no auth needed):
# GET  /api/demo/cases                     -- list all cases
# GET  /api/demo/cases/case-demo-004       -- Maria vs TechCorp (hero story)
# POST /api/demo/cases                     -- create a new case
# POST /api/demo/cases/{id}/analyze        -- trigger AI analysis
# POST /api/demo/cases/{id}/verdict        -- render verdict
# POST /api/demo/cases/{id}/resolve        -- distribute escrow
# POST /api/demo/cases/{id}/full-flow      -- run entire lifecycle in one call
# GET  /api/demo/reputation/{address}      -- check reputation scores
# GET  /api/demo/analytics                 -- platform stats
# GET  /api/health                         -- system health check

# Frontend
open src/frontend/index.html

# Deploy contract to GenLayer
# See: src/contracts/DEPLOY_GENLAYER.md
```

### Quick Demo: Maria vs TechCorp

```bash
# Start the server
cd src/backend && python server.py

# In another terminal:

# See the hero story
curl -s http://localhost:8000/api/demo/cases/case-demo-004 | python -m json.tool

# See Maria's evidence
curl -s http://localhost:8000/api/demo/cases/case-demo-004/evidence | python -m json.tool

# See the full timeline
curl -s http://localhost:8000/api/demo/cases/case-demo-004/timeline | python -m json.tool

# Check reputations
curl -s http://localhost:8000/api/demo/reputation/0xMaria003aaBBccDDeeFF00112233445566778899 | python -m json.tool
curl -s http://localhost:8000/api/demo/reputation/0xTechCorp5aaBBccDDeeFF00112233445566778899 | python -m json.tool

# Create a NEW case and run the full flow
curl -s -X POST http://localhost:8000/api/demo/cases \
  -H "Content-Type: application/json" \
  -d '{"respondent_address": "0xBadActor", "category": "contract_breach", "title": "Test Dispute", "description": "Testing the full flow", "escrow_amount": 5000, "filing_fee": 100}' | python -m json.tool

# Then run the full lifecycle on it:
curl -s -X POST http://localhost:8000/api/demo/cases/<case-id>/full-flow | python -m json.tool
```

---

## Demo Video Script (3 minutes)

### Scene 1: The Problem (0:00 - 0:30)

**Visual:** Legal fee invoices, calendar pages turning, frustrated freelancer. Stats overlay.

**Narration:** "Maria is a web developer in Buenos Aires. She built an e-commerce site for a Berlin company. They loved it. Then they didn't pay. $2,000 -- not enough to hire a lawyer, too much to just forget. In the traditional system, Maria has no realistic option. International arbitration costs $91,000 and takes over a year. For small-scale cross-border disputes, justice simply doesn't exist."

### Scene 2: How Veritas Works (0:30 - 1:00)

**Visual:** Architecture diagram animating: dispute filed -> evidence submitted -> AI validators deliberate -> verdict rendered -> escrow distributed.

**Narration:** "Veritas replaces human arbitrators with AI-consensus validators on GenLayer. Multiple AI validators independently analyze the evidence, deliberate across rounds, and converge on a verdict. No single AI decides -- the network reaches consensus. Verdicts execute automatically on-chain."

### Scene 3: Live Demo (1:00 - 2:30)

**Visual:** Screen recording of the API.

1. **(1:00 - 1:20)** **Maria files** -- Show the dispute with 4 evidence items. Highlight automatic escrow locking.
2. **(1:20 - 1:40)** **Evidence review** -- Show the contract, delivery email, Stripe records. All SHA-256 hashed.
3. **(1:40 - 2:00)** **AI Analysis** -- Show the structured analysis: strengths (signed contract, delivery ack), weaknesses (informal contract), confidence (92%).
4. **(2:00 - 2:15)** **Verdict** -- Maria wins, 85/15 split, $1,700 awarded. HIGH confidence. Multi-paragraph reasoning.
5. **(2:15 - 2:30)** **Resolution** -- Escrow distributed. Reputation updated. Cost: <$1. Time: <48 hours.

### Scene 4: Why GenLayer (2:30 - 2:50)

**Visual:** Comparison table.

| | Traditional | Veritas |
|---|---|---|
| **Cost** | $91,000+ | < $1 |
| **Time** | 12-18 months | Minutes |
| **Transparency** | Closed hearings | On-chain, auditable |
| **Cross-border** | Jurisdictional nightmare | Borderless |

**Narration:** "This only works because GenLayer lets smart contracts think. No other chain has AI-consensus built into the validator layer. Veritas doesn't bolt AI onto a blockchain -- it uses a blockchain that is AI-native."

### Scene 5: Close (2:50 - 3:00)

**Visual:** Veritas logo. "$91,000 -> <$1"

**Narration:** "Veritas. Justice in minutes, not months. Built on GenLayer."

---

## Submission Checklist

- [x] GenLayer intelligent contract with full arbitration lifecycle
- [x] AI-consensus evidence analysis using equivalence principle
- [x] Multi-round deliberation with rebuttals
- [x] Appeal mechanism with escalating fees
- [x] On-chain escrow and automatic distribution
- [x] ELO-style reputation scoring
- [x] FastAPI backend with JWT auth and SQLite persistence
- [x] Evidence upload with SHA-256 content addressing
- [x] Demo mode with standalone operation (no GenLayer RPC needed)
- [x] Maria vs TechCorp hero story pre-loaded
- [x] Demo endpoints for full flow (create/analyze/verdict/resolve)
- [x] GenLayer deployment guide (DEPLOY_GENLAYER.md)
- [x] Landing page
- [x] Source code on GitHub
- [ ] Demo video (record per script above)
- [ ] DoraHacks BUIDL page published
- [ ] Frontend connected to GenLayer testnet (in progress)
