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
from dataclasses import dataclass
import re
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApprovalCategory(str, Enum):
    """Semantic categories for actions that may require approval."""

    DATA_EXFILTRATION = "data_exfiltration"
    FINANCIAL = "financial"
    PRIVILEGED_WRITE = "privileged_write"
    EXTERNAL_API_CALL = "external_api_call"
    USER_DATA_ACCESS = "user_data_access"
    AWS_ROLE_ACCESS = "aws_role_access"
    OTHER = "other"

    @property
    def risk_default(self) -> int:
        """Default risk weight for the category (1-10)."""

        risk_map: Dict[ApprovalCategory, int] = {
            ApprovalCategory.DATA_EXFILTRATION: 9,
            ApprovalCategory.FINANCIAL: 8,
            ApprovalCategory.PRIVILEGED_WRITE: 7,
            ApprovalCategory.EXTERNAL_API_CALL: 5,
            ApprovalCategory.USER_DATA_ACCESS: 6,
            ApprovalCategory.AWS_ROLE_ACCESS: 8,
            ApprovalCategory.OTHER: 3,
        }
        return risk_map[self]


class ApprovalOutcome(str, Enum):
    """Decision outcomes for proposed actions."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ProposedAction(BaseModel):
    """Structured description of a user/tool action to be executed."""

    tool_name: str = Field(..., description="The name of the tool or operation")
    description: str = Field(..., description="Human-readable description of the intended action")
    category: ApprovalCategory = Field(default=ApprovalCategory.OTHER)
    resource: Optional[str] = Field(
        default=None, description="Target resource identifier (ARN, URL, path)"
    )
    amount: Optional[float] = Field(
        default=None, description="Monetary amount or numeric threshold relevant to the action"
    )
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "dev"))
    user_id: Optional[str] = Field(default=None)
    group_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PolicyRule(BaseModel):
    """Deterministic policy rule definition."""

    name: str
    categories: List[ApprovalCategory] = Field(default_factory=list)
    environments: List[str] = Field(default_factory=list)
    resource_prefixes: List[str] = Field(default_factory=list)
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    require_approval: bool = True
    deny: bool = False

    def matches(self, action: ProposedAction) -> bool:
        """Return True if this rule applies to the given action."""

        if self.categories and action.category not in self.categories:
            return False
        if self.environments and action.environment not in self.environments:
            return False
        if self.resource_prefixes and action.resource is not None:
            if not any(action.resource.startswith(p) for p in self.resource_prefixes):
                return False
        if self.min_amount is not None and (action.amount or 0) < self.min_amount:
            return False
        if self.max_amount is not None and (action.amount or 0) > self.max_amount:
            return False
        return True


class PolicyDecision(BaseModel):
    """Result of evaluating a ProposedAction against policy rules."""

    outcome: ApprovalOutcome
    matched_rule: Optional[str] = None
    rationale: str = ""


@dataclass(slots=True)
class _RawPolicy:
    rules: List[PolicyRule]


DEFAULT_RULES: List[PolicyRule] = [
    PolicyRule(
        name="deny_prod_exfiltration",
        categories=[ApprovalCategory.DATA_EXFILTRATION],
        environments=["prod", "production"],
        deny=True,
    ),
    PolicyRule(
        name="require_approval_for_aws_role_access",
        categories=[ApprovalCategory.AWS_ROLE_ACCESS],
        require_approval=True,
    ),
    PolicyRule(
        name="approve_required_privileged_writes",
        categories=[ApprovalCategory.PRIVILEGED_WRITE],
        require_approval=True,
    ),
    PolicyRule(
        name="financial_threshold_approval",
        categories=[ApprovalCategory.FINANCIAL],
        min_amount=100.0,
        require_approval=True,
    ),
]


class PolicyEngine:
    """Policy evaluator that decides whether an action may proceed.

    Loads rules from POLICY_PATH if provided; otherwise uses DEFAULT_RULES.
    """

    def __init__(self, policy_path: Optional[str] = None) -> None:
        self._policy_path = policy_path or os.getenv("POLICY_PATH")

    @lru_cache(maxsize=1)
    def _load_rules(self) -> _RawPolicy:
        if self._policy_path and os.path.exists(self._policy_path):
            with open(self._policy_path, "r", encoding="utf-8") as f:
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
_AWS_ROLE_ARN_REGEX = re.compile(r"arn:aws:iam::\d{12}:role/[A-Za-z0-9+=,.@_/-]+")


def infer_category_and_resource(description: str) -> tuple[ApprovalCategory, Optional[str]]:
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

