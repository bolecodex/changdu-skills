"""Upload files to Volcengine TOS (Tinder Object Storage)."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

import tos


@dataclass
class UploadResult:
    bucket: str
    key: str
    url: str
    etag: str
    status_code: int


def upload_file(
    *,
    file_path: Path,
    bucket: str,
    key: str | None = None,
    ak: str,
    sk: str,
    endpoint: str,
    region: str,
    public: bool = False,
) -> UploadResult:
    """Upload a local file to TOS and return its URL.

    Args:
        file_path: Local file to upload.
        bucket: TOS bucket name.
        key: Object key (defaults to filename).
        ak: Volcengine Access Key.
        sk: Volcengine Secret Key.
        endpoint: TOS endpoint (e.g. tos-cn-beijing.volces.com).
        region: TOS region (e.g. cn-beijing).
        public: If True, set ACL to public-read.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    if key is None:
        key = file_path.name

    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

    file_size = file_path.stat().st_size
    timeout_s = max(120, file_size // (256 * 1024))  # ~4 KB/s worst-case

    client = tos.TosClientV2(
        ak, sk, endpoint, region,
        connection_time=30,
        socket_timeout=timeout_s,
    )

    acl = tos.ACLType.ACL_Public_Read if public else tos.ACLType.ACL_Private

    with open(file_path, "rb") as f:
        result = client.put_object(
            bucket,
            key,
            content=f,
            content_length=file_size,
            content_type=content_type,
            acl=acl,
        )

    if public:
        url = f"https://{bucket}.{endpoint}/{key}"
    else:
        url = f"https://{bucket}.{endpoint}/{key}"

    return UploadResult(
        bucket=bucket,
        key=key,
        url=url,
        etag=result.etag if hasattr(result, "etag") else "",
        status_code=result.status_code if hasattr(result, "status_code") else 200,
    )
