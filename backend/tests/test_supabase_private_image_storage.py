from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.services.generation_result_storage import GenerationResultStorageError, calculate_sha256
from app.services.supabase_private_image_storage import (
    SupabasePrivateImageStorage,
    SupabaseStorageAdapterError,
    SupabaseStorageNotConfiguredError,
)


OWNER = UUID("11111111-1111-4111-8111-111111111111")
JOB = UUID("22222222-2222-4222-8222-222222222222")
PNG = b"\x89PNG\r\n\x1a\nprivate-storage-test"


def make_settings(**overrides):
    values = {
        "supabase_url": "https://project.supabase.co",
        "supabase_service_role_key": "sb_secret_server_only",
        "generation_storage_bucket": "studio-media",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_upload_verifies_private_bucket_object_metadata_and_downloaded_bytes():
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            assert request.content == PNG
            assert request.headers["content-type"] == "image/png"
            assert request.headers["x-upsert"] == "false"
            return httpx.Response(200, json={"Key": f"studio-media/{OWNER}/generated/{JOB}.png"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"id": "studio-media", "public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        uploaded = await storage.upload_image(
            owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
        )

    assert uploaded.metadata.is_private is True
    assert uploaded.metadata.object_path == f"{OWNER}/generated/{JOB}.png"
    assert uploaded.metadata.sha256_hex == calculate_sha256(PNG)
    assert len(seen) == 4
    assert all("authorization" not in req.headers for req in seen)
    assert all(req.headers["apikey"] == "sb_secret_server_only" for req in seen)


@pytest.mark.asyncio
async def test_transient_verification_failure_preserves_uploaded_object_for_retry():
    calls = []
    bucket_reads = 0

    def handler(request):
        nonlocal bucket_reads
        calls.append((request.method, request.url.path))
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            if sum(1 for method, path in calls
                   if method == "POST" and "/object/studio-media/" in path) == 1:
                return httpx.Response(200, json={"Key": "uploaded"})
            return httpx.Response(409, json={"message": "already exists"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            bucket_reads += 1
            if bucket_reads == 1:
                return httpx.Response(503, json={"message": "temporarily unavailable"})
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG)
        if request.method == "DELETE":
            raise AssertionError("Transient verification failure must not delete the object")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(SupabaseStorageAdapterError) as exc_info:
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )
        assert exc_info.value.retryable is True

        uploaded = await storage.upload_image(
            owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
        )

    assert uploaded.metadata.sha256_hex == calculate_sha256(PNG)
    assert bucket_reads == 2
    assert not any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_retry_after_ambiguous_upload_verifies_existing_object_without_overwrite():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            assert request.headers["x-upsert"] == "false"
            return httpx.Response(409, json={"message": "already exists"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        uploaded = await storage.upload_image(
            owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
        )

    assert uploaded.metadata.sha256_hex == calculate_sha256(PNG)
    assert [method for method, _ in calls].count("POST") == 2
    assert not any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_mismatched_preexisting_object_is_not_deleted_on_retry():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(409, json={"message": "already exists"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG + b"unexpected")
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(GenerationResultStorageError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )

    assert not any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_public_bucket_is_rejected_and_uploaded_object_cleanup_attempted():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": True})
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(GenerationResultStorageError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )
    assert any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_storage_byte_mismatch_is_rejected_and_cleaned_up():
    def handler(request):
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG + b"tampered")
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(GenerationResultStorageError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )


@pytest.mark.asyncio
async def test_missing_object_metadata_is_not_treated_as_success():
    def handler(request):
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[])
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(SupabaseStorageAdapterError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )


def test_storage_adapter_fails_closed_without_service_key():
    with pytest.raises(SupabaseStorageNotConfiguredError):
        SupabasePrivateImageStorage(
            Settings(supabase_url="https://project.supabase.co"),
            httpx.AsyncClient(),
        )


@pytest.mark.asyncio
async def test_legacy_jwt_service_key_is_sent_as_bearer():
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG)
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(
            make_settings(supabase_service_role_key="eyJlegacy.jwt.key"), client
        )
        await storage.upload_image(
            owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
        )
    assert all(req.headers["authorization"] == "Bearer eyJlegacy.jwt.key" for req in seen)


@pytest.mark.asyncio
async def test_storage_download_size_limit_is_enforced_before_buffer_growth():
    oversized = PNG + (b"x" * (20 * 1024 * 1024 + 1))

    def handler(request):
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=oversized)
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(GenerationResultStorageError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )


@pytest.mark.asyncio
async def test_boolean_size_metadata_is_rejected_as_invalid():
    def handler(request):
        if request.method == "POST" and "/object/studio-media/" in request.url.path:
            return httpx.Response(200, json={"Key": "uploaded"})
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": True, "mimetype": "image/png"},
            }])
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "deleted"})
        raise AssertionError("Unexpected request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(SupabaseStorageAdapterError):
            await storage.upload_image(
                owner_id=OWNER, job_id=JOB, image_bytes=PNG, mime_type="image/png"
            )


@pytest.mark.asyncio
async def test_existing_result_verification_checks_private_metadata_and_hashes_bytes():
    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": len(PNG), "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        verified = await storage.verify_existing_image(
            owner_id=OWNER, job_id=JOB, object_path=f"{OWNER}/generated/{JOB}.png"
        )
    assert verified.is_private is True
    assert verified.content_type == "image/png"
    assert verified.size_bytes == len(PNG)
    assert verified.sha256_hex == calculate_sha256(PNG)


@pytest.mark.asyncio
async def test_existing_result_verification_rejects_foreign_or_mismatched_path_before_io():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(AssertionError("No request expected"))
    )) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(GenerationResultStorageError):
            await storage.verify_existing_image(
                owner_id=OWNER, job_id=JOB,
                object_path=f"{UUID(int=9)}/generated/{JOB}.png",
            )
        with pytest.raises(GenerationResultStorageError):
            await storage.verify_existing_image(
                owner_id=OWNER, job_id=JOB,
                object_path=f"{OWNER}/generated/{UUID(int=8)}.png",
            )


@pytest.mark.asyncio
async def test_existing_result_verification_rejects_corrupt_size_and_public_bucket():
    mode = {"public": False, "size": len(PNG)}

    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": mode["public"]})
        if request.method == "POST" and request.url.path.endswith("/object/list/studio-media"):
            return httpx.Response(200, json=[{
                "name": f"{JOB}.png",
                "metadata": {"size": mode["size"], "mimetype": "image/png"},
            }])
        if request.method == "GET" and "/object/authenticated/" in request.url.path:
            return httpx.Response(200, content=PNG)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        mode["size"] = len(PNG) + 1
        with pytest.raises(GenerationResultStorageError):
            await storage.verify_existing_image(
                owner_id=OWNER, job_id=JOB, object_path=f"{OWNER}/generated/{JOB}.png"
            )
        mode["public"] = True
        mode["size"] = len(PNG)
        with pytest.raises(GenerationResultStorageError):
            await storage.verify_existing_image(
                owner_id=OWNER, job_id=JOB, object_path=f"{OWNER}/generated/{JOB}.png"
            )


@pytest.mark.asyncio
async def test_owner_inventory_paginates_and_returns_only_relative_names():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        payload = request.read()
        import json
        body = json.loads(payload)
        if body["offset"] == 0:
            return httpx.Response(200, json=[{
                "name": "one.png",
                "created_at": "2026-11-01T00:00:00+00:00",
                "metadata": {"size": 100, "mimetype": "image/png"},
            }])
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        objects = await storage.list_owner_generated_objects(
            owner_id=OWNER, page_size=1, max_pages=3
        )
    assert len(objects) == 1
    assert objects[0].object_path == f"{OWNER}/generated/one.png"
    assert len(requests) == 3  # bucket privacy preflight plus two inventory pages


@pytest.mark.asyncio
async def test_owner_inventory_fails_closed_when_page_limit_is_reached():
    def handler(request):
        if request.method == "GET" and request.url.path.endswith("/bucket/studio-media"):
            return httpx.Response(200, json={"public": False})
        return httpx.Response(200, json=[{
            "name": "one.png",
            "created_at": "2026-11-01T00:00:00+00:00",
            "metadata": {"size": 100, "mimetype": "image/png"},
        }])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        storage = SupabasePrivateImageStorage(make_settings(), client)
        with pytest.raises(SupabaseStorageAdapterError):
            await storage.list_owner_generated_objects(
                owner_id=OWNER, page_size=1, max_pages=1
            )
