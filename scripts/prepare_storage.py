from __future__ import annotations

import sys

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from snax_import.config import settings


def main() -> int:
    if not settings.s3_endpoint or not settings.s3_access_key or not settings.s3_secret_key:
        raise RuntimeError("S3_ENDPOINT, S3_ACCESS_KEY and S3_SECRET_KEY are required")
    if not settings.s3_bucket:
        raise RuntimeError("S3_BUCKET is required")
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"}),
    )
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status not in {400, 403, 404}:
            raise
        client.create_bucket(Bucket=settings.s3_bucket)
    print(f"prepared bucket {settings.s3_bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
