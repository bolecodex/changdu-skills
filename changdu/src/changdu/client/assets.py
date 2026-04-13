"""Volcengine Ark Assets API client (AK/SK HMAC-SHA256 auth)."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from changdu.errors import AuthError, NetworkError, RequestError, ServerError


def _hmac_sha256(key: bytes, content: str) -> bytes:
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _hash_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _norm_query(params: dict[str, str]) -> str:
    parts = []
    for key in sorted(params.keys()):
        parts.append(f"{quote(key, safe='-_.~')}={quote(str(params[key]), safe='-_.~')}")
    return "&".join(parts).replace("+", "%20")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


@dataclass
class AssetInfo:
    id: str
    name: str = ""
    url: str = ""
    asset_type: str = ""
    group_id: str = ""
    status: str = ""
    error_code: str = ""
    error_message: str = ""
    create_time: str = ""
    update_time: str = ""
    project_name: str = ""

    @property
    def asset_url(self) -> str:
        """Return the asset:// protocol URL for use in video generation."""
        return f"asset://{self.id}"


@dataclass
class AssetGroupInfo:
    id: str
    name: str = ""
    description: str = ""
    group_type: str = ""
    project_name: str = ""
    create_time: str = ""
    update_time: str = ""


class AssetsClient:
    """Client for Volcengine Ark Assets API with HMAC-SHA256 signing."""

    SERVICE = "ark"
    VERSION = "2024-01-01"
    CONTENT_TYPE = "application/json"

    def __init__(
        self,
        *,
        ak: str,
        sk: str,
        region: str = "cn-beijing",
        host: str = "open.volcengineapi.com",
        timeout_s: int = 30,
    ) -> None:
        self.ak = ak
        self.sk = sk
        self.region = region
        self.host = host
        self.timeout_s = timeout_s

    def _sign_and_call(self, action: str, body: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        body_str = json.dumps(body, ensure_ascii=False)
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        short_x_date = x_date[:8]
        x_content_sha256 = _hash_sha256(body_str)

        query_params = {"Action": action, "Version": self.VERSION}
        query_string = _norm_query(query_params)

        signed_headers_str = "content-type;host;x-content-sha256;x-date"
        canonical_request = "\n".join([
            "POST",
            "/",
            query_string,
            f"content-type:{self.CONTENT_TYPE}",
            f"host:{self.host}",
            f"x-content-sha256:{x_content_sha256}",
            f"x-date:{x_date}",
            "",
            signed_headers_str,
            x_content_sha256,
        ])

        hashed_canonical = _hash_sha256(canonical_request)
        credential_scope = f"{short_x_date}/{self.region}/{self.SERVICE}/request"
        string_to_sign = "\n".join(["HMAC-SHA256", x_date, credential_scope, hashed_canonical])

        k_date = _hmac_sha256(self.sk.encode("utf-8"), short_x_date)
        k_region = _hmac_sha256(k_date, self.region)
        k_service = _hmac_sha256(k_region, self.SERVICE)
        k_signing = _hmac_sha256(k_service, "request")
        signature = _hmac_sha256(k_signing, string_to_sign).hex()

        authorization = (
            f"HMAC-SHA256 Credential={self.ak}/{credential_scope}, "
            f"SignedHeaders={signed_headers_str}, Signature={signature}"
        )

        headers = {
            "Content-Type": self.CONTENT_TYPE,
            "Host": self.host,
            "X-Content-Sha256": x_content_sha256,
            "X-Date": x_date,
            "Authorization": authorization,
        }

        url = f"https://{self.host}/"
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.post(url, headers=headers, params=query_params, content=body_str)
        except httpx.RequestError as exc:
            raise NetworkError(f"Assets API 网络错误: {exc}") from exc

        request_id = ""
        try:
            data = resp.json()
        except ValueError:
            raise ServerError(f"Assets API 响应非 JSON: {resp.text[:500]}")

        meta = data.get("ResponseMetadata", {})
        request_id = meta.get("RequestId", "")
        error = meta.get("Error")
        if error:
            code = error.get("Code", "")
            message = error.get("Message", "")
            full_msg = f"[{code}] {message}" if code else message
            if resp.status_code in (401, 403) or "auth" in code.lower():
                raise AuthError(full_msg, request_id=request_id)
            raise RequestError(full_msg, request_id=request_id)

        if resp.status_code >= 500:
            raise ServerError(f"Assets API 服务端错误: HTTP {resp.status_code}", request_id=request_id)
        if resp.status_code >= 400:
            raise RequestError(f"Assets API 请求失败: HTTP {resp.status_code}", request_id=request_id)

        return data.get("Result", data)

    # ── Asset Group ──

    def create_group(
        self,
        name: str,
        description: str = "",
        group_type: str = "AIGC",
        project_name: str = "default",
    ) -> AssetGroupInfo:
        body: dict[str, Any] = {"Name": name, "GroupType": group_type, "ProjectName": project_name}
        if description:
            body["Description"] = description
        result = self._sign_and_call("CreateAssetGroup", body)
        return AssetGroupInfo(id=result.get("Id", ""), name=name, group_type=group_type, project_name=project_name)

    def list_groups(
        self,
        group_type: str = "AIGC",
        page: int = 1,
        page_size: int = 20,
        project_name: str = "default",
    ) -> list[AssetGroupInfo]:
        body: dict[str, Any] = {
            "Filter": {"GroupType": group_type},
            "PageNumber": page,
            "PageSize": page_size,
            "ProjectName": project_name,
        }
        result = self._sign_and_call("ListAssetGroups", body)
        items = result.get("Items", [])
        return [
            AssetGroupInfo(
                id=item.get("Id", ""),
                name=item.get("Name", ""),
                description=item.get("Description", ""),
                group_type=item.get("GroupType", ""),
                project_name=item.get("ProjectName", ""),
                create_time=item.get("CreateTime", ""),
                update_time=item.get("UpdateTime", ""),
            )
            for item in items
        ]

    def get_group(self, group_id: str, project_name: str = "default") -> AssetGroupInfo:
        result = self._sign_and_call("GetAssetGroup", {"Id": group_id, "ProjectName": project_name})
        return AssetGroupInfo(
            id=result.get("Id", ""),
            name=result.get("Name", ""),
            description=result.get("Description", ""),
            group_type=result.get("GroupType", ""),
            project_name=result.get("ProjectName", ""),
            create_time=result.get("CreateTime", ""),
            update_time=result.get("UpdateTime", ""),
        )

    # ── Asset ──

    def create_asset(
        self,
        group_id: str,
        url: str,
        asset_type: str = "Image",
        name: str = "",
        project_name: str = "default",
    ) -> AssetInfo:
        body: dict[str, Any] = {
            "GroupId": group_id,
            "URL": url,
            "AssetType": asset_type,
            "ProjectName": project_name,
        }
        if name:
            body["Name"] = name
        result = self._sign_and_call("CreateAsset", body)
        return AssetInfo(id=result.get("Id", ""), asset_type=asset_type, group_id=group_id, status="Processing")

    def get_asset(self, asset_id: str, project_name: str = "default") -> AssetInfo:
        result = self._sign_and_call("GetAsset", {"Id": asset_id, "ProjectName": project_name})
        error = result.get("Error", {}) or {}
        return AssetInfo(
            id=result.get("Id", ""),
            name=result.get("Name", ""),
            url=result.get("URL", ""),
            asset_type=result.get("AssetType", ""),
            group_id=result.get("GroupId", ""),
            status=result.get("Status", ""),
            error_code=error.get("Code", "") if isinstance(error, dict) else "",
            error_message=error.get("Message", "") if isinstance(error, dict) else str(error),
            create_time=result.get("CreateTime", ""),
            update_time=result.get("UpdateTime", ""),
            project_name=result.get("ProjectName", ""),
        )

    def list_assets(
        self,
        group_ids: list[str] | None = None,
        group_type: str = "AIGC",
        statuses: list[str] | None = None,
        page: int = 1,
        page_size: int = 20,
        project_name: str = "default",
    ) -> list[AssetInfo]:
        filt: dict[str, Any] = {"GroupType": group_type}
        if group_ids:
            filt["GroupIds"] = group_ids
        if statuses:
            filt["Statuses"] = statuses
        body: dict[str, Any] = {
            "Filter": filt,
            "PageNumber": page,
            "PageSize": page_size,
            "ProjectName": project_name,
        }
        result = self._sign_and_call("ListAssets", body)
        items = result.get("Items", [])
        return [
            AssetInfo(
                id=item.get("Id", ""),
                name=item.get("Name", ""),
                url=item.get("URL", ""),
                asset_type=item.get("AssetType", ""),
                group_id=item.get("GroupId", ""),
                status=item.get("Status", ""),
                create_time=item.get("CreateTime", ""),
                update_time=item.get("UpdateTime", ""),
                project_name=item.get("ProjectName", ""),
            )
            for item in items
        ]

    def delete_asset(self, asset_id: str, project_name: str = "default") -> None:
        self._sign_and_call("DeleteAsset", {"Id": asset_id, "ProjectName": project_name})

    def wait_for_active(self, asset_id: str, project_name: str = "default", interval_s: int = 3, timeout_s: int = 120) -> AssetInfo:
        """Poll GetAsset until status is Active or Failed."""
        import time
        deadline = time.time() + timeout_s
        while True:
            info = self.get_asset(asset_id, project_name=project_name)
            if info.status == "Active":
                return info
            if info.status == "Failed":
                raise RequestError(
                    f"素材处理失败: {info.error_message or info.error_code or '未知错误'} (asset_id={asset_id})"
                )
            if time.time() > deadline:
                raise RequestError(f"素材处理超时 ({timeout_s}s), 当前状态: {info.status} (asset_id={asset_id})")
            time.sleep(interval_s)
