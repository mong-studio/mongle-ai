"""RunPod Serverless 예열 — 콜드(워커 0개)일 때만 더미 job 1건으로 워커를 깨운다.

워커가 이미 떠 있거나 꽉 차 있으면 아무것도 하지 않는다(health-gate). 그래야 실제
요청 슬롯을 뺏거나 중복 비용을 내지 않는다. 예열은 best-effort 라 모든 실패는
비치명적으로 삼킨다(로깅만).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10.0
# 워커가 "살아있다"고 볼 상태들. 하나라도 있으면 콜드가 아니므로 예열 생략.
_WARM_KEYS = ("idle", "ready", "running", "initializing")

_LLM_WARM_PAYLOAD = {
    "input": {
        "adapter": "character",
        "messages": [{"role": "user", "content": "warm"}],
        "max_tokens": 1,
    }
}
# ponytail: 이미지 워커는 num_inference_steps 를 내부 고정 → 콜드 예열 1건 = 이미지
# 1장 비용(상한). 입력이 부실해도 워커 컨테이너는 부팅되므로 예열 목적은 달성된다.
_IMAGE_WARM_PAYLOAD = {
    "input": {"adapter": "character", "prompt": "warm", "source_image_b64": ""}
}


async def _is_cold(client: httpx.AsyncClient, base: str, headers: dict) -> bool:
    resp = await client.get(f"{base}/health", headers=headers)
    resp.raise_for_status()
    workers = resp.json().get("workers") or {}
    return sum(int(workers.get(k, 0) or 0) for k in _WARM_KEYS) == 0


async def _warm_one(
    client: httpx.AsyncClient,
    endpoint_url: str,
    api_key: str,
    payload: dict,
    label: str,
) -> None:
    base = endpoint_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        if not await _is_cold(client, base, headers):
            log.info("warmup skip — 이미 워커 있음: %s", label)
            return
        resp = await client.post(f"{base}/run", json=payload, headers=headers)
        resp.raise_for_status()
        log.info("warmup fired: %s job=%s", label, resp.json().get("id"))
    except Exception:
        log.warning("warmup failed (non-fatal): %s", label, exc_info=True)


async def warm_character_endpoints(
    *,
    llm_url: str | None,
    image_url: str | None,
    api_key: str,
    client: httpx.AsyncClient | None = None,
) -> None:
    """캐릭터 생성용 LLM·이미지 엔드포인트를 콜드일 때만 병렬 예열(best-effort)."""
    own = client is None
    c = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
    try:
        targets = (
            (llm_url, _LLM_WARM_PAYLOAD, "character-llm"),
            (image_url, _IMAGE_WARM_PAYLOAD, "character-image"),
        )
        tasks = [
            _warm_one(c, url, api_key, payload, label)
            for url, payload, label in targets
            if url
        ]
        if tasks:
            await asyncio.gather(*tasks)
    finally:
        if own:
            await c.aclose()
