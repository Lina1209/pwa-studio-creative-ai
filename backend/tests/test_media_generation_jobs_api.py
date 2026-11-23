
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import app
from app.services.auth import StudioUser, get_current_user
import app.main as main_module


def _user():
    return StudioUser(user_id="11111111-1111-4111-8111-111111111111",
                      email="creator@example.test", role="creator")


def _settings(**overrides):
    values = dict(generation_jobs_enabled=True, generation_job_worker_ready=True)
    values.update(overrides)
    return Settings(**values)


def test_video_job_fails_closed_without_provider(monkeypatch):
    monkeypatch.setattr(main_module, "settings", _settings())
    app.dependency_overrides[get_current_user] = _user
    try:
        response = TestClient(app).post(
            "/api/projects/22222222-2222-4222-8222-222222222222/video-jobs",
            headers={"Idempotency-Key": "video-job-test-001"},
            json={"prompt": "A mountain sunrise", "duration_seconds": 30,
                  "resolution": "720p", "quote_snapshot": {"placeholder": True}},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 503
    assert "provider and model are not configured" in response.json()["detail"]


def test_audio_job_requires_signed_quote(monkeypatch):
    monkeypatch.setattr(main_module, "settings", _settings(
        audio_generation_provider="provider-x", audio_generation_model="model-y"))
    app.dependency_overrides[get_current_user] = _user
    try:
        response = TestClient(app).post(
            "/api/projects/22222222-2222-4222-8222-222222222222/audio-jobs",
            headers={"Idempotency-Key": "audio-job-test-001"},
            json={"prompt": "Gentle cinematic ambient music", "duration_seconds": 45},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 422
    assert "server-issued pricing quote" in response.json()["detail"]


def test_speech_job_uses_atomic_admission_and_exact_request(monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID
    captured = {}

    def admit(settings, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            job_id=UUID("33333333-3333-4333-8333-333333333333"),
            event_id=UUID("44444444-4444-4444-8444-444444444444"),
            hold_id=UUID("55555555-5555-4555-8555-555555555555"),
            available_credits=90, reserved_credits=10, created=True, replayed=False,
            quota_reservations=(),
        )

    monkeypatch.setattr(main_module, "settings", _settings(
        speech_generation_provider="provider-x", speech_generation_model="voice-model"))
    monkeypatch.setattr(main_module, "create_plan_credited_generation_job", admit)
    app.dependency_overrides[get_current_user] = _user
    try:
        response = TestClient(app).post(
            "/api/projects/22222222-2222-4222-8222-222222222222/speech-jobs",
            headers={"Idempotency-Key": "speech-job-test-001"},
            json={"text": "Добро пожаловать в нашу студию", "voice": "neutral",
                  "language": "ru", "quote_snapshot": {"signed": "quote"}},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 202
    assert captured["user_id"] == UUID("11111111-1111-4111-8111-111111111111")
    assert captured["job_type"] == "speech_generation"
    assert captured["request_snapshot"]["text"] == "Добро пожаловать в нашу студию"
    assert captured["quote_snapshot"] == {"signed": "quote"}


def test_cancel_generation_job_uses_verified_owner_and_returns_handshake_state(monkeypatch):
    from types import SimpleNamespace
    from uuid import UUID

    captured = {}

    def request_cancel(settings, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            job_status="cancel_requested",
            cancellation_action="awaiting_worker_confirmation",
            replayed=False,
        )

    job_id = UUID("66666666-6666-4666-8666-666666666666")
    monkeypatch.setattr(main_module, "settings", _settings())
    monkeypatch.setattr(main_module, "request_generation_job_cancellation", request_cancel)
    app.dependency_overrides[get_current_user] = _user
    try:
        response = TestClient(app).post(f"/api/jobs/{job_id}/cancel")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json() == {
        "job_id": str(job_id),
        "status": "cancel_requested",
        "cancellation_action": "awaiting_worker_confirmation",
        "replayed": False,
    }
    assert captured["user_id"] == UUID("11111111-1111-4111-8111-111111111111")
    assert captured["job_id"] == job_id


def test_cancel_generation_job_hides_other_owner_jobs(monkeypatch):
    from fastapi import HTTPException
    from app.services.generation_jobs import GenerationJobNotFoundError

    def not_found(settings, **kwargs):
        raise GenerationJobNotFoundError("not found")

    monkeypatch.setattr(main_module, "settings", _settings())
    monkeypatch.setattr(main_module, "request_generation_job_cancellation", not_found)
    app.dependency_overrides[get_current_user] = _user
    try:
        response = TestClient(app).post(
            "/api/jobs/66666666-6666-4666-8666-666666666666/cancel"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 404
    assert response.json()["detail"] == "Generation job was not found."


def test_cancel_generation_job_fails_closed_when_jobs_disabled(monkeypatch):
    def unexpected_cancel(*args, **kwargs):
        raise AssertionError("Cancellation service must not be called while jobs are disabled")

    monkeypatch.setattr(main_module, "settings", _settings(generation_jobs_enabled=False))
    monkeypatch.setattr(main_module, "request_generation_job_cancellation", unexpected_cancel)
    app.dependency_overrides[get_current_user] = _user
    try:
        response = TestClient(app).post(
            "/api/jobs/66666666-6666-4666-8666-666666666666/cancel"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 503
