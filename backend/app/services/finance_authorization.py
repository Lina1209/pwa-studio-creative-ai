"""Fail-closed policy primitives for future delegated finance workflows.

This module is intentionally not wired to public mutation endpoints. Callers must
obtain grants from a trusted server-side registry; never accept grants from a
browser request or infer them from the owner role.
"""
from dataclasses import dataclass, field
from uuid import UUID


class FinanceAuthorizationDenied(PermissionError):
    """A finance action failed a server-side permission or separation-of-duties check."""


FINANCE_PERMISSIONS = frozenset({
    "credit.compensation.read",
    "credit.compensation.request",
    "credit.compensation.approve",
    "credit.compensation.execute",
    "credit.compensation.cancel",
    "billing.refund.read",
    "billing.refund.request",
    "billing.refund.approve",
    "billing.refund.execute",
    "billing.refund.cancel",
    "finance.audit.read",
    "finance.reconciliation.read",
    "finance.policy.manage",
})


@dataclass(frozen=True)
class FinanceGrant:
    """Trusted server-resolved grant snapshot; not constructible from client input."""

    principal_id: UUID
    permissions: frozenset[str]
    active: bool
    scope_ids: frozenset[str] = frozenset()
    permission_scopes: dict[str, frozenset[str]] = field(default_factory=dict)
    global_permissions: frozenset[str] = frozenset()


def require_finance_permission(
    grant: FinanceGrant | None,
    *,
    actor_id: UUID,
    permission: str,
    target_scope: str | None = None,
) -> None:
    """Require a current, explicit grant and optional exact scope membership."""
    if permission not in FINANCE_PERMISSIONS:
        raise FinanceAuthorizationDenied("Unknown finance permission.")
    if grant is None or not grant.active or grant.principal_id != actor_id:
        raise FinanceAuthorizationDenied("No active finance assignment.")
    if permission not in grant.permissions:
        raise FinanceAuthorizationDenied("Required finance permission is not granted.")
    if target_scope is not None:
        if permission in grant.global_permissions:
            return
        allowed_scopes = grant.permission_scopes.get(permission, grant.scope_ids)
        if target_scope not in allowed_scopes:
            raise FinanceAuthorizationDenied("Finance assignment does not cover this scope.")


def require_independent_approval(*, requester_id: UUID, approver_id: UUID) -> None:
    """The requester can never approve their own credit compensation or refund."""
    if requester_id == approver_id:
        raise FinanceAuthorizationDenied("Self-approval is prohibited.")


def require_independent_execution(
    *,
    requester_id: UUID,
    approver_id: UUID,
    executor_id: UUID,
    high_risk: bool = True,
) -> None:
    """For high-risk actions, requester, approver, and executor are distinct."""
    require_independent_approval(requester_id=requester_id, approver_id=approver_id)
    if high_risk and (executor_id == requester_id or executor_id == approver_id):
        raise FinanceAuthorizationDenied(
            "High-risk execution requires an identity independent of requester and approver."
        )
