# VERITAS — Demo Script
### 3-Minute Live Demo
#### GenLayer Testnet Bradbury Hackathon

---

## Setup & Context

**What the audience needs to believe by the end:**
Veritas can take a real dispute — with a real contract, real evidence, and a real disagreement — and resolve it through AI consensus in minutes, on-chain, with no human intervention.

**Demo environment:** GenLayer Testnet Bradbury, Veritas frontend, live intelligent contract.

---

## THE DEMO

### [0:00 - 0:30] — SET THE SCENE

**[Show the Veritas landing page]**

> "Meet Maria. She's a freelance web designer in Buenos Aires. Three weeks ago, she finished a $2,000 website for a client in Berlin — a small e-commerce shop.
>
> She delivered the site. The client says, 'It doesn't match the mockups.' Maria says it does — she has the Figma files, the signed-off wireframes, the revision history.
>
> Now what?
>
> A lawyer in Argentina costs $150/hour. A lawyer in Germany costs more. For a $2,000 dispute, the legal fees would exceed the claim before the first email is sent.
>
> So historically, Maria eats the loss. Two thousand dollars, three weeks of work — gone.
>
> Not anymore."

---

### [0:30 - 1:15] — FILE THE DISPUTE

**[Switch to Veritas app — Dispute Filing screen]**

> "Maria opens Veritas and files a dispute. Watch how simple this is."

**[Walk through the filing form, filling in or showing pre-filled fields:]**

1. **Parties:** Maria (Claimant) vs. Client (Respondent) — wallet addresses
2. **Contract:** Upload the freelance agreement (PDF or paste key terms)
3. **Claim amount:** $2,000
4. **Evidence from Maria:**
   - The signed contract with deliverable specifications
   - Figma mockups that were approved in writing
   - The delivered website (URL)
   - Email chain showing client sign-off on wireframes
5. **Maria's argument:** "The delivered website matches the approved mockups. Client's objections reference features not in the original scope."

**[Click "Submit Dispute"]**

> "That's it. The dispute is now recorded on-chain — immutable, timestamped, transparent. The GenLayer intelligent contract has been triggered.
>
> Cost so far? A fraction of a cent in gas."

**[Show the transaction confirmation on GenLayer testnet]**

---

### [1:15 - 2:15] — AI DELIBERATION

**[Switch to the Dispute Detail screen — show the deliberation in progress]**

> "Now here's where GenLayer does something no other blockchain can do.
>
> Our intelligent contract — written in Python — is calling GenLayer's AI validator network. Multiple validators are *independently* analyzing this case right now."

**[Show the deliberation panel / validator activity:]**

> "Each validator is doing what a human arbitrator would do:
>
> **First,** reading the contract to understand what was actually agreed to — the scope, the deliverables, the acceptance criteria.
>
> **Second,** examining the evidence — comparing the mockups to the delivered site, reading the email chain for any scope changes.
>
> **Third,** applying relevant legal principles — was there substantial performance? Did the client's objections fall within or outside the original scope?
>
> **Fourth,** reaching an independent conclusion.
>
> Then GenLayer's consensus mechanism kicks in. The validators compare their reasoning. They converge on a verdict — not through voting, but through *deliberation*. If a validator's reasoning doesn't hold up against the evidence, it gets challenged."

**[The verdict appears on screen]**

> "And there it is."

---

### [2:15 - 2:50] — THE VERDICT

**[Show the full verdict on screen]**

> "The verdict: **Maria wins.** The AI validators found that the delivered website substantially matches the approved mockups. The client's objections reference features — a blog section, an advanced filter — that were never part of the original contract scope.
>
> Look at this reasoning. It's not a coin flip. It's not a popularity contest. The validators cited specific clauses from the contract, referenced the evidence, and explained *why* they reached this conclusion."

**[Highlight the reasoning section — show specific contract clause references]**

> "And now watch what happens next."

**[Show the escrow release — funds moving to Maria's wallet]**

> "The smart contract escrow automatically releases the $2,000 to Maria. No enforcement motion. No collections agency. No 'please pay within 30 days.' Done."

---

### [2:50 - 3:00] — THE CLOSE

**[Pull back to show the full resolved dispute — filed, deliberated, resolved]**

> "From filing to verdict to payment: under five minutes. Total cost: less than a dollar.
>
> Maria got her money. The client got a reasoned, evidence-based decision. And neither of them needed a lawyer.
>
> That's Veritas. AI-consensus arbitration on GenLayer.
>
> Justice shouldn't cost more than the dispute itself.
>
> Now it doesn't."

**[Veritas logo. Tagline: "Truth needs no advocate. Just consensus."]**

---

## TECHNICAL BACKUP (if judges ask)

**Q: "What's actually happening on-chain?"**
> The intelligent contract is deployed on GenLayer Testnet Bradbury. When a dispute is filed, it stores the evidence hashes and triggers an LLM call through GenLayer's native `gl.call_llm()` function. Multiple validators process the prompt independently, then reach consensus through GenLayer's optimistic rollup mechanism. The verdict is stored on-chain and the escrow function executes automatically.

**Q: "What if the AI gets it wrong?"**
> Two safeguards. First, GenLayer's consensus mechanism means multiple validators must independently agree — one rogue model can't control the outcome. Second, the system can be configured with an appeal window where a dispute escalates to a larger validator set, similar to how appellate courts work. The consensus mechanism is the key innovation — it's not one AI deciding, it's a *network* deliberating.

**Q: "Is this legally enforceable?"**
> Today, on testnet, it's a proof of concept. But the architecture is designed for enforceability. The New York Convention (1958) — ratified by 172 countries — already recognizes binding arbitration awards. The key requirements are: agreement to arbitrate, due process, and a reasoned decision. Veritas provides all three. The frontier is getting jurisdictions to recognize AI-rendered awards, and we believe the legal framework will follow the technology, just as it did with electronic signatures and online contracts.

**Q: "Why GenLayer and not just an API calling GPT-4?"**
> Three reasons. First, decentralization — no single entity controls the verdict. Second, consensus — multiple validators must agree, eliminating single-model bias. Third, on-chain execution — the verdict and the enforcement happen in the same transaction. You can't build this on Ethereum plus an API. GenLayer makes the AI reasoning *native* to the blockchain.
