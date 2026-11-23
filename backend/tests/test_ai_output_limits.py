from types import SimpleNamespace

from app.core.config import Settings
from app.services import ai_service


def test_ask_ai_applies_server_side_output_token_ceiling(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A concise answer"))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
            model="deepseek-flash",
            _hidden_params={"response_cost": "0.0001"},
        )

    monkeypatch.setattr(ai_service, "completion", fake_completion)
    settings = Settings(ai_provider="deepseek", ai_model="deepseek-flash",
                        deepseek_api_key="test-key", ai_max_output_tokens=1024)

    result = ai_service.ask_ai(settings, [{"role": "user", "content": "Hello"}])

    assert captured["max_tokens"] == 1024
    assert result.text == "A concise answer"
    assert result.total_tokens == 20


def test_ai_output_token_ceiling_has_safe_bounds():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(ai_max_output_tokens=128)
    with pytest.raises(ValidationError):
        Settings(ai_max_output_tokens=9000)
