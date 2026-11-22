from uuid import UUID

import pytest

from app.services.finance_authorization import (
    FinanceAuthorizationDenied,
    FinanceGrant,
    require_finance_permission,
    require_independent_approval,
    require_independent_execution,
)


ACTOR = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")
THIRD = UUID("33333333-3333-4333-8333-333333333333")


def test_finance_permission_requires_active_explicit_server_grant():
    grant = FinanceGrant(ACTOR, frozenset({"credit.compensation.request"}), True, frozenset({"tenant-a"}))
    require_finance_permission(
        grant, actor_id=ACTOR, permission="credit.compensation.request", target_scope="tenant-a"
    )
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(
            grant, actor_id=ACTOR, permission="credit.compensation.approve", target_scope="tenant-a"
        )


def test_owner_or_other_identity_does_not_inherit_grants():
    grant = FinanceGrant(ACTOR, frozenset({"credit.compensation.request"}), True)
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(
            grant, actor_id=OTHER, permission="credit.compensation.request"
        )


def test_inactive_or_missing_grant_fails_closed():
    inactive = FinanceGrant(ACTOR, frozenset({"credit.compensation.request"}), False)
    for grant in (None, inactive):
        with pytest.raises(FinanceAuthorizationDenied):
            require_finance_permission(
                grant, actor_id=ACTOR, permission="credit.compensation.request"
            )


def test_scope_mismatch_and_unknown_permission_fail_closed():
    grant = FinanceGrant(ACTOR, frozenset({"credit.compensation.request"}), True, frozenset({"tenant-a"}))
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(
            grant, actor_id=ACTOR, permission="credit.compensation.request", target_scope="tenant-b"
        )
    with pytest.raises(FinanceAuthorizationDenied):
        require_finance_permission(grant, actor_id=ACTOR, permission="admin.superuser")


def test_self_approval_is_always_rejected():
    with pytest.raises(FinanceAuthorizationDenied):
        require_independent_approval(requester_id=ACTOR, approver_id=ACTOR)
    require_independent_approval(requester_id=ACTOR, approver_id=OTHER)


def test_high_risk_executor_must_be_distinct_from_both_other_actors():
    require_independent_execution(
        requester_id=ACTOR, approver_id=OTHER, executor_id=THIRD, high_risk=True
    )
    for executor in (ACTOR, OTHER):
        with pytest.raises(FinanceAuthorizationDenied):
            require_independent_execution(
                requester_id=ACTOR, approver_id=OTHER, executor_id=executor, high_risk=True
            )


def test_low_risk_execution_still_disallows_self_approval():
    with pytest.raises(FinanceAuthorizationDenied):
        require_independent_execution(
            requester_id=ACTOR, approver_id=ACTOR, executor_id=THIRD, high_risk=False
        )
