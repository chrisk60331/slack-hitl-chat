"""Policy models and evaluator for deciding if actions require approval.

This module defines:
- ApprovalCategory: semantic categories for actions
- ApprovalDecision: enumeration of decision outcomes
- ProposedAction: structured description of a tool/action request
- PolicyRule: rule definition supporting deterministic gating
- PolicyEngine: loads rules and evaluates ProposedAction to an ApprovalDecision

Design goals:
- Do not alter existing HITL workflow; only decide allow/approval/deny
- Keep rule evaluation deterministic and auditable
- Allow external policy file via POLICY_PATH environment variable
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field


class ApprovalCategory(str, Enum):
    """Semantic categories for actions that may require approval."""

    USER_ACCOUNT_ACCESS = "user_account_access"
    AWS_ROLE_ACCESS = "aws_role_access"
    DOCUMENT_ACCESS_UPDATES = "document_access_updates"
    DOCUMENT_CONTENT_UPDATES = "document_content_updates"
    OTHER = "other"

    @property
    def risk_default(self) -> int:
        """Default risk weight for the category (1-10)."""

        risk_map: dict[ApprovalCategory, int] = {
            ApprovalCategory.USER_ACCOUNT_ACCESS: 10,
            ApprovalCategory.AWS_ROLE_ACCESS: 8,
            ApprovalCategory.DOCUMENT_ACCESS_UPDATES: 10,
            ApprovalCategory.DOCUMENT_CONTENT_UPDATES: 5,
            ApprovalCategory.OTHER: 3,
        }
        return risk_map[self]


class ApprovalOutcome(str, Enum):
    """Decision outcomes for proposed actions."""

    ALLOW: str = "Approved"
    REQUIRE_APPROVAL: str = "Approval Required"
    DENY: str = "Denied"


class ProposedAction(BaseModel):
    """Structured description of a user/tool action to be executed."""

    tool_name: str = Field(
        ..., description="The name of the tool or operation"
    )
    description: str = Field(
        ..., description="Human-readable description of the intended action"
    )
    category: ApprovalCategory = Field(default=ApprovalCategory.OTHER)
    resource: str | None = Field(
        default=None, description="Target resource identifier (ARN, URL, path)"
    )
    amount: float | None = Field(
        default=None,
        description="Monetary amount or numeric threshold relevant to the action",
    )
    environment: str = Field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "dev")
    )
    user_id: str | None = Field(default=None)
    group_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyRule(BaseModel):
    """Deterministic policy rule definition."""

    name: str
    categories: list[ApprovalCategory] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    resource_prefixes: list[str] = Field(default_factory=list)
    min_amount: float | None = None
    max_amount: float | None = None
    require_approval: bool = True
    deny: bool = False

    def matches(self, action: ProposedAction) -> bool:
        """Return True if this rule applies to the given action."""

        if self.categories and action.category not in self.categories:
            return False
        if self.environments and action.environment not in self.environments:
            return False
        if self.resource_prefixes and action.resource is not None:
            if not any(
                action.resource.startswith(p) for p in self.resource_prefixes
            ):
                return False
        if (
            self.min_amount is not None
            and (action.amount or 0) < self.min_amount
        ):
            return False
        if (
            self.max_amount is not None
            and (action.amount or 0) > self.max_amount
        ):
            return False
        return True


class PolicyDecision(BaseModel):
    """Result of evaluating a ProposedAction against policy rules."""

    outcome: ApprovalOutcome
    matched_rule: str | None = None
    rationale: str = ""


@dataclass(slots=True)
class _RawPolicy:
    rules: list[PolicyRule]


DEFAULT_RULES: list[PolicyRule] = [
    PolicyRule(
        name="require_approval_for_aws_role_access",
        categories=[ApprovalCategory.AWS_ROLE_ACCESS],
        require_approval=True,
    ),
    PolicyRule(
        name="require_approval_for_user_google_account_maintenance",
        categories=[ApprovalCategory.USER_ACCOUNT_ACCESS],
        require_approval=True,
    ),
    PolicyRule(
        name="require_approval_for_document_access_updates",
        categories=[ApprovalCategory.DOCUMENT_ACCESS_UPDATES],
        require_approval=True,
    ),
]


class PolicyEngine:
    """Policy evaluator that decides whether an action may proceed.

    Loads rules from POLICY_PATH if provided; otherwise uses DEFAULT_RULES.
    """

    def __init__(self, policy_path: str | None = None) -> None:
        self._policy_path = policy_path or os.getenv("POLICY_PATH")

    @lru_cache(maxsize=1)
    def _load_rules(self) -> _RawPolicy:
        if self._policy_path and os.path.exists(self._policy_path):
            with open(self._policy_path, encoding="utf-8") as f:
                data = json.load(f)
            rules = [PolicyRule(**r) for r in data.get("rules", [])]
            return _RawPolicy(rules=rules)
        return _RawPolicy(rules=list(DEFAULT_RULES))

    def evaluate(self, action: ProposedAction) -> PolicyDecision:
        """Evaluate a ProposedAction to an ApprovalOutcome.

        Rule precedence:
        - First matching rule with deny=True → DENY
        - First matching rule with require_approval=True → REQUIRE_APPROVAL
        - Otherwise → ALLOW
        """

        rules = self._load_rules().rules
        print(f"rules {rules}\n\n")
        print(f"action {action}\n\n")
        for rule in rules:
            if rule.matches(action):
                if rule.deny:
                    return PolicyDecision(
                        outcome=ApprovalOutcome.DENY,
                        matched_rule=rule.name,
                        rationale="Denied by policy rule",
                    )
                if rule.require_approval:
                    return PolicyDecision(
                        outcome=ApprovalOutcome.REQUIRE_APPROVAL,
                        matched_rule=rule.name,
                        rationale="Approval required by policy rule",
                    )

        return PolicyDecision(
            outcome=ApprovalOutcome.ALLOW,
            matched_rule=None,
            rationale="No matching rule requires gating; allowed by default",
        )


# Compiled regex to detect AWS IAM Role ARNs in free-form text
_AWS_ROLE_ARN_REGEX = re.compile(
    r"arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_/-]+"
)


def infer_category_and_resource(
    description: str,
) -> tuple[ApprovalCategory, str | None]:
    """Infer an approval category and target resource from a natural language description.

    - Detects AWS IAM Role ARNs and returns (AWS_ROLE_ACCESS, role_arn)
    - Defaults to (OTHER, None) when no pattern is recognized

    Args:
        description: Free-form action description

    Returns:
        Tuple of (ApprovalCategory, resource string or None)
    """
    match = _AWS_ROLE_ARN_REGEX.search(description or "")
    if match:
        return (ApprovalCategory.AWS_ROLE_ACCESS, match.group(0))
    return (ApprovalCategory.OTHER, None)
