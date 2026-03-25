# Veritas -- GenLayer Bradbury Hackathon Submission

**Hackathon:** GenLayer Testnet Bradbury Hackathon (DoraHacks)
**Deadline:** Late March 2026
**Team:** Xpandia
**Repo:** https://github.com/xpandia/veritas

---

## Submission Text

### One-Liner

Veritas is the first AI-powered decentralized arbitration protocol -- replacing human arbitrators with GenLayer's AI-consensus validators to resolve disputes in minutes instead of months, for dollars instead of tens of thousands.

### Project Description

Dispute resolution is fundamentally broken. A simple contract disagreement costs $91,000+ in legal fees and takes 12-18 months to resolve. Cross-border disputes are worse. Arbitration was supposed to fix this -- it didn't. It just became litigation with fewer rules and the same bills.

Veritas reimagines arbitration from first principles using GenLayer's unique capability: smart contracts that can *reason*. Instead of paying three human arbitrators $500/hour to read briefs for six months, Veritas submits disputes to a decentralized network of AI validators that read evidence, deliberate through multi-round analysis, and render binding verdicts -- all on-chain, all transparent, all in minutes.

**Why GenLayer is essential:** This is not a project that "uses GenLayer because it's the hackathon sponsor." GenLayer is the *only* blockchain where smart contracts can call LLMs, analyze subjective evidence, and reach consensus on non-deterministic outputs. Arbitration requires exactly this: evaluating conflicting human claims, weighing evidence quality, and making judgment calls. No other chain can do this natively. Veritas could not exist without GenLayer.

### What We Built

**Intelligent Contract (GenLayer native -- Python):**
- Full dispute lifecycle management: FILED -> EVIDENCE_SUBMISSION -> DELIBERATION -> VERDICT -> APPEAL -> RESOLVED
- AI-powered evidence analysis using GenLayer's `call_llm_with_principle` equivalence mechanism
- Multi-round deliberation with rebuttals (up to 3 rounds per dispute)
- Consensus-based verdicts requiring validator supermajority agreement on outcome AND escrow split
- Appeal mechanism with escalating fees and fresh deliberation (up to 2 appeals)
- On-chain escrow management with automatic distribution per verdict
- ELO-style reputation scoring for all parties (tracks wins, losses, compliance, appeal success)
- Platform fee system (2.5% in basis points) with treasury accumulation

**Backend (FastAPI + SQLite):**
- Case management API with full CRUD and lifecycle transitions
- Evidence upload system with SHA-256 content-addressed storage
- JWT authentication for user identity
- AI analysis proxy that forwards to the GenLayer contract
- Case timeline tracking (event log per dispute)
- Notification system (in-app + webhook)
- Analytics dashboard data endpoints

**Frontend:**
- Landing page presenting the Veritas value proposition
- Clean UI for dispute filing and case tracking

### AI-Consensus Arbitration Flow

1. **File** -- A claimant submits a dispute with category, description, and escrow deposit. The contract validates inputs, locks funds, and initializes reputation records for both parties.

2. **Submit Evidence** -- Both parties upload evidence (documents, communications, transactions, testimony, expert reports). Each piece is content-addressed by hash and timestamped on-chain. Evidence is accepted until the block-based deadline.

3. **AI Analysis** -- GenLayer validators independently query the LLM with a structured prompt containing all evidence. The equivalence principle ensures validators agree on the preliminary assessment (favor_claimant / favor_respondent / insufficient_evidence / requires_more_deliberation) and confidence level. This is not a single AI making a decision -- it is a *consensus of independent AI analyses*.

4. **Deliberate** -- Parties can submit rebuttals and trigger additional rounds. Each round re-analyzes all accumulated evidence. After max rounds, the contract automatically moves to verdict.

5. **Verdict** -- The LLM renders a definitive ruling with outcome, escrow split percentage, confidence level, and multi-paragraph reasoning. Validators must reach consensus on the outcome category and agree on the escrow split within 10 percentage points.

6. **Appeal** -- Either party can appeal with escalating fees (base * 2^appeal_count). Appeals reset deliberation with fresh analysis of all evidence including new submissions. Maximum 2 appeals per dispute.

7. **Resolve** -- After the appeal window closes, escrow is distributed per the verdict split. Reputation scores update: winners gain 25-30 points, losers lose 20, settlements gain 10, dismissals cost 10 + compliance decay.

---

## Demo Video Script (3 minutes)

### Scene 1: The Problem (0:00 - 0:30)

**Visual:** Legal fee invoices, calendar pages turning, frustrated business owners. Stats overlay.

**Narration:** "Resolving a contract dispute costs $91,000 and takes over a year. Cross-border? Even worse. Small businesses and individuals simply can't afford justice. Arbitration was supposed to be the answer -- but it became litigation-lite with the same price tag."

### Scene 2: How Veritas Works (0:30 - 1:00)

**Visual:** Architecture diagram animating the flow: dispute filed -> evidence submitted -> AI validators deliberate -> verdict rendered -> escrow distributed.

**Narration:** "Veritas replaces human arbitrators with AI-consensus validators on GenLayer. Multiple AI validators independently analyze the evidence, deliberate, and converge on a verdict. No single AI decides -- the network reaches consensus. Verdicts are binding, transparent, and execute automatically on-chain."

### Scene 3: Live Demo (1:00 - 2:30)

**Visual:** Screen recording of the application.

1. **(1:00 - 1:20)** **File a Dispute** -- Show the API filing a contract breach dispute between two parties. Highlight the automatic escrow locking, platform fee deduction, and evidence deadline assignment.

2. **(1:20 - 1:40)** **Submit Evidence** -- Both parties submit evidence: the claimant uploads the original contract and communication logs showing breach; the respondent uploads payment records and a force majeure claim. Show evidence hashes recorded on-chain.

3. **(1:40 - 2:00)** **AI Analysis** -- Trigger the `analyze_evidence` call. Show the GenLayer equivalence principle in action: the LLM produces a structured analysis with evidence summary, strengths/weaknesses for each party, inconsistencies flagged, and a preliminary assessment with confidence level.

4. **(2:00 - 2:15)** **Verdict** -- Advance deliberation to final round. Show the verdict response: OUTCOME (claimant_wins), ESCROW_SPLIT (85% to claimant), CONFIDENCE (high), and detailed REASONING paragraphs explaining the factual and legal basis.

5. **(2:15 - 2:30)** **Resolution** -- Call `resolve_and_distribute`. Show escrow funds split per verdict. Show updated reputation scores for both parties.

### Scene 4: Why GenLayer (2:30 - 2:50)

**Visual:** Comparison table: Traditional Arbitration vs. Veritas.

| | Traditional | Veritas |
|---|---|---|
| **Cost** | $91,000+ | < $10 |
| **Time** | 12-18 months | Minutes |
| **Transparency** | Closed hearings | On-chain, auditable |
| **Appeals** | Months per appeal | Instant re-deliberation |
| **Cross-border** | Jurisdictional nightmare | Borderless by design |

**Narration:** "This only works because GenLayer lets smart contracts think. No other chain has AI-consensus built into the validator layer. Veritas doesn't bolt AI onto a blockchain -- it uses a blockchain that *is* AI-native."

### Scene 5: Close (2:50 - 3:00)

**Visual:** Veritas logo. Tagline: "Truth needs no advocate. Just consensus."

**Narration:** "Veritas. Justice in minutes, not months. Built on GenLayer."

**End card:** GitHub URL. Team names. GenLayer Bradbury testnet.

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/xpandia/veritas.git
cd veritas

# Backend
cd src/backend
pip install -r requirements.txt

# Set environment variables
export JWT_SECRET="your-secret-key"
export ARBITRATION_CONTRACT_ADDRESS="<deployed-contract-address>"
export GENLAYER_RPC_URL="http://localhost:4000/api"

# Start the server
python server.py
# API available at http://localhost:8000
# API docs at http://localhost:8000/docs

# Frontend -- open the landing page
open src/frontend/index.html

# Contracts -- deploy to GenLayer testnet
cd src/contracts
# Follow GenLayer deployment documentation:
# https://docs.genlayer.com/
```

### Key API Flows to Demo

```bash
# 1. Register a user and get JWT token
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "claimant", "password": "demo123"}'

# 2. File a dispute
curl -X POST http://localhost:8000/disputes \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"respondent": "0xRespondent", "category": "contract_breach", "title": "Service Agreement Breach", "description": "Vendor failed to deliver...", "escrow_amount": 1000}'

# 3. Submit evidence
curl -X POST http://localhost:8000/disputes/VRT-000001/evidence \
  -H "Authorization: Bearer <token>" \
  -F "file=@contract.pdf" \
  -F "evidence_type=document" \
  -F "description=Original service agreement"

# 4. Trigger AI analysis
curl -X POST http://localhost:8000/disputes/VRT-000001/analyze \
  -H "Authorization: Bearer <token>"

# 5. Get verdict
curl -X POST http://localhost:8000/disputes/VRT-000001/verdict \
  -H "Authorization: Bearer <token>"
```

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
- [x] Landing page
- [x] Source code on GitHub
- [ ] Demo video (record per script above)
- [ ] DoraHacks BUIDL page published
- [ ] Frontend connected to GenLayer testnet (in progress)
