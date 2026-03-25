# Deploying Veritas on GenLayer Bradbury Testnet

## Prerequisites

- Python 3.10+
- GenLayer Studio (browser-based IDE) OR GenLayer CLI
- A GenLayer testnet account with test tokens

## GenLayer Bradbury Testnet Details

| Parameter | Value |
|---|---|
| **Network** | GenLayer Bradbury Testnet |
| **RPC URL** | `https://studio.genlayer.com/api` |
| **Faucet** | Available inside GenLayer Studio (request test tokens) |
| **Explorer** | [https://studio.genlayer.com](https://studio.genlayer.com) |
| **Docs** | [https://docs.genlayer.com](https://docs.genlayer.com) |
| **Contract language** | Python (GenLayer Intelligent Contracts) |

## Option A: Deploy via GenLayer Studio (Recommended)

GenLayer Studio is the easiest way to deploy and test intelligent contracts.

### Step 1: Open GenLayer Studio

Navigate to [https://studio.genlayer.com](https://studio.genlayer.com) and create an account or sign in.

### Step 2: Create a new project

1. Click **New Contract**
2. Name it `Veritas_Arbitration`

### Step 3: Paste the contract code

Copy the full contents of `src/contracts/arbitration.py` into the Studio editor.

**Important:** The imports at the top of the file reference GenLayer's internal modules:

```python
from backend.node.genvm.icontract import IContract
from backend.node.genvm.equivalence_principle import call_llm_with_principle
```

These are provided by the GenLayer runtime environment. Do NOT install them locally -- they are available automatically when the contract runs on GenLayer validators.

### Step 4: Deploy

1. Click **Deploy** in the Studio toolbar
2. The contract constructor (`__init__`) will execute, initializing:
   - Empty disputes dictionary
   - Escrow balances tracker
   - Reputation scoring system
   - Platform fee configuration (2.5% / 250 basis points)
   - Minimum filing fee (100 units)
3. Note the **contract address** returned after deployment

### Step 5: Configure the backend

Set the contract address in your backend environment:

```bash
export ARBITRATION_CONTRACT_ADDRESS="<your-deployed-contract-address>"
export GENLAYER_RPC_URL="https://studio.genlayer.com/api"
```

Or add to `.env`:

```
ARBITRATION_CONTRACT_ADDRESS=<your-deployed-contract-address>
GENLAYER_RPC_URL=https://studio.genlayer.com/api
```

### Step 6: Test the contract

In GenLayer Studio, use the **Interact** tab to test each function:

#### 6a. File a dispute

```
Function: file_dispute
Args:
  claimant: "0xClaimant001"
  respondent: "0xRespondent001"
  category: "service_dispute"
  title: "Unpaid Web Development Work"
  description: "Freelancer completed all deliverables but client refused payment."
  escrow_amount: 2000
  filing_fee: 100
  block_number: 1
```

Expected: Returns `dispute_id` (e.g., `VRT-000001`), status `FILED`, escrow details.

#### 6b. Submit evidence

```
Function: submit_evidence
Args:
  dispute_id: "VRT-000001"
  submitter: "0xClaimant001"
  evidence_type: "document"
  evidence_hash: "abc123..."
  description: "Signed freelance contract"
  metadata: {}
  block_number: 2
```

#### 6c. Trigger AI analysis (equivalence principle)

```
Function: analyze_evidence
Args:
  dispute_id: "VRT-000001"
  caller: "0xClaimant001"
```

This is where GenLayer's unique capability activates:
- Each validator independently queries the LLM with the structured evidence prompt
- The equivalence principle ensures validators agree on the preliminary assessment
- Results are compared for consensus before being accepted

#### 6d. Render verdict

```
Function: render_verdict
Args:
  dispute_id: "VRT-000001"
  caller: "0xClaimant001"
```

The LLM renders a definitive ruling with:
- OUTCOME (claimant_wins / respondent_wins / split / dismissed)
- ESCROW_SPLIT (percentage)
- CONFIDENCE level
- REASONING (multi-paragraph)

Validators must reach consensus on outcome AND agree on escrow split within 10%.

#### 6e. Resolve and distribute

```
Function: resolve_and_distribute
Args:
  dispute_id: "VRT-000001"
  block_number: 100
```

Distributes escrow per verdict and updates reputation scores.

## Option B: Deploy via GenLayer CLI

If you prefer the command line:

```bash
# Install GenLayer CLI (check docs.genlayer.com for latest instructions)
pip install genlayer-cli

# Configure the testnet
genlayer config set --network bradbury

# Deploy the contract
genlayer deploy src/contracts/arbitration.py

# Note the returned contract address
# Use it to configure the backend as shown in Step 5 above
```

## Architecture: How Veritas Uses GenLayer

```
User (Frontend/API)
    |
    v
FastAPI Backend (server.py)
    |
    |-- Local: SQLite (case metadata, evidence files, user accounts)
    |-- On-chain: GenLayer RPC calls
            |
            v
      GenLayer Bradbury Testnet
            |
            |-- Arbitration Contract (arbitration.py)
            |       |-- Dispute lifecycle state machine
            |       |-- Escrow management
            |       |-- Reputation scoring
            |       |
            |       |-- call_llm_with_principle() [AI Analysis]
            |               |
            |               v
            |         GenLayer Validators (multiple)
            |               |-- Each validator independently queries LLM
            |               |-- Equivalence principle compares outputs
            |               |-- Consensus required for acceptance
            |
            v
      Verdict + Escrow Distribution (on-chain, auditable)
```

## Key GenLayer Features Used

1. **Equivalence Principle** (`call_llm_with_principle`): The core innovation. Multiple validators independently query the LLM and must agree on the output. This prevents any single AI from being the sole arbiter.

2. **Intelligent Contracts**: Python contracts that can reason about subjective evidence. No other blockchain supports this natively.

3. **Validator Consensus on Non-Deterministic Output**: Traditional blockchains require deterministic execution. GenLayer's validators can reach consensus on LLM outputs that are semantically equivalent but not byte-identical.

## Troubleshooting

| Issue | Solution |
|---|---|
| Contract deployment fails | Check that imports match GenLayer's runtime (`IContract`, `call_llm_with_principle`) |
| `analyze_evidence` timeout | LLM calls can take 30-60s. Increase client timeout. |
| Consensus not reached | For complex cases, validators may disagree. Adjust equivalence principle parameters. |
| Backend can't reach RPC | Verify `GENLAYER_RPC_URL` is correct and the testnet is up. |
| Demo mode works but on-chain fails | The backend falls back to demo mode when GenLayer is unreachable. Check `.env` config. |

## Running Without GenLayer (Demo Mode)

The backend is designed to work standalone for demos:

```bash
cd src/backend
pip install -r requirements.txt
python server.py
```

All `/api/demo/*` endpoints work without any GenLayer connection. The demo includes:
- 4 pre-seeded cases at different lifecycle stages
- The "Maria vs TechCorp" hero story (case-demo-004) with full evidence and verdict
- Mock AI analysis with realistic strengths/weaknesses/confidence
- End-to-end flow: create -> analyze -> verdict -> resolve
