from uuid import UUID

import pytest

from app.services.generation_result_storage import (
    GenerationResultStorageError,
    StoredObjectMetadata,
    calculate_sha256,
    validate_generation_result_object,
)


OWNER = UUID("11111111-1111-4111-8111-111111111111")
BUCKET = "studio-media"
PATH = f"{OWNER}/generated/scene-1.png"
PAYLOAD = b"\x89PNG\r\n\x1a\nverified-test-payload"
DIGEST = calculate_sha256(PAYLOAD)


def metadata(**overrides):
    values = {
        "bucket": BUCKET,
        "object_path": PATH,
        "is_private": True,
        "content_type": "image/png",
        "size_bytes": len(PAYLOAD),
        "sha256_hex": DIGEST,
    }
    values.update(overrides)
    return StoredObjectMetadata(**values)


def test_valid_private_owner_scoped_object_is_accepted():
    result = validate_generation_result_object(
        owner_id=OWNER,
        expected_bucket=BUCKET,
        expected_object_path=PATH,
        expected_sha256_hex=DIGEST,
        metadata=metadata(),
    )
    assert result.bucket == BUCKET
    assert result.object_path == PATH
    assert result.content_type == "image/png"
    assert result.sha256_hex == DIGEST


@pytest.mark.parametrize(
    ("changes", "error_code"),
    [
        ({"bucket": "other-bucket"}, "object_bucket_mismatch"),
        ({"object_path": f"{UUID(int=2)}/generated/scene.png"}, "object_path_mismatch"),
        ({"is_private": False}, "object_bucket_must_be_private"),
        ({"content_type": "image/svg+xml"}, "object_mime_not_allowed"),
        ({"size_bytes": 0}, "object_size_out_of_range"),
        ({"sha256_hex": "0" * 64}, "object_checksum_mismatch"),
    ],
)
def test_untrusted_or_invalid_storage_metadata_is_rejected(changes, error_code):
    with pytest.raises(GenerationResultStorageError) as exc:
        validate_generation_result_object(
            owner_id=OWNER,
            expected_bucket=BUCKET,
            expected_object_path=PATH,
            expected_sha256_hex=DIGEST,
            metadata=metadata(**changes),
        )
    assert exc.value.error_code == error_code


@pytest.mark.parametrize(
    "path",
    [
        "../other-user/file.png",
        f"{OWNER}/../other-user/file.png",
        f"/{OWNER}/file.png",
        f"{OWNER}//file.png",
        f"{UUID(int=2)}/file.png",
        f"{OWNER}\\\\other-user\\\\file.png",
    ],
)
def test_unsafe_or_cross_owner_paths_are_rejected(path):
    with pytest.raises(GenerationResultStorageError):
        validate_generation_result_object(
            owner_id=OWNER,
            expected_bucket=BUCKET,
            expected_object_path=path,
            expected_sha256_hex=DIGEST,
            metadata=metadata(object_path=path),
        )


def test_metadata_must_match_exact_expected_path():
    with pytest.raises(GenerationResultStorageError) as exc:
        validate_generation_result_object(
            owner_id=OWNER,
            expected_bucket=BUCKET,
            expected_object_path=PATH,
            expected_sha256_hex=DIGEST,
            metadata=metadata(object_path=f"{OWNER}/generated/other.png"),
        )
    assert exc.value.error_code == "object_path_mismatch"


def test_checksum_input_is_validated():
    with pytest.raises(GenerationResultStorageError):
        validate_generation_result_object(
            owner_id=OWNER,
            expected_bucket=BUCKET,
            expected_object_path=PATH,
            expected_sha256_hex="not-a-checksum",
            metadata=metadata(),
        )


def test_payload_digest_is_deterministic_and_rejects_empty_payload():
    assert calculate_sha256(PAYLOAD) == DIGEST
    with pytest.raises(GenerationResultStorageError):
        calculate_sha256(b"")
