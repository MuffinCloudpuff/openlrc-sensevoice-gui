#  Copyright (C) 2024. Hao Zheng
#  All rights reserved.

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import httpx


def get_asr_options(batch_size_s, merge_length_s, use_itn, output_timestamp):
    return {
        "batch_size_s": batch_size_s,
        "merge_length_s": merge_length_s,
        "use_itn": use_itn,
        "output_timestamp": output_timestamp,
    }


def get_vad_options(max_single_segment_time):
    return {"max_single_segment_time": max_single_segment_time}


def get_preprocess_options(atten_lim_db):
    return {"atten_lim_db": atten_lim_db}


def detect_relay_models(provider_kind: str, base_url: str, api_key: str, proxy: str | None = None) -> list[str]:
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        raise ValueError("Base URL 不能为空。")
    if not api_key:
        raise ValueError("探测模型时需要可用的 API Key。")

    if provider_kind == "openai":
        header_candidates = [
            {"Authorization": f"Bearer {api_key}"},
            {"x-api-key": api_key},
            {"Authorization": f"Bearer {api_key}", "x-api-key": api_key},
        ]
        endpoint_candidates = [f"{base_url}/models", f"{base_url}/v1/models"]
    elif provider_kind == "anthropic":
        header_candidates = [
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            {
                "Authorization": f"Bearer {api_key}",
                "anthropic-version": "2023-06-01",
            },
        ]
        endpoint_candidates = [f"{base_url}/models", f"{base_url}/v1/models"]
    else:
        raise ValueError(f"不支持的中转提供商类型: {provider_kind}")

    seen = set()
    endpoint_candidates = [url for url in endpoint_candidates if not (url in seen or seen.add(url))]

    errors = []
    with httpx.Client(proxy=proxy, timeout=15.0, follow_redirects=True) as client:
        for endpoint in endpoint_candidates:
            for headers in header_candidates:
                try:
                    response = client.get(endpoint, headers=headers)
                    response.raise_for_status()
                    models = _extract_model_ids(response.json())
                    if models:
                        return models
                    errors.append(f"{endpoint} [{_header_mode(headers)}]: 未返回可识别的模型列表")
                except Exception as exc:
                    errors.append(f"{endpoint} [{_header_mode(headers)}]: {exc}")

    raise ValueError("模型探测失败。\n" + "\n".join(errors))


def _header_mode(headers: dict[str, str]) -> str:
    if "Authorization" in headers and "x-api-key" in headers:
        return "bearer+x-api-key"
    if "Authorization" in headers:
        return "bearer"
    if "x-api-key" in headers:
        return "x-api-key"
    return "unknown"


def _extract_model_ids(payload) -> list[str]:
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            return _extract_model_ids(payload["data"])
        if isinstance(payload.get("models"), list):
            return _extract_model_ids(payload["models"])
        if isinstance(payload.get("items"), list):
            return _extract_model_ids(payload["items"])
        if "id" in payload and isinstance(payload["id"], str):
            return [payload["id"]]
        if "name" in payload and isinstance(payload["name"], str):
            return [payload["name"]]
        return []

    if isinstance(payload, list):
        models = []
        for item in payload:
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("name")
                if isinstance(model_id, str):
                    models.append(model_id)
            elif isinstance(item, str):
                models.append(item)
        return sorted(set(models))

    return []


def zip_files(file_paths, zip_filename="zipped"):
    file_paths = [Path(path) for path in file_paths]
    zip_filename = file_paths[0].parent.with_name(zip_filename).with_suffix(".zip")
    with ZipFile(zip_filename, "w") as zip_object:
        _ = [zip_object.write(lrc_path, arcname=lrc_path.name) for lrc_path in file_paths]

    return zip_filename
