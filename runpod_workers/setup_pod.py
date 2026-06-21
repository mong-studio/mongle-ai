"""RunPod 상시 CPU Pod(FastAPI AI 엔진) 최초 생성 스크립트.

mongle-ai FastAPI 이미지를 RunPod Secure Cloud 의 **상시 CPU Pod** 으로 띄운다.
Pod 는 장수(long-lived)로 유지하며, 이후 배포는 `.github/workflows/deploy-api.yml`
이 Pod 를 stop→start 해 `:latest` 를 재-pull 하는 방식으로 갱신한다(Pod ID 고정 →
프록시 URL 안정). GPU 워커(planner·character·image)는 별도 Serverless 엔드포인트.

필수 환경변수:
  RUNPOD_API_KEY              — RunPod API 키
  API_DOCKER_IMAGE           — FastAPI 이미지 (예: mongstudio/mongle-ai:latest)
  # 아래는 Pod 안의 앱이 쓰는 env (config.py 의 from_env 요구사항)
  MONGLE_API_KEY             — Django 가 보내는 X-API-Key
  RUNPOD_PLANNER_ENDPOINT_URL
  RUNPOD_CHARACTER_ENDPOINT_URL
  RUNPOD_IMAGE_ENDPOINT_URL
  AWS_S3_BUCKET, AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY  (S3 — IAM role 못 쓰므로 키 주입)

선택 환경변수:
  AWS_S3_PREFIX, QWEN_BASE_URL, QWEN_MODEL, QWEN_PERSONA_MODEL,
  CPU_FLAVOR(기본 cpu3g-2-8 = 2vCPU/8GB), VCPU_COUNT(기본 2), POD_NAME(기본 mongle-ai-api)

실행 후 출력되는 Pod ID 를 GitHub Secret `RUNPOD_POD_ID` 에 등록하고,
프록시 URL 을 mongle-server 의 `MONGLE_AI_API_BASE` 로 설정한다.
"""
from __future__ import annotations

import os
import sys

import httpx

_REST_URL = "https://rest.runpod.io/v1/pods"
_HTTP_PORT = 8010

# Pod 생성 시 RunPod 에 직접 지정하는 고정 env (provider 분기 강제)
_FIXED_ENV = {
    "LLM_PROVIDER": "runpod",
    "QUEST_LLM_PROVIDER": "runpod",
    "FEED_LLM_PROVIDER": "runpod",
    "IMAGE_PROVIDER": "runpod",
    "STORAGE_BACKEND": "s3",
}

# 로컬 환경에서 Pod 로 그대로 전달할 env 키 (값이 있을 때만 주입)
_REQUIRED_APP_ENV = (
    "MONGLE_API_KEY",
    "RUNPOD_API_KEY",
    "RUNPOD_PLANNER_ENDPOINT_URL",
    "RUNPOD_CHARACTER_ENDPOINT_URL",
    "RUNPOD_IMAGE_ENDPOINT_URL",
    "AWS_S3_BUCKET",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)
_OPTIONAL_APP_ENV = (
    "AWS_S3_PREFIX",
    "QWEN_BASE_URL",
    "QWEN_MODEL",
    "QWEN_PERSONA_MODEL",
)


def _collect_env() -> dict[str, str]:
    """Pod 에 주입할 env 를 모은다(고정값 + 로컬에서 전달하는 앱 설정)."""
    env = dict(_FIXED_ENV)
    for key in (*_REQUIRED_APP_ENV, *_OPTIONAL_APP_ENV):
        val = os.environ.get(key, "").strip()
        if val:
            env[key] = val
    return env


def _validate() -> tuple[str, str]:
    """필수 환경변수를 검증하고 (api_key, image) 를 돌려준다."""
    missing = [
        k
        for k in ("RUNPOD_API_KEY", "API_DOCKER_IMAGE", *_REQUIRED_APP_ENV)
        if not os.environ.get(k, "").strip()
    ]
    if missing:
        sys.exit(f"[ERROR] 필수 환경변수가 없습니다: {', '.join(missing)}")
    return (
        os.environ["RUNPOD_API_KEY"].strip(),
        os.environ["API_DOCKER_IMAGE"].strip(),
    )


def create_pod(api_key: str, image: str, env: dict[str, str]) -> dict:
    """Secure Cloud CPU Pod 를 생성하고 응답(JSON)을 돌려준다."""
    payload = {
        "name": os.environ.get("POD_NAME", "mongle-ai-api").strip(),
        "computeType": "CPU",
        "cloudType": "SECURE",
        "imageName": image,
        # cpu3g-2-8 = 3GHz General Purpose, 2 vCPU / 8GB ($0.08/hr) — 콘솔 확인값
        "cpuFlavorIds": [os.environ.get("CPU_FLAVOR", "cpu3g-2-8").strip()],
        "vcpuCount": int(os.environ.get("VCPU_COUNT", "2")),
        "containerDiskInGb": 20,
        "ports": [f"{_HTTP_PORT}/http"],
        "env": env,
    }
    try:
        resp = httpx.post(
            _REST_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as err:
        sys.exit(f"[ERROR] Pod 생성 실패 ({err.response.status_code}): {err.response.text}")
    except httpx.HTTPError as err:
        sys.exit(f"[ERROR] Pod 생성 요청 실패: {err}")
    return resp.json()


def main() -> None:
    api_key, image = _validate()
    env = _collect_env()

    print(f"CPU Pod 생성 중 — image={image}, 주입 env {len(env)}개")
    pod = create_pod(api_key, image, env)

    pod_id = pod.get("id")
    if not pod_id:
        sys.exit(f"[ERROR] 응답에 Pod id 가 없습니다: {pod}")

    proxy_url = f"https://{pod_id}-{_HTTP_PORT}.proxy.runpod.net"
    print("\n" + "=" * 60)
    print(f"Pod 생성 완료: {pod_id}")
    print(f"프록시 URL  : {proxy_url}")
    print("=" * 60)
    print("\n1) GitHub Secret 에 등록 (CI 재배포용):")
    print(f"   RUNPOD_POD_ID={pod_id}")
    print("\n2) mongle-server 환경에 설정:")
    print(f"   MONGLE_AI_API_BASE={proxy_url}")
    print(f"\n3) 헬스 확인: curl {proxy_url}/health")
    print("=" * 60)


if __name__ == "__main__":
    main()
