"""Evidence object storage (PRD 48, 60, 74).

LocalStorage writes to application-private disk; S3Storage writes to an S3 bucket.
Both hand out the same short-lived HMAC-signed app URL — the signature (not bearer
auth) is the capability, and bytes are always proxied through this API, never made
permanently public. PostgreSQL only ever holds the reference, never the bytes.

Select the backend with CPM_STORAGE_BACKEND=local|s3. LocalStorage is fine for a
single long-lived instance; use S3Storage for App Runner / ECS, where instances are
stateless and disposable and there is no shared local disk across them.
"""
import hmac
import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote

from .config import settings


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key  # the stored file_reference

    def read(self, ref: str) -> bytes:
        return (self.root / ref).read_bytes()

    def delete(self, ref: str) -> None:
        p = self.root / ref
        if p.exists():
            p.unlink()

    def exists(self, ref: str) -> bool:
        return (self.root / ref).exists()

    # --- signed URL (PRD 74: evidence URLs are never permanently public) ---
    def _sign(self, ref: str, exp: int) -> str:
        msg = f"{ref}:{exp}".encode()
        return hmac.new(settings.jwt_secret.encode(), msg, sha256).hexdigest()

    def signed_url(self, ref: str, ttl: int | None = None) -> str:
        exp = int(time.time()) + (ttl or settings.signed_url_ttl_sec)
        sig = self._sign(ref, exp)
        return f"{settings.api_prefix}/evidence/file?ref={quote(ref, safe='')}&exp={exp}&sig={sig}"

    def verify_signature(self, ref: str, exp: int, sig: str) -> bool:
        if exp < int(time.time()):
            return False
        return hmac.compare_digest(sig, self._sign(ref, exp))


class S3Storage:
    """Same interface as LocalStorage, backed by an S3 (or S3-compatible) bucket.
    Credentials come from the environment (an instance role in production; a local
    AWS CLI profile for testing) — never hard-coded. Set endpoint_url to point this
    at a non-AWS provider (Supabase Storage, Cloudflare R2, MinIO, ...) — those all
    need path-style addressing, which is harmless against real AWS S3 too."""

    def __init__(self, bucket: str, region: str, endpoint_url: str | None = None,
                 access_key_id: str | None = None, secret_access_key: str | None = None):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self._client = boto3.client(
            "s3", region_name=region, endpoint_url=endpoint_url,
            # None here means "use boto3's default credential chain" (EC2 instance
            # role on AWS) - only pass real values for providers with no such thing.
            aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key,
            config=Config(
                s3={"addressing_style": "path"},
                # boto3's newer default of sending CRC32 checksum headers on every
                # request breaks against most non-AWS S3-compatible providers
                # (Supabase Storage included) - restore the old opt-in behavior.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def save(self, key: str, data: bytes) -> str:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def read(self, ref: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=ref)["Body"].read()

    def delete(self, ref: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=ref)

    def exists(self, ref: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self.bucket, Key=ref)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    # --- signed URL: identical HMAC scheme to LocalStorage (PRD 74) ---
    def _sign(self, ref: str, exp: int) -> str:
        msg = f"{ref}:{exp}".encode()
        return hmac.new(settings.jwt_secret.encode(), msg, sha256).hexdigest()

    def signed_url(self, ref: str, ttl: int | None = None) -> str:
        exp = int(time.time()) + (ttl or settings.signed_url_ttl_sec)
        sig = self._sign(ref, exp)
        return f"{settings.api_prefix}/evidence/file?ref={quote(ref, safe='')}&exp={exp}&sig={sig}"

    def verify_signature(self, ref: str, exp: int, sig: str) -> bool:
        if exp < int(time.time()):
            return False
        return hmac.compare_digest(sig, self._sign(ref, exp))


def _build_storage():
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("CPM_STORAGE_BACKEND=s3 requires CPM_S3_BUCKET to be set.")
        return S3Storage(settings.s3_bucket, settings.aws_region, settings.s3_endpoint_url,
                          settings.s3_access_key_id, settings.s3_secret_access_key)
    return LocalStorage(settings.storage_dir)


storage = _build_storage()
