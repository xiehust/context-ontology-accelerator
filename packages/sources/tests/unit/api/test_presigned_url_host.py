# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression test: presigned upload URLs must target the regional S3 endpoint.

With SigV4 alone botocore presigns against the global ``<bucket>.s3.amazonaws.com``
host. For a bucket outside us-east-1 that host answers with a 307 redirect, and the
redirect carries no CORS headers, so a browser PUT to the URL fails. The client
must therefore pin virtual-hosted addressing, which yields the regional host.
"""

from __future__ import annotations

import os

os.environ.setdefault("SOURCES_TABLE", "test-sources")
os.environ.setdefault("SOURCE_SCAN_JOBS_TABLE", "test-scan-jobs")
os.environ.setdefault("NAMESPACES_TABLE", "test-namespaces")
os.environ.setdefault("INGESTION_QUEUE_URL", "https://sqs.us-west-2.amazonaws.com/123/ingestion-queue")
os.environ.setdefault("BUCKET_NAME", "test-bucket")

import coa_sources.api.sources_handler as sources_handler  # noqa: E402


def test_presigned_put_url_uses_regional_endpoint(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setattr(sources_handler, "_AWS_REGION", "us-west-2")
    monkeypatch.setattr(sources_handler, "_s3", None)

    url = sources_handler._get_s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": "my-bucket", "Key": "ns/raw/id/a.md", "ContentType": "text/markdown"},
        ExpiresIn=900,
    )

    assert url.startswith("https://my-bucket.s3.us-west-2.amazonaws.com/")
    assert "s3.amazonaws.com/" not in url
