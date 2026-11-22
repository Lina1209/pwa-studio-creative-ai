from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import main
from app.services.ai_admission import AIAdmissionRejected, AIAdmissionUnavailable


def test_admitted_ai_request_is_finalized_as_completed(monkeypatch):
    reservation = SimpleNamespace(request_id=uuid4(), user_id=uuid4())
    finished = []
    monkeypatch.setattr(main, "reserve_ai_request", lambda *args, **kwargs: reservation)
    monkeypatch.setattr(
        main, "finish_ai_request",
        lambda settings, value, completed: finished.append((value, completed)),
    )
    monkeypatch.setattr(main, "_run_ai", lambda operation, call: call())

    result = main._run_admitted_ai("chat", str(reservation.user_id), lambda: "answer")

    assert result == "answer"
    assert finished == [(reservation, True)]


def test_failed_provider_request_releases_admission_reservation(monkeypatch):
    reservation = SimpleNamespace(request_id=uuid4(), user_id=uuid4())
    finished = []
    monkeypatch.setattr(main, "reserve_ai_request", lambda *args, **kwargs: reservation)
    monkeypatch.setattr(
        main, "finish_ai_request",
        lambda settings, value, completed: finished.append((value, completed)),
    )

    def fail(operation, call):
        raise HTTPException(status_code=502, detail="provider failed")

    monkeypatch.setattr(main, "_run_ai", fail)
    with pytest.raises(HTTPException) as error:
        main._run_admitted_ai("prompts", str(reservation.user_id), lambda: None)

    assert error.value.status_code == 502
    assert finished == [(reservation, False)]


def test_rejected_admission_never_calls_ai_provider(monkeypatch):
    called = []
    monkeypatch.setattr(
        main, "reserve_ai_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AIAdmissionRejected("rate_limited", 60)
        ),
    )
    monkeypatch.setattr(main, "_run_ai", lambda *args: called.append(True))

    with pytest.raises(HTTPException) as error:
        main._run_admitted_ai("chat", str(uuid4()), lambda: None)

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "60"
    assert called == []


def test_admission_store_failure_fails_closed_without_ai_call(monkeypatch):
    called = []
    monkeypatch.setattr(
        main, "reserve_ai_request",
        lambda *args, **kwargs: (_ for _ in ()).throw(AIAdmissionUnavailable()),
    )
    monkeypatch.setattr(main, "_run_ai", lambda *args: called.append(True))

    with pytest.raises(HTTPException) as error:
        main._run_admitted_ai("chat", str(uuid4()), lambda: None)

    assert error.value.status_code == 503
    assert called == []
