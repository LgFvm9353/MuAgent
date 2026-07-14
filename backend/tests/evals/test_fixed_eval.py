from app.contracts.agents import AgentDecision, AgentProposal, Critique


def test_fixed_eval_fixture_is_structurally_valid() -> None:
    proposals = (
        AgentProposal(summary="bounded approach A", risks=("path traversal",), confidence=0.8),
        AgentProposal(summary="bounded approach B", risks=("budget",), confidence=0.7),
    )
    critiques = (
        Critique(proposal_index=0, findings=("requires deterministic path validation",)),
        Critique(proposal_index=1, findings=("requires token guard",)),
    )
    decision = AgentDecision(
        selected_proposal_index=0,
        rationale="better evidence boundary",
        rejected_reasons={1: "weaker verification"},
        may_plan=True,
        confidence=0.8,
    )
    assert len({proposal.summary for proposal in proposals}) == 2
    assert all(critique.findings for critique in critiques)
    assert decision.selected_proposal_index < len(proposals)
