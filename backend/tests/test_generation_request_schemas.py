import pytest
from pydantic import ValidationError

from app.schemas import ChatRequest, PromptRequest


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (ChatRequest, {"message": "hello", "provider": "other-provider"}),
        (ChatRequest, {"message": "hello", "user_id": "another-account"}),
        (ChatRequest, {"message": "hello", "credits": 0}),
        (PromptRequest, {"idea": "a quiet forest", "model": "other-model"}),
        (PromptRequest, {"idea": "a quiet forest", "user_id": "another-account"}),
        (PromptRequest, {"idea": "a quiet forest", "price": 0}),
    ],
)
def test_generation_schemas_reject_unrecognized_control_fields(schema, payload):
    with pytest.raises(ValidationError):
        schema.model_validate(payload)


def test_generation_schemas_accept_supported_fields_only():
    assert ChatRequest.model_validate({"message": "hello"}).message == "hello"
    prompt = PromptRequest.model_validate({
        "idea": "a quiet forest",
        "purpose": "video",
        "language": "Russian",
        "style": "cinematic",
    })
    assert prompt.idea == "a quiet forest"
