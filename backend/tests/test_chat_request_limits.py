import pytest
from pydantic import ValidationError

from app.schemas import ChatRequest


def test_chat_request_accepts_context_within_total_character_budget():
    payload = ChatRequest(
        message="current question",
        history=[
            {"role": "user", "content": "a" * 12000},
            {"role": "assistant", "content": "b" * 11900},
        ],
    )

    assert len(payload.message) + sum(len(turn.content) for turn in payload.history) <= 24000


def test_chat_request_rejects_context_over_total_character_budget():
    with pytest.raises(ValidationError, match="complete chat context"):
        ChatRequest(
            message="c" * 12000,
            history=[
                {"role": "user", "content": "a" * 12000},
                {"role": "assistant", "content": "b" * 1},
            ],
        )


def test_chat_request_keeps_existing_per_turn_limit():
    with pytest.raises(ValidationError):
        ChatRequest(message="x", history=[{"role": "user", "content": "a" * 12001}])
