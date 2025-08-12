from __future__ import annotations

from src.policy import (
    ApprovalOutcome,
    PolicyEngine,
    ProposedAction,
    ApprovalCategory,
    infer_category_and_resource,
)


def test_policy_allow_default() -> None:
    engine = PolicyEngine()
    action = ProposedAction(tool_name="read", description="Read public info")
    decision = engine.evaluate(action)
    assert decision.outcome == ApprovalOutcome.ALLOW


def test_policy_require_privileged_write() -> None:
    engine = PolicyEngine()
    action = ProposedAction(
        tool_name="write_config",
        description="Modify system settings",
        category=ApprovalCategory.PRIVILEGED_WRITE,
    )
    decision = engine.evaluate(action)
    assert decision.outcome == ApprovalOutcome.REQUIRE_APPROVAL


def test_policy_deny_prod_exfiltration() -> None:
    engine = PolicyEngine()
    action = ProposedAction(
        tool_name="download_s3",
        description="Download prod secrets",
        category=ApprovalCategory.DATA_EXFILTRATION,
        environment="prod",
        resource="arn:aws:s3:::prod-secrets/keys.json",
    )
    decision = engine.evaluate(action)
    assert decision.outcome == ApprovalOutcome.DENY


def test_policy_financial_threshold() -> None:
    engine = PolicyEngine()
    action = ProposedAction(
        tool_name="issue_payment",
        description="Expense reimbursement",
        category=ApprovalCategory.FINANCIAL,
        amount=200.0,
    )
    decision = engine.evaluate(action)
    assert decision.outcome == ApprovalOutcome.REQUIRE_APPROVAL


def test_infer_aws_role_access_category() -> None:
    text = (
        "grant user access for test_user@newmathdata.com on aws project role "
        "arn:aws:iam::250623887600:role/NMD-Admin-Scaia"
    )
    category, resource = infer_category_and_resource(text)
    assert category == ApprovalCategory.AWS_ROLE_ACCESS
    assert resource == "arn:aws:iam::250623887600:role/NMD-Admin-Scaia"


def test_policy_requires_approval_for_aws_role_access() -> None:
    engine = PolicyEngine()
    action = ProposedAction(
        tool_name="iam_grant",
        description=(
            "grant user access for test_user@newmathdata.com on aws project role "
            "arn:aws:iam::250623887600:role/NMD-Admin-Scaia"
        ),
        category=ApprovalCategory.AWS_ROLE_ACCESS,
        resource="arn:aws:iam::250623887600:role/NMD-Admin-Scaia",
    )
    decision = engine.evaluate(action)
    assert decision.outcome == ApprovalOutcome.REQUIRE_APPROVAL

