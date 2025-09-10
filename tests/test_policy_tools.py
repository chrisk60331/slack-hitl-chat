from __future__ import annotations

from src.policy import PolicyEngine, PolicyRule, ProposedAction, ApprovalOutcome, ApprovalCategory


def test_policy_matches_on_tools_require_approval() -> None:
    rules = [
        PolicyRule(
            name="reset2fa_requires_approval",
            tools=["google__admin_reset2fa"],
            require_approval=True,
        )
    ]
    engine = PolicyEngine(rules=rules)
    action = ProposedAction(
        tool_name="google__admin_reset2fa",
        description="Reset 2FA",
        category=ApprovalCategory.USER_ACCOUNT_ACCESS,
        environment="dev",
        user_id="u",
        intended_tools=["google__admin_reset2fa"],
    )
    decision = engine.evaluate(action)
    assert decision.outcome == ApprovalOutcome.REQUIRE_APPROVAL





