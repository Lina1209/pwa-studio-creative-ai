import pytest
from fastapi import HTTPException

from app.services.asset_access import (
    canonical_owner_id,
    owner_filter,
    owner_scoped_params,
)


OWNER = "11111111-1111-4111-8111-111111111111"


def test_owner_id_is_canonicalized_from_verified_identity():
    assert canonical_owner_id(OWNER.upper()) == OWNER


def test_owner_filter_uses_authenticated_identity_only():
    assert owner_filter(OWNER) == {"owner_id": f"eq.{OWNER}"}


def test_extra_query_params_cannot_override_owner_scope():
    with pytest.raises(ValueError, match="authenticated principal"):
        owner_scoped_params(OWNER, extra={"owner_id": "eq.someone-else"})


def test_additional_filters_preserve_owner_scope():
    params = owner_scoped_params(OWNER, extra={"status": "eq.ready", "limit": "30"})
    assert params == {
        "status": "eq.ready",
        "limit": "30",
        "owner_id": f"eq.{OWNER}",
    }


@pytest.mark.parametrize("invalid", ["", "not-a-uuid", None])
def test_invalid_authenticated_identity_fails_closed(invalid):
    with pytest.raises(HTTPException) as exc:
        canonical_owner_id(invalid)
    assert exc.value.status_code == 401
