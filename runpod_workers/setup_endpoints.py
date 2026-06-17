"""RunPod Serverless 엔드포인트 최초 생성 스크립트.

세 개의 워커(플래너 LLM · 캐릭터 페르소나 LLM · 이미지 생성)를 RunPod API 로
자동 생성하고, .env 에 붙여 넣을 URL 을 출력한다.

필수 환경변수:
  RUNPOD_API_KEY      — RunPod API 키
  LLM_DOCKER_IMAGE    — LLM 워커 이미지  (예: docker.io/user/mongle-llm-worker:latest)
  IMAGE_DOCKER_IMAGE  — 이미지 워커 이미지 (예: docker.io/user/mongle-image-worker:latest)

선택 환경변수:
  HF_TOKEN            — private HuggingFace repo 접근용
"""
from __future__ import annotations

import os
import sys

import httpx

_GQL_URL = "https://api.runpod.io/graphql"

_WORKERS = [
    {
        "label": "플래너 LLM (todo · quest)",
        "template_name": "mongle-planner-llm",
        "endpoint_name": "mongle-planner-llm",
        "image_env": "LLM_DOCKER_IMAGE",
        "container_disk_gb": 5,
        "env": {"LORA_PLANNER_REPO": "bigmooon/qwen2.5-7b-mongle-planner-ko-lora"},
        "result_key": "RUNPOD_PLANNER_ENDPOINT_URL",
        "template_secret_key": "RUNPOD_PLANNER_TEMPLATE_ID",
        "network_volume_id": "lmrw00ibp3",
    },
    {
        "label": "캐릭터 페르소나 LLM",
        "template_name": "mongle-character-llm",
        "endpoint_name": "mongle-character-llm",
        "image_env": "LLM_DOCKER_IMAGE",
        "container_disk_gb": 5,
        "env": {"LORA_CHARACTER_REPO": "deeps1eep/qwen2.5-7b-mongle-village"},
        "result_key": "RUNPOD_CHARACTER_ENDPOINT_URL",
        "template_secret_key": "RUNPOD_CHARACTER_TEMPLATE_ID",
        "network_volume_id": "lmrw00ibp3",
    },
    {
        "label": "이미지 생성 워커 (character + bg 합본)",
        "template_name": "mongle-image-gen",
        "endpoint_name": "mongle-image-gen",
        "image_env": "IMAGE_DOCKER_IMAGE",
        "container_disk_gb": 5,
        "env": {
            "LORA_CHARACTER_REPO": "Hadimeeee/mongle-character-lora",
            "LORA_BG_REPO": "Hadimeeee/mongle-bg-lora",
        },
        "result_key": "RUNPOD_IMAGE_ENDPOINT_URL",
        "template_secret_key": "RUNPOD_IMAGE_TEMPLATE_ID",
        "network_volume_id": None,
    },
]

_SAVE_TEMPLATE = """
mutation SaveTemplate($input: SaveTemplateInput!) {
  saveTemplate(input: $input) { id name }
}
"""

_SAVE_ENDPOINT = """
mutation SaveEndpoint($input: EndpointInput!) {
  saveEndpoint(input: $input) { id name }
}
"""


def _gql(query: str, variables: dict, api_key: str) -> dict:
    resp = httpx.post(
        f"{_GQL_URL}?api_key={api_key}",
        json={"query": query, "variables": variables},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    if errors := data.get("errors"):
        raise RuntimeError(f"RunPod GraphQL 오류: {errors}")
    return data["data"]


def create_template(
    api_key: str,
    name: str,
    image: str,
    env: dict[str, str],
    disk_gb: int,
) -> str:
    env_list = [{"key": k, "value": v} for k, v in env.items() if v]
    data = _gql(
        _SAVE_TEMPLATE,
        {
            "input": {
                "name": name,
                "imageName": image,
                "containerDiskInGb": disk_gb,
                "volumeInGb": 0,
                "dockerArgs": "",
                "env": env_list,
                "isServerless": True,
            }
        },
        api_key,
    )
    template_id: str = data["saveTemplate"]["id"]
    print(f"    template id: {template_id}")
    return template_id


def create_endpoint(
    api_key: str, name: str, template_id: str, network_volume_id: str | None = None
) -> str:
    data = _gql(
        _SAVE_ENDPOINT,
        {
            "input": {
                "name": name,
                "templateId": template_id,
                "gpuIds": "AMPERE_24",  # RTX 3090/4090 24 GB — Qwen 7B fp16 에 충분
                "workersMin": 0,
                "workersMax": 3,
                "idleTimeout": 5,
                "scalerType": "QUEUE_DELAY",
                "scalerValue": 4,
                "networkVolumeId": network_volume_id,
            }
        },
        api_key,
    )
    endpoint_id: str = data["saveEndpoint"]["id"]
    print(f"    endpoint id: {endpoint_id}")
    return endpoint_id


def main() -> None:
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    hf_token = os.environ.get("HF_TOKEN", "").strip()

    missing = [
        k for k in ("RUNPOD_API_KEY", "LLM_DOCKER_IMAGE", "IMAGE_DOCKER_IMAGE")
        if not os.environ.get(k, "").strip()
    ]
    if missing:
        sys.exit(f"필수 환경변수가 없습니다: {', '.join(missing)}")

    results: dict[str, str] = {}
    template_ids: dict[str, str] = {}

    for idx, w in enumerate(_WORKERS, 1):
        image = os.environ[w["image_env"]].strip()
        print(f"\n[{idx}/{len(_WORKERS)}] {w['label']}")
        print(f"    image: {image}")

        env = dict(w["env"])
        if hf_token:
            env["HF_TOKEN"] = hf_token

        template_id = create_template(
            api_key, w["template_name"], image, env, w["container_disk_gb"]
        )
        endpoint_id = create_endpoint(
            api_key, w["endpoint_name"], template_id, w.get("network_volume_id")
        )
        results[w["result_key"]] = f"https://api.runpod.ai/v2/{endpoint_id}"
        template_ids[w["template_secret_key"]] = template_id

    print("\n" + "=" * 60)
    print(".env 에 아래 값을 추가하세요:")
    print("=" * 60)
    for key, url in results.items():
        print(f"{key}={url}")

    print("\n" + "=" * 60)
    print("GitHub Secrets 에 아래 값을 추가하세요 (CI/CD 자동 배포용):")
    print("  Settings → Secrets and variables → Actions → New repository secret")
    print("=" * 60)
    for key, tid in template_ids.items():
        print(f"{key}={tid}")
    print("=" * 60)


if __name__ == "__main__":
    main()
