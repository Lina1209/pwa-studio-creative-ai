"""Private Supabase Storage adapter for generated image assets.

Uploads are create-only, then independently verifies bucket privacy, object
metadata and the downloaded bytes through Storage's authenticated API. The
service-role key is server-only. No public URLs or signed URLs are produced.
"""
import logging
from dataclasses import dataclass
from urllib.parse import quote
from uuid import UUID

import httpx

from app.core.config import Settings
from app.services.generation_result_storage import (
    GenerationResultStorageError,
    GenerationStorageAdapterError,
    StoredObjectMetadata,
    calculate_sha256,
)
from app.services.generation_worker import UploadedImageObject
from app.services.image_generation import ALLOWED_IMAGE_MIME_TYPES, MAX_IMAGE_BYTES

logger = logging.getLogger(__name__)


class SupabaseStorageNotConfiguredError(GenerationStorageAdapterError):
    def __init__(self):
        super().__init__("storage_not_configured", retryable=False)


class SupabaseStorageAdapterError(GenerationStorageAdapterError):
    pass


@dataclass(frozen=True)
class ListedGeneratedObject:
    object_path: str
    size_bytes: int
    content_type: str | None
    created_at: str | None


class SupabasePrivateImageStorage:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        *,
        timeout_seconds: float = 30.0,
    ):
        key = settings.supabase_service_role_key
        if not settings.supabase_url or not key:
            raise SupabaseStorageNotConfiguredError()
        if not 1 <= timeout_seconds <= 180:
            raise ValueError("Storage timeout must be between 1 and 180 seconds.")
        self._base_url = settings.supabase_url.rstrip("/") + "/storage/v1"
        self._bucket = settings.generation_storage_bucket
        if not self._bucket or len(self._bucket) > 100 or "/" in self._bucket:
            raise ValueError("Generation storage bucket configuration is invalid.")
        self._client = client
        self._timeout = timeout_seconds
        self._headers = {"apikey": key}
        # Legacy JWT service-role keys require a bearer header. New sb_secret
        # keys are API keys, not JWTs, and must not be wrapped as Bearer tokens.
        if key.startswith("eyJ"):
            self._headers["Authorization"] = f"Bearer {key}"

    @staticmethod
    def _encoded_path(path: str) -> str:
        return "/".join(quote(part, safe="") for part in path.split("/"))

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            extra_headers = kwargs.pop("headers", {})
            merged_headers = {**self._headers, **extra_headers}
            response = await self._client.request(
                method, url, headers=merged_headers, timeout=self._timeout, **kwargs
            )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise SupabaseStorageAdapterError(
                "storage_request_timeout", retryable=True
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            error_code = (
                "storage_service_unavailable" if status >= 500
                else "storage_object_already_exists" if status == 409
                else "storage_request_rejected"
            )
            raise SupabaseStorageAdapterError(
                error_code,
                retryable=status >= 500 or status == 429,
            ) from exc
        except httpx.HTTPError as exc:
            raise SupabaseStorageAdapterError(
                "storage_transport_error", retryable=True
            ) from exc

    async def _download_object(self, url: str) -> bytes:
        payload = bytearray()
        try:
            async with self._client.stream(
                "GET", url, headers=self._headers, timeout=self._timeout
            ) as response:
                response.raise_for_status()
                declared_length = response.headers.get("content-length")
                if declared_length:
                    try:
                        if int(declared_length) > MAX_IMAGE_BYTES:
                            raise GenerationResultStorageError("stored_object_too_large")
                    except ValueError as exc:
                        raise SupabaseStorageAdapterError("storage_content_length_invalid") from exc
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_IMAGE_BYTES:
                        raise GenerationResultStorageError("stored_object_too_large")
            return bytes(payload)
        except httpx.TimeoutException as exc:
            raise SupabaseStorageAdapterError(
                "storage_request_timeout", retryable=True
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise SupabaseStorageAdapterError(
                "storage_service_unavailable" if status >= 500 else "storage_request_rejected",
                retryable=status >= 500 or status == 429,
            ) from exc
        except httpx.HTTPError as exc:
            raise SupabaseStorageAdapterError(
                "storage_transport_error", retryable=True
            ) from exc

    async def _delete_own_object(self, path: str) -> None:
        try:
            await self._request(
                "DELETE",
                f"{self._base_url}/object/{quote(self._bucket, safe='')}/{self._encoded_path(path)}",
            )
        except Exception:
            logger.warning("generation_storage_orphan_cleanup_failed bucket=%s", self._bucket)

    async def list_owner_generated_objects(
        self, *, owner_id: UUID, page_size: int = 100, max_pages: int = 10
    ) -> list[ListedGeneratedObject]:
        """Inventory one owner's generated folder without mutating any object."""
        if not 1 <= page_size <= 1000 or not 1 <= max_pages <= 100:
            raise ValueError("Storage inventory pagination is out of bounds.")
        encoded_bucket = quote(self._bucket, safe="")
        bucket_response = await self._request(
            "GET", f"{self._base_url}/bucket/{encoded_bucket}"
        )
        bucket_info = bucket_response.json()
        if not isinstance(bucket_info, dict) or bucket_info.get("public") is not False:
            raise GenerationResultStorageError("object_bucket_must_be_private")
        prefix = f"{owner_id}/generated"
        results: list[ListedGeneratedObject] = []
        for page in range(max_pages):
            response = await self._request(
                "POST",
                f"{self._base_url}/object/list/{encoded_bucket}",
                json={
                    "prefix": prefix,
                    "limit": page_size,
                    "offset": page * page_size,
                    "sortBy": {"column": "created_at", "order": "asc"},
                },
            )
            rows = response.json()
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise SupabaseStorageAdapterError("storage_inventory_response_invalid")
            for row in rows:
                name = row.get("name")
                metadata = row.get("metadata")
                if not isinstance(name, str) or not name or "/" in name or not isinstance(metadata, dict):
                    raise SupabaseStorageAdapterError("storage_inventory_metadata_invalid")
                raw_size = metadata.get("size")
                if isinstance(raw_size, bool):
                    raise SupabaseStorageAdapterError("storage_inventory_size_invalid")
                if isinstance(raw_size, int):
                    size = raw_size
                elif isinstance(raw_size, str) and raw_size.isdecimal():
                    size = int(raw_size)
                else:
                    raise SupabaseStorageAdapterError("storage_inventory_size_invalid")
                if size < 0 or size > MAX_IMAGE_BYTES:
                    raise SupabaseStorageAdapterError("storage_inventory_size_out_of_range")
                results.append(
                    ListedGeneratedObject(
                        object_path=f"{prefix}/{name}",
                        size_bytes=size,
                        content_type=metadata.get("mimetype") or metadata.get("contentType"),
                        created_at=row.get("created_at") or row.get("updated_at"),
                    )
                )
            if len(rows) < page_size:
                return results
        raise SupabaseStorageAdapterError("storage_inventory_page_limit_reached")

    async def verify_existing_image(
        self, *, owner_id: UUID, job_id: UUID, object_path: str
    ) -> StoredObjectMetadata:
        """Re-verify a previously completed result against private Storage.

        The path is derived from the owner/job pair and must match exactly;
        Storage metadata is read independently and bytes are downloaded with
        a hard size bound before a fresh SHA-256 is calculated.
        """
        allowed_extensions = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
        prefix = f"{owner_id}/generated/"
        if not isinstance(object_path, str) or not object_path.startswith(prefix):
            raise GenerationResultStorageError("stored_object_path_invalid")
        filename = object_path[len(prefix):]
        if "/" in filename or filename.count(".") != 1:
            raise GenerationResultStorageError("stored_object_path_invalid")
        stem, extension = filename.rsplit(".", 1)
        expected_mime = allowed_extensions.get(extension)
        if stem != str(job_id) or expected_mime is None:
            raise GenerationResultStorageError("stored_object_path_invalid")

        encoded_bucket = quote(self._bucket, safe="")
        bucket_response = await self._request(
            "GET", f"{self._base_url}/bucket/{encoded_bucket}"
        )
        bucket_info = bucket_response.json()
        if not isinstance(bucket_info, dict) or bucket_info.get("public") is not False:
            raise GenerationResultStorageError("object_bucket_must_be_private")

        matches = []
        page_size = 100
        max_pages = 10
        for page in range(max_pages):
            listing_response = await self._request(
                "POST",
                f"{self._base_url}/object/list/{encoded_bucket}",
                json={
                    "prefix": f"{owner_id}/generated",
                    "limit": page_size,
                    "offset": page * page_size,
                    "sortBy": {"column": "created_at", "order": "asc"},
                },
            )
            listing = listing_response.json()
            if not isinstance(listing, list):
                raise SupabaseStorageAdapterError("storage_metadata_invalid")
            if any(not isinstance(row, dict) for row in listing):
                raise SupabaseStorageAdapterError("storage_metadata_invalid")
            matches.extend(row for row in listing if row.get("name") == filename)
            if len(matches) > 1:
                raise GenerationResultStorageError("duplicate_storage_object_metadata")
            if len(matches) == 1:
                break
            if len(listing) < page_size:
                break
        else:
            # Do not report a false missing result when the target may be
            # beyond this bounded verification window.
            raise SupabaseStorageAdapterError(
                "storage_verification_listing_limit_reached", retryable=True
            )
        if len(matches) != 1:
            raise SupabaseStorageAdapterError(
                "storage_object_metadata_missing", retryable=True
            )
        metadata = matches[0].get("metadata")
        if not isinstance(metadata, dict):
            raise SupabaseStorageAdapterError("storage_object_metadata_invalid")
        raw_size = metadata.get("size")
        if isinstance(raw_size, bool):
            raise SupabaseStorageAdapterError("storage_object_size_invalid")
        if isinstance(raw_size, int):
            size_bytes = raw_size
        elif isinstance(raw_size, str) and raw_size.isdecimal():
            size_bytes = int(raw_size)
        else:
            raise SupabaseStorageAdapterError("storage_object_size_invalid")
        content_type = metadata.get("mimetype") or metadata.get("contentType")
        if not 0 < size_bytes <= MAX_IMAGE_BYTES:
            raise GenerationResultStorageError("object_size_out_of_range")
        if content_type != expected_mime:
            raise GenerationResultStorageError("object_mime_not_allowed")

        encoded_path = self._encoded_path(object_path)
        payload = await self._download_object(
            f"{self._base_url}/object/authenticated/{encoded_bucket}/{encoded_path}"
        )
        if len(payload) != size_bytes:
            raise GenerationResultStorageError("stored_object_content_mismatch")
        return StoredObjectMetadata(
            bucket=self._bucket,
            object_path=object_path,
            is_private=True,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256_hex=calculate_sha256(payload),
        )

    async def create_signed_download_url(
        self,
        *,
        owner_id: UUID,
        job_id: UUID,
        object_path: str,
        expected_sha256_hex: str,
        expires_in: int = 60,
    ) -> str:
        """Issue a short-lived download URL only after owner/path/hash verification."""
        if isinstance(expires_in, bool) or not 30 <= expires_in <= 300:
            raise ValueError("Signed download lifetime must be between 30 and 300 seconds.")
        verified = await self.verify_existing_image(
            owner_id=owner_id, job_id=job_id, object_path=object_path
        )
        if (
            not isinstance(expected_sha256_hex, str)
            or len(expected_sha256_hex) != 64
            or verified.sha256_hex != expected_sha256_hex
        ):
            raise GenerationResultStorageError("stored_object_checksum_mismatch")

        encoded_bucket = quote(self._bucket, safe="")
        encoded_path = self._encoded_path(object_path)
        response = await self._request(
            "POST",
            f"{self._base_url}/object/sign/{encoded_bucket}/{encoded_path}",
            json={"expiresIn": expires_in},
        )
        try:
            signed_path = response.json().get("signedURL")
            if not isinstance(signed_path, str):
                raise ValueError("signedURL")
            # Storage returns a path, never an arbitrary host. Reject absolute
            # URLs and path traversal before composing the trusted project URL.
            from urllib.parse import urlsplit
            parsed = urlsplit(signed_path)
            expected_prefix = f"/object/sign/{self._bucket}/"
            if (
                parsed.scheme or parsed.netloc or not parsed.path.startswith(expected_prefix)
                or ".." in parsed.path.split("/")
                or not parsed.query
            ):
                raise ValueError("signedURL")
        except (ValueError, AttributeError) as exc:
            raise SupabaseStorageAdapterError("storage_signed_url_invalid") from exc
        return f"{self._base_url}{signed_path}"

    async def upload_image(
        self, *, owner_id: UUID, job_id: UUID, image_bytes: bytes, mime_type: str
    ) -> UploadedImageObject:
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise GenerationResultStorageError("empty_or_invalid_upload_payload")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise GenerationResultStorageError("upload_payload_too_large")
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise GenerationResultStorageError("object_mime_not_allowed")

        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[mime_type]
        object_path = f"{owner_id}/generated/{job_id}.{extension}"
        encoded_bucket = quote(self._bucket, safe="")
        encoded_path = self._encoded_path(object_path)
        object_url = f"{self._base_url}/object/{encoded_bucket}/{encoded_path}"

        # POST without x-upsert is deliberately create-only. If a previous
        # attempt succeeded but its response was lost, a retry receives 409;
        # verify the deterministic existing object instead of overwriting it.
        already_exists = False
        try:
            await self._request(
                "POST",
                object_url,
                content=image_bytes,
                headers={
                    "Content-Type": mime_type,
                    "Cache-Control": "max-age=0",
                    "x-upsert": "false",
                },
            )
        except SupabaseStorageAdapterError as exc:
            if exc.error_code != "storage_object_already_exists":
                raise
            already_exists = True

        try:
            bucket_response = await self._request(
                "GET", f"{self._base_url}/bucket/{encoded_bucket}"
            )
            bucket_info = bucket_response.json()
            if not isinstance(bucket_info, dict) or bucket_info.get("public") is not False:
                raise GenerationResultStorageError("object_bucket_must_be_private")

            prefix = f"{owner_id}/generated"
            expected_name = f"{job_id}.{extension}"
            matches = []
            page_size = 100
            max_pages = 10
            for page in range(max_pages):
                listing_response = await self._request(
                    "POST",
                    f"{self._base_url}/object/list/{encoded_bucket}",
                    json={
                        "prefix": prefix,
                        "limit": page_size,
                        "offset": page * page_size,
                        "sortBy": {"column": "created_at", "order": "asc"},
                    },
                )
                listing = listing_response.json()
                if not isinstance(listing, list):
                    raise SupabaseStorageAdapterError("storage_metadata_invalid")
                matches.extend(
                    item for item in listing
                    if isinstance(item, dict) and item.get("name") == expected_name
                )
                if len(matches) > 1:
                    raise GenerationResultStorageError("duplicate_storage_object_metadata")
                if len(matches) == 1:
                    break
                if len(listing) < page_size:
                    break
            else:
                # The expected object may be beyond the bounded inventory.
                # Do not misclassify a truncated listing as a missing object.
                raise SupabaseStorageAdapterError(
                    "storage_verification_listing_limit_reached", retryable=True
                )
            if len(matches) != 1:
                # Storage listing can lag a successful upload; retry safely
                # using the deterministic create-only object path.
                raise SupabaseStorageAdapterError(
                    "storage_object_metadata_missing", retryable=True
                )
            metadata = matches[0].get("metadata")
            if not isinstance(metadata, dict):
                raise SupabaseStorageAdapterError("storage_object_metadata_invalid")

            stored_size = metadata.get("size")
            if isinstance(stored_size, bool):
                raise SupabaseStorageAdapterError("storage_object_size_invalid")
            if isinstance(stored_size, int):
                size_bytes = stored_size
            elif isinstance(stored_size, str) and stored_size.isdecimal():
                size_bytes = int(stored_size)
            else:
                raise SupabaseStorageAdapterError("storage_object_size_invalid")
            if not 0 < size_bytes <= MAX_IMAGE_BYTES:
                raise GenerationResultStorageError("object_size_out_of_range")
            stored_mime = metadata.get("mimetype") or metadata.get("contentType")
            if stored_mime != mime_type or size_bytes != len(image_bytes):
                raise GenerationResultStorageError("uploaded_object_content_mismatch")

            downloaded = await self._download_object(
                f"{self._base_url}/object/authenticated/{encoded_bucket}/{encoded_path}"
            )
            if len(downloaded) > MAX_IMAGE_BYTES or downloaded != image_bytes:
                raise GenerationResultStorageError("stored_object_bytes_mismatch")
            digest = calculate_sha256(downloaded)

            return UploadedImageObject(
                metadata=StoredObjectMetadata(
                    bucket=self._bucket,
                    object_path=object_path,
                    is_private=True,
                    content_type=stored_mime,
                    size_bytes=size_bytes,
                    sha256_hex=digest,
                ),
                expected_bucket=self._bucket,
                expected_object_path=object_path,
                expected_sha256_hex=digest,
            )
        except Exception as exc:
            # Preserve pre-existing objects and newly uploaded objects when
            # verification failed only because Storage was temporarily
            # unavailable. A retry can receive 409 and verify the same bytes.
            # Delete only a newly-created object after a definitive failure.
            retryable_storage_error = (
                isinstance(exc, SupabaseStorageAdapterError) and exc.retryable
            )
            if not already_exists and not retryable_storage_error:
                await self._delete_own_object(object_path)
            raise
