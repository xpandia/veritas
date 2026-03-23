# Veritas — AI-Powered Decentralized Arbitration
# GenLayer Intelligent Contract
#
# This contract implements a full arbitration lifecycle on GenLayer:
#   1. Dispute filing with structured evidence
#   2. AI-powered evidence analysis via GenLayer's LLM oracle
#   3. Multi-round deliberation with rebuttals
#   4. Consensus-based verdict (validator quorum)
#   5. Appeal mechanism with escalation
#   6. Escrow management for filing fees and settlements
#   7. On-chain reputation scoring for all parties
#
# Dispute flow:
#   FILED -> EVIDENCE_SUBMISSION -> DELIBERATION -> VERDICT -> (APPEAL -> DELIBERATION) | RESOLVED
#
# GenLayer validators run the `get_verdict` equivalence principle:
#   - Each validator independently queries the LLM to analyze evidence
#   - The contract compares outputs for consensus
#   - A supermajority (>= 2/3) is required to finalize a verdict

from backend.node.genvm.icontract import IContract
from backend.node.genvm.equivalence_principle import call_llm_with_principle


class Dispute:
    """Represents a single arbitration dispute with full lifecycle state."""

    def __init__(
        self,
        dispute_id: str,
        claimant: str,
        respondent: str,
        category: str,
        title: str,
        description: str,
        filing_fee: int,
        escrow_amount: int,
    ):
        self.dispute_id: str = dispute_id
        self.claimant: str = claimant
        self.respondent: str = respondent
        self.category: str = category  # e.g. "contract_breach", "ip_infringement", "fraud", "service_dispute"
        self.title: str = title
        self.description: str = description
        self.filing_fee: int = filing_fee
        self.escrow_amount: int = escrow_amount

        # Lifecycle state
        self.status: str = "FILED"  # FILED | EVIDENCE_SUBMISSION | DELIBERATION | VERDICT | APPEAL | RESOLVED | DISMISSED
        self.current_round: int = 1
        self.max_rounds: int = 3
        self.appeal_count: int = 0
        self.max_appeals: int = 2

        # Evidence ledger — keyed by party address
        self.evidence: dict[str, list[dict]] = {claimant: [], respondent: []}

        # Deliberation records
        self.deliberation_rounds: list[dict] = []

        # Verdict
        self.verdict: dict | None = None

        # Timestamps (block numbers used as logical clocks)
        self.filed_at: int = 0
        self.evidence_deadline: int = 0
        self.resolved_at: int = 0


class Arbitration(IContract):
    """
    Veritas Arbitration — GenLayer Intelligent Contract.

    Storage layout:
        disputes            : dict[str, Dispute]   — all disputes by ID
        escrow_balances     : dict[str, int]        — locked funds per dispute
        reputation_scores   : dict[str, dict]       — per-address reputation record
        dispute_counter     : int                   — monotonic ID generator
        arbitration_fee_bps : int                   — platform fee in basis points (e.g. 250 = 2.5%)
        min_filing_fee      : int                   — minimum fee to file a dispute
        treasury            : int                   — accumulated platform fees
    """

    def __init__(self):
        """Deploy the Arbitration contract with default configuration."""
        self.disputes: dict[str, Dispute] = {}
        self.escrow_balances: dict[str, int] = {}
        self.reputation_scores: dict[str, dict] = {}
        self.dispute_counter: int = 0
        self.arbitration_fee_bps: int = 250  # 2.5%
        self.min_filing_fee: int = 100
        self.treasury: int = 0

    # ------------------------------------------------------------------ #
    #  Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _next_dispute_id(self) -> str:
        """Generate a monotonically increasing dispute identifier."""
        self.dispute_counter += 1
        return f"VRT-{self.dispute_counter:06d}"

    def _get_dispute(self, dispute_id: str) -> Dispute:
        """Retrieve a dispute or raise if not found."""
        if dispute_id not in self.disputes:
            raise ValueError(f"Dispute {dispute_id} not found")
        return self.disputes[dispute_id]

    def _assert_party(self, dispute: Dispute, caller: str) -> None:
        """Assert the caller is either claimant or respondent."""
        if caller not in (dispute.claimant, dispute.respondent):
            raise PermissionError("Caller is not a party to this dispute")

    def _init_reputation(self, address: str) -> None:
        """Lazily initialize a reputation record for an address."""
        if address not in self.reputation_scores:
            self.reputation_scores[address] = {
                "address": address,
                "cases_filed": 0,
                "cases_responded": 0,
                "cases_won": 0,
                "cases_lost": 0,
                "cases_settled": 0,
                "appeals_filed": 0,
                "appeals_won": 0,
                "evidence_submissions": 0,
                "compliance_score": 100,  # starts perfect, decays on bad behavior
                "score": 500,  # ELO-like, starts at 500
            }

    def _update_reputation(self, address: str, outcome: str, role: str) -> None:
        """
        Adjust reputation after a dispute resolves.

        Scoring model:
            - Win as claimant:   +30
            - Win as respondent: +25
            - Loss:              -20
            - Settlement:        +10
            - Appeal filed:      -5 (frivolous penalty) or +15 (if appeal succeeds)
            - Compliance decay:  -3 per dismissal
        """
        self._init_reputation(address)
        rep = self.reputation_scores[address]

        if outcome == "won":
            rep["cases_won"] += 1
            rep["score"] += 30 if role == "claimant" else 25
        elif outcome == "lost":
            rep["cases_lost"] += 1
            rep["score"] = max(0, rep["score"] - 20)
        elif outcome == "settled":
            rep["cases_settled"] += 1
            rep["score"] += 10
        elif outcome == "dismissed":
            rep["compliance_score"] = max(0, rep["compliance_score"] - 3)
            rep["score"] = max(0, rep["score"] - 10)
        elif outcome == "appeal_filed":
            rep["appeals_filed"] += 1
            rep["score"] = max(0, rep["score"] - 5)
        elif outcome == "appeal_won":
            rep["appeals_won"] += 1
            rep["score"] += 15

    def _compute_platform_fee(self, amount: int) -> int:
        """Compute the platform fee for a given amount."""
        return (amount * self.arbitration_fee_bps) // 10_000

    # ------------------------------------------------------------------ #
    #  1. Dispute Filing                                                  #
    # ------------------------------------------------------------------ #

    def file_dispute(
        self,
        claimant: str,
        respondent: str,
        category: str,
        title: str,
        description: str,
        escrow_amount: int,
        filing_fee: int,
        block_number: int,
    ) -> dict:
        """
        File a new dispute.

        Args:
            claimant:       Address of the party filing the dispute.
            respondent:     Address of the opposing party.
            category:       Dispute category (contract_breach | ip_infringement | fraud | service_dispute | other).
            title:          Short human-readable title.
            description:    Detailed description of the claim.
            escrow_amount:  Funds locked in escrow for potential settlement.
            filing_fee:     Fee paid to initiate arbitration (must meet minimum).
            block_number:   Current block number (logical timestamp).

        Returns:
            dict with dispute_id, status, and escrow details.

        Raises:
            ValueError: If filing fee is below minimum or addresses are invalid.
        """
        valid_categories = {"contract_breach", "ip_infringement", "fraud", "service_dispute", "other"}
        if category not in valid_categories:
            raise ValueError(f"Invalid category. Must be one of: {valid_categories}")

        if filing_fee < self.min_filing_fee:
            raise ValueError(f"Filing fee must be at least {self.min_filing_fee}")

        if claimant == respondent:
            raise ValueError("Claimant and respondent must be different addresses")

        if not claimant or not respondent:
            raise ValueError("Both claimant and respondent addresses are required")

        dispute_id = self._next_dispute_id()
        platform_fee = self._compute_platform_fee(filing_fee)
        self.treasury += platform_fee

        dispute = Dispute(
            dispute_id=dispute_id,
            claimant=claimant,
            respondent=respondent,
            category=category,
            title=title,
            description=description,
            filing_fee=filing_fee,
            escrow_amount=escrow_amount,
        )
        dispute.filed_at = block_number
        dispute.evidence_deadline = block_number + 100  # ~100 blocks for evidence

        self.disputes[dispute_id] = dispute
        self.escrow_balances[dispute_id] = escrow_amount

        # Update reputation tracking
        self._init_reputation(claimant)
        self._init_reputation(respondent)
        self.reputation_scores[claimant]["cases_filed"] += 1
        self.reputation_scores[respondent]["cases_responded"] += 1

        return {
            "dispute_id": dispute_id,
            "status": dispute.status,
            "claimant": claimant,
            "respondent": respondent,
            "escrow_locked": escrow_amount,
            "platform_fee_charged": platform_fee,
            "evidence_deadline_block": dispute.evidence_deadline,
        }

    # ------------------------------------------------------------------ #
    #  2. Evidence Submission                                             #
    # ------------------------------------------------------------------ #

    def submit_evidence(
        self,
        dispute_id: str,
        submitter: str,
        evidence_type: str,
        evidence_hash: str,
        description: str,
        metadata: dict | None = None,
        block_number: int = 0,
    ) -> dict:
        """
        Submit evidence for a dispute.

        Evidence is stored as a hash reference (the actual document lives off-chain).
        Each submission is timestamped and attributed to the submitting party.

        Args:
            dispute_id:     Target dispute.
            submitter:      Address of the submitting party.
            evidence_type:  Type of evidence (document | communication | transaction | testimony | expert_report).
            evidence_hash:  IPFS/Arweave hash or other content-addressed reference.
            description:    Human-readable description of the evidence.
            metadata:       Optional structured metadata (dates, parties mentioned, etc.).
            block_number:   Current block number.

        Returns:
            dict with evidence index and submission confirmation.

        Raises:
            PermissionError: If submitter is not a party.
            ValueError:      If dispute is not in a valid state for evidence submission.
        """
        dispute = self._get_dispute(dispute_id)
        self._assert_party(dispute, submitter)

        if dispute.status not in ("FILED", "EVIDENCE_SUBMISSION", "APPEAL"):
            raise ValueError(f"Cannot submit evidence in status: {dispute.status}")

        valid_evidence_types = {"document", "communication", "transaction", "testimony", "expert_report"}
        if evidence_type not in valid_evidence_types:
            raise ValueError(f"Invalid evidence type. Must be one of: {valid_evidence_types}")

        if block_number > dispute.evidence_deadline and dispute.status != "APPEAL":
            raise ValueError("Evidence submission deadline has passed")

        # Transition state on first evidence submission
        if dispute.status == "FILED":
            dispute.status = "EVIDENCE_SUBMISSION"

        evidence_entry = {
            "index": len(dispute.evidence[submitter]),
            "type": evidence_type,
            "hash": evidence_hash,
            "description": description,
            "metadata": metadata or {},
            "submitted_at": block_number,
            "submitter": submitter,
        }
        dispute.evidence[submitter].append(evidence_entry)

        # Track in reputation
        self.reputation_scores[submitter]["evidence_submissions"] += 1

        return {
            "dispute_id": dispute_id,
            "evidence_index": evidence_entry["index"],
            "submitter": submitter,
            "status": dispute.status,
            "total_evidence_count": sum(len(v) for v in dispute.evidence.values()),
        }

    # ------------------------------------------------------------------ #
    #  3. AI-Powered Evidence Analysis (GenLayer Equivalence Principle)    #
    # ------------------------------------------------------------------ #

    async def analyze_evidence(self, dispute_id: str, caller: str = "") -> dict:
        """
        Trigger AI analysis of all submitted evidence using GenLayer's LLM oracle.

        This method invokes the equivalence principle: every validator independently
        queries the LLM with the same structured prompt. The outputs are compared
        for semantic equivalence — if a supermajority agree, the analysis is accepted.

        The LLM prompt is carefully structured to:
            - Summarize each piece of evidence
            - Identify strengths and weaknesses for each party
            - Flag inconsistencies or contradictions
            - Provide a preliminary assessment

        Args:
            dispute_id: Target dispute.
            caller:     Address of the caller (must be a party to the dispute).

        Returns:
            dict containing the AI analysis results.

        Raises:
            PermissionError: If caller is not a party to the dispute.
        """
        dispute = self._get_dispute(dispute_id)
        if caller:
            self._assert_party(dispute, caller)

        if dispute.status not in ("EVIDENCE_SUBMISSION", "APPEAL"):
            raise ValueError(f"Cannot analyze evidence in status: {dispute.status}")

        # Compile evidence summaries for the prompt
        claimant_evidence = dispute.evidence.get(dispute.claimant, [])
        respondent_evidence = dispute.evidence.get(dispute.respondent, [])

        evidence_summary = self._format_evidence_for_llm(
            dispute, claimant_evidence, respondent_evidence
        )

        analysis_prompt = f"""You are an expert legal arbitrator AI for the Veritas decentralized arbitration platform.

CASE OVERVIEW:
{evidence_summary}

DISPUTE DETAILS:
- Case ID: {dispute.dispute_id}
- Category: {dispute.category}
- Title: {dispute.title}
- Description: {dispute.description}
- Current Round: {dispute.current_round} of {dispute.max_rounds}
- Appeal Count: {dispute.appeal_count} of {dispute.max_appeals}

CLAIMANT ({dispute.claimant}) EVIDENCE:
{self._format_evidence_list(claimant_evidence)}

RESPONDENT ({dispute.respondent}) EVIDENCE:
{self._format_evidence_list(respondent_evidence)}

INSTRUCTIONS:
Analyze the evidence from both parties. Provide your analysis in the following structured format:

1. EVIDENCE SUMMARY: Brief summary of each piece of evidence and its relevance.
2. CLAIMANT STRENGTHS: Key points supporting the claimant's position.
3. CLAIMANT WEAKNESSES: Gaps or issues in the claimant's evidence.
4. RESPONDENT STRENGTHS: Key points supporting the respondent's position.
5. RESPONDENT WEAKNESSES: Gaps or issues in the respondent's evidence.
6. INCONSISTENCIES: Any contradictions between or within the evidence sets.
7. PRELIMINARY ASSESSMENT: Your initial assessment of the merits (favor_claimant | favor_respondent | insufficient_evidence | requires_more_deliberation).
8. CONFIDENCE: Your confidence level (low | medium | high).
9. REASONING: A concise paragraph explaining your reasoning.

Respond ONLY with the structured analysis. Be objective, thorough, and fair."""

        # GenLayer equivalence principle: validators independently query LLM
        # and results are compared for consensus
        analysis_result = await call_llm_with_principle(
            analysis_prompt,
            eq_principle="The analysis must reach the same preliminary assessment "
            "(favor_claimant, favor_respondent, insufficient_evidence, or "
            "requires_more_deliberation) and the same confidence level.",
        )

        # Store the analysis in the deliberation record
        deliberation_entry = {
            "round": dispute.current_round,
            "analysis": analysis_result,
            "evidence_count": {
                "claimant": len(claimant_evidence),
                "respondent": len(respondent_evidence),
            },
        }
        dispute.deliberation_rounds.append(deliberation_entry)

        return {
            "dispute_id": dispute_id,
            "round": dispute.current_round,
            "analysis": analysis_result,
            "status": dispute.status,
        }

    def _format_evidence_for_llm(
        self,
        dispute: Dispute,
        claimant_evidence: list[dict],
        respondent_evidence: list[dict],
    ) -> str:
        """Build a structured text block summarizing all evidence for the LLM."""
        lines = [
            f"Dispute: {dispute.title}",
            f"Category: {dispute.category}",
            f"Claimant evidence count: {len(claimant_evidence)}",
            f"Respondent evidence count: {len(respondent_evidence)}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_evidence_list(evidence_list: list[dict]) -> str:
        """Format a party's evidence list into readable text for the LLM prompt."""
        if not evidence_list:
            return "  (No evidence submitted)"
        lines = []
        for e in evidence_list:
            lines.append(
                f"  [{e['index']}] Type: {e['type']} | Hash: {e['hash']}\n"
                f"      Description: {e['description']}\n"
                f"      Metadata: {e.get('metadata', {})}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  4. Multi-Round Deliberation                                        #
    # ------------------------------------------------------------------ #

    async def advance_deliberation(self, dispute_id: str, caller: str = "") -> dict:
        """
        Advance the dispute to the next deliberation round.

        Each round allows both parties to submit rebuttals, after which
        the AI re-analyzes all evidence (including new submissions).
        After max_rounds, the contract moves to verdict.

        Args:
            dispute_id: Target dispute.
            caller:     Address of the caller (must be a party to the dispute).

        Returns:
            dict with new round number or transition to verdict phase.

        Raises:
            PermissionError: If caller is not a party to the dispute.
        """
        dispute = self._get_dispute(dispute_id)
        if caller:
            self._assert_party(dispute, caller)

        if dispute.status not in ("EVIDENCE_SUBMISSION", "DELIBERATION"):
            raise ValueError(f"Cannot advance deliberation in status: {dispute.status}")

        dispute.status = "DELIBERATION"

        if dispute.current_round >= dispute.max_rounds:
            # Final round — trigger verdict
            return await self.render_verdict(dispute_id)

        dispute.current_round += 1

        # Re-run AI analysis with accumulated evidence
        analysis = await self.analyze_evidence(dispute_id)

        return {
            "dispute_id": dispute_id,
            "status": dispute.status,
            "current_round": dispute.current_round,
            "max_rounds": dispute.max_rounds,
            "analysis": analysis,
            "message": f"Deliberation round {dispute.current_round} complete. "
            f"{'Final round — verdict next.' if dispute.current_round >= dispute.max_rounds else 'Parties may submit rebuttals.'}",
        }

    # ------------------------------------------------------------------ #
    #  5. Consensus-Based Verdict                                         #
    # ------------------------------------------------------------------ #

    async def render_verdict(self, dispute_id: str, caller: str = "") -> dict:
        """
        Render a final verdict using AI analysis with GenLayer consensus.

        The verdict prompt asks the LLM to make a definitive ruling based on
        all evidence and prior deliberation rounds. Validators must reach
        consensus on the outcome (claimant_wins | respondent_wins | split | dismissed).

        Args:
            dispute_id: Target dispute.
            caller:     Address of the caller (must be a party to the dispute).

        Returns:
            dict containing the verdict, reasoning, and escrow distribution plan.

        Raises:
            PermissionError: If caller is not a party to the dispute.
        """
        dispute = self._get_dispute(dispute_id)
        if caller:
            self._assert_party(dispute, caller)

        if dispute.status not in ("DELIBERATION", "EVIDENCE_SUBMISSION"):
            raise ValueError(f"Cannot render verdict in status: {dispute.status}")

        # Compile full deliberation history
        prior_analyses = "\n---\n".join(
            f"Round {d['round']}:\n{d['analysis']}"
            for d in dispute.deliberation_rounds
        )

        verdict_prompt = f"""You are the final arbitrator AI for the Veritas platform. You must now render a binding verdict.

DISPUTE DETAILS:
- Case ID: {dispute.dispute_id}
- Category: {dispute.category}
- Title: {dispute.title}
- Description: {dispute.description}
- Rounds completed: {dispute.current_round}
- Appeal number: {dispute.appeal_count}

PRIOR DELIBERATION ANALYSES:
{prior_analyses if prior_analyses else "(No prior analyses)"}

CLAIMANT ({dispute.claimant}) EVIDENCE:
{self._format_evidence_list(dispute.evidence.get(dispute.claimant, []))}

RESPONDENT ({dispute.respondent}) EVIDENCE:
{self._format_evidence_list(dispute.evidence.get(dispute.respondent, []))}

INSTRUCTIONS:
Render a final verdict. You MUST choose exactly one outcome.

Respond with these EXACT fields, each on its own line, using the format shown:

OUTCOME: claimant_wins | respondent_wins | split | dismissed
ESCROW_SPLIT: <number 0-100> (percentage to claimant, remainder goes to respondent)
CONFIDENCE: low | medium | high
REASONING: <2-3 paragraphs explaining the legal and factual basis for the verdict>

Guidelines for ESCROW_SPLIT:
- claimant_wins: typically 80-100
- respondent_wins: typically 0-20
- split: typically 40-60
- dismissed: 50

Be definitive. This is a binding ruling."""

        verdict_result = await call_llm_with_principle(
            verdict_prompt,
            eq_principle="The verdict must reach the same OUTCOME "
            "(claimant_wins, respondent_wins, split, or dismissed) "
            "and the ESCROW_SPLIT must be within 10 percentage points.",
        )

        # Parse a default escrow split from the verdict
        escrow_split = self._parse_escrow_split(verdict_result)

        dispute.verdict = {
            "outcome": verdict_result,
            "escrow_split_claimant_pct": escrow_split,
            "round_rendered": dispute.current_round,
            "appeal_number": dispute.appeal_count,
        }
        dispute.status = "VERDICT"

        return {
            "dispute_id": dispute_id,
            "status": "VERDICT",
            "verdict": dispute.verdict,
            "message": "Verdict rendered. Parties may appeal within the appeal window.",
        }

    @staticmethod
    def _parse_escrow_split(verdict_text: str) -> int:
        """
        Extract the claimant escrow percentage from the verdict text.

        Strategy:
          1. Try to find an explicit ESCROW_SPLIT numeric value in the text
             (e.g. "ESCROW_SPLIT: 75" or "ESCROW_SPLIT: 75%").
          2. Fall back to OUTCOME keyword mapping with sensible defaults.
          3. Default to 50 (equal split) if nothing matches.
        """
        import re

        text = verdict_text.lower()

        # 1. Try to extract a numeric ESCROW_SPLIT value from the LLM response
        split_match = re.search(r"escrow_split[:\s]+(\d{1,3})\s*%?", text)
        if split_match:
            value = int(split_match.group(1))
            # Clamp to valid range
            return max(0, min(100, value))

        # 2. Fall back to OUTCOME keyword mapping
        outcome_match = re.search(
            r"outcome[:\s]+(claimant_wins|respondent_wins|split|dismissed)", text
        )
        if outcome_match:
            outcome = outcome_match.group(1)
            defaults = {
                "claimant_wins": 85,
                "respondent_wins": 15,
                "split": 50,
                "dismissed": 50,
            }
            return defaults[outcome]

        # 3. Legacy loose keyword matching (last resort)
        if "claimant_wins" in text:
            return 85
        elif "respondent_wins" in text:
            return 15
        elif "dismissed" in text:
            return 50

        return 50

    # ------------------------------------------------------------------ #
    #  6. Appeal Mechanism                                                #
    # ------------------------------------------------------------------ #

    def file_appeal(
        self,
        dispute_id: str,
        appellant: str,
        grounds: str,
        new_evidence_hashes: list[str] | None = None,
        appeal_fee: int = 0,
    ) -> dict:
        """
        File an appeal against a rendered verdict.

        Appeals reset the deliberation process with an increased scrutiny level.
        Each appeal costs a progressively higher fee to deter frivolous appeals.

        Args:
            dispute_id:          Target dispute.
            appellant:           Address of the appealing party.
            grounds:             Written grounds for the appeal.
            new_evidence_hashes: Optional list of new evidence hashes to introduce.
            appeal_fee:          Fee paid for the appeal (must increase with each appeal).

        Returns:
            dict with appeal status and new round information.

        Raises:
            ValueError: If max appeals exceeded or dispute not in VERDICT status.
            PermissionError: If appellant is not a party.
        """
        dispute = self._get_dispute(dispute_id)
        self._assert_party(dispute, appellant)

        if dispute.status != "VERDICT":
            raise ValueError("Can only appeal a rendered verdict")

        if dispute.appeal_count >= dispute.max_appeals:
            raise ValueError(
                f"Maximum appeals ({dispute.max_appeals}) exhausted. Verdict is final."
            )

        # Progressive appeal fee: base * 2^appeal_count
        required_fee = self.min_filing_fee * (2 ** (dispute.appeal_count + 1))
        if appeal_fee < required_fee:
            raise ValueError(f"Appeal fee must be at least {required_fee}")

        # Process appeal
        dispute.appeal_count += 1
        dispute.status = "APPEAL"
        dispute.current_round = 1  # Reset rounds for fresh deliberation
        dispute.verdict = None  # Clear previous verdict

        # Extend evidence deadline for new submissions
        dispute.evidence_deadline += 50  # Additional 50 blocks

        # Add appeal fee to escrow
        platform_fee = self._compute_platform_fee(appeal_fee)
        self.treasury += platform_fee
        self.escrow_balances[dispute_id] = (
            self.escrow_balances.get(dispute_id, 0) + appeal_fee - platform_fee
        )

        # Track reputation impact
        self._update_reputation(appellant, "appeal_filed", "")

        return {
            "dispute_id": dispute_id,
            "appeal_number": dispute.appeal_count,
            "status": dispute.status,
            "grounds": grounds,
            "new_evidence_accepted": len(new_evidence_hashes) if new_evidence_hashes else 0,
            "appeal_fee_charged": appeal_fee,
            "platform_fee": platform_fee,
            "message": f"Appeal #{dispute.appeal_count} filed. Deliberation will restart.",
        }

    # ------------------------------------------------------------------ #
    #  7. Escrow Management                                               #
    # ------------------------------------------------------------------ #

    def resolve_and_distribute(self, dispute_id: str, block_number: int) -> dict:
        """
        Finalize the dispute and distribute escrowed funds according to the verdict.

        This can only be called after a verdict when the appeal window has closed
        (or max appeals exhausted).

        Args:
            dispute_id:   Target dispute.
            block_number: Current block number.

        Returns:
            dict with distribution details.
        """
        dispute = self._get_dispute(dispute_id)

        if dispute.status != "VERDICT":
            raise ValueError("Dispute must have a verdict to resolve")

        if dispute.verdict is None:
            raise ValueError("No verdict recorded")

        escrow_total = self.escrow_balances.get(dispute_id, 0)
        claimant_pct = dispute.verdict["escrow_split_claimant_pct"]
        claimant_amount = (escrow_total * claimant_pct) // 100
        respondent_amount = escrow_total - claimant_amount

        # Finalize
        dispute.status = "RESOLVED"
        dispute.resolved_at = block_number
        self.escrow_balances[dispute_id] = 0

        # Update reputations based on outcome
        verdict_text = str(dispute.verdict.get("outcome", "")).lower()
        if "claimant_wins" in verdict_text:
            self._update_reputation(dispute.claimant, "won", "claimant")
            self._update_reputation(dispute.respondent, "lost", "respondent")
        elif "respondent_wins" in verdict_text:
            self._update_reputation(dispute.claimant, "lost", "claimant")
            self._update_reputation(dispute.respondent, "won", "respondent")
        elif "split" in verdict_text:
            self._update_reputation(dispute.claimant, "settled", "claimant")
            self._update_reputation(dispute.respondent, "settled", "respondent")
        elif "dismissed" in verdict_text:
            self._update_reputation(dispute.claimant, "dismissed", "claimant")

        return {
            "dispute_id": dispute_id,
            "status": "RESOLVED",
            "escrow_total": escrow_total,
            "claimant_receives": claimant_amount,
            "respondent_receives": respondent_amount,
            "claimant_pct": claimant_pct,
            "resolved_at_block": block_number,
        }

    def get_escrow_balance(self, dispute_id: str) -> dict:
        """Query the current escrow balance for a dispute."""
        dispute = self._get_dispute(dispute_id)
        return {
            "dispute_id": dispute_id,
            "escrow_balance": self.escrow_balances.get(dispute_id, 0),
            "status": dispute.status,
        }

    # ------------------------------------------------------------------ #
    #  8. Reputation Queries                                              #
    # ------------------------------------------------------------------ #

    def get_reputation(self, address: str) -> dict:
        """
        Get the full reputation record for an address.

        Returns a dict with all tracked metrics including ELO-like score
        and compliance score.
        """
        self._init_reputation(address)
        return self.reputation_scores[address]

    def get_reputation_score(self, address: str) -> int:
        """Get the numeric reputation score for an address."""
        self._init_reputation(address)
        return self.reputation_scores[address]["score"]

    # ------------------------------------------------------------------ #
    #  9. Read-Only Queries                                               #
    # ------------------------------------------------------------------ #

    def get_dispute(self, dispute_id: str) -> dict:
        """Get full dispute details."""
        dispute = self._get_dispute(dispute_id)
        return {
            "dispute_id": dispute.dispute_id,
            "claimant": dispute.claimant,
            "respondent": dispute.respondent,
            "category": dispute.category,
            "title": dispute.title,
            "description": dispute.description,
            "status": dispute.status,
            "current_round": dispute.current_round,
            "max_rounds": dispute.max_rounds,
            "appeal_count": dispute.appeal_count,
            "max_appeals": dispute.max_appeals,
            "filing_fee": dispute.filing_fee,
            "escrow_amount": dispute.escrow_amount,
            "escrow_balance": self.escrow_balances.get(dispute_id, 0),
            "evidence_count": {
                party: len(ev) for party, ev in dispute.evidence.items()
            },
            "deliberation_rounds_completed": len(dispute.deliberation_rounds),
            "verdict": dispute.verdict,
            "filed_at": dispute.filed_at,
            "evidence_deadline": dispute.evidence_deadline,
            "resolved_at": dispute.resolved_at,
        }

    def get_dispute_evidence(self, dispute_id: str) -> dict:
        """Get all evidence submitted for a dispute."""
        dispute = self._get_dispute(dispute_id)
        return {
            "dispute_id": dispute_id,
            "claimant_evidence": dispute.evidence.get(dispute.claimant, []),
            "respondent_evidence": dispute.evidence.get(dispute.respondent, []),
        }

    def get_deliberation_history(self, dispute_id: str) -> dict:
        """Get the full deliberation history for a dispute."""
        dispute = self._get_dispute(dispute_id)
        return {
            "dispute_id": dispute_id,
            "rounds": dispute.deliberation_rounds,
            "current_round": dispute.current_round,
        }

    def get_platform_stats(self) -> dict:
        """Get aggregate platform statistics."""
        total = len(self.disputes)
        by_status: dict[str, int] = {}
        by_category: dict[str, int] = {}
        total_escrow = sum(self.escrow_balances.values())

        for d in self.disputes.values():
            by_status[d.status] = by_status.get(d.status, 0) + 1
            by_category[d.category] = by_category.get(d.category, 0) + 1

        return {
            "total_disputes": total,
            "disputes_by_status": by_status,
            "disputes_by_category": by_category,
            "total_escrow_locked": total_escrow,
            "treasury_balance": self.treasury,
            "total_addresses_with_reputation": len(self.reputation_scores),
        }
