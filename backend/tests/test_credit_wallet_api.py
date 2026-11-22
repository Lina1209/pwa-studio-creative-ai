from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException, Response

from app import main
from app.services.credit_wallet_service import CreditWalletNotConfigured, CreditWalletUnavailable


USER_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_wallet_endpoint_returns_owner_scoped_no_store_snapshot(monkeypatch):
    monkeypatch.setattr(
        main, "get_credit_wallet_snapshot",
        lambda settings, user_id, history_limit: SimpleNamespace(
            user_id=user_id,
            available_credits=80,
            reserved_credits=20,
            holds=[{
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "job_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "amount": 20,
                "status": "held",
                "created_at": "2026-11-23T00:00:00Z",
            }],
            ledger=[],
        ),
    )
    response = Response()

    result = main.get_my_credit_wallet(
        response, main.StudioUser(str(USER_ID), None, "creator")
    )

    assert result["user_id"] == str(USER_ID)
    assert result["available_credits"] == 80
    assert result["reserved_credits"] == 20
    assert result["total_credits"] == 100
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    "failure,expected_status",
    [
        (CreditWalletNotConfigured("not configured"), 503),
        (CreditWalletUnavailable("unavailable"), 503),
    ],
)
def test_wallet_endpoint_fails_closed_when_storage_is_unavailable(
    monkeypatch, failure, expected_status
):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(main, "get_credit_wallet_snapshot", fail)

    with pytest.raises(HTTPException) as error:
        main.get_my_credit_wallet(
            Response(), main.StudioUser(str(USER_ID), None, "creator")
        )

    assert error.value.status_code == expected_status
