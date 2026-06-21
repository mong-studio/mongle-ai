"""RunPod Serverless 공용 호출 — /run 제출 후 /status 폴링.

세 LLM 어댑터(todo·quest·character)가 공유하는 전송 계층.
비즈니스 로직은 각 어댑터(QwenLLM 서브클래스)에, 비동기 job 큐 전송만 여기에 둔다.
"""
from __future__ import annotations

import asyncio
import time

import httpx

_HTTP_TIMEOUT = 30.0
_MAX_CONSECUTIVE_POLL_ERRORS = 3
_TERMINAL_STATUSES = frozenset({"FAILED", "CANCELLED", "TIMED_OUT"})


class RunPodJobError(RuntimeError):
    """RunPod job 제출·폴링·터미널 상태·타임아웃 실패.

    각 어댑터가 자기 도메인의 LLMFailedError 로 변환한다.
    """


async def run_and_poll(
    *,
    endpoint_url: str,
    api_key: str,
    payload: dict,
    label: str,
    poll_interval: float = 2.0,
    poll_timeout: float = 300.0,
) -> dict:
    """RunPod Serverless 엔드포인트에 job 을 제출하고 완료까지 폴링해 output 을 반환.

    성공 시 COMPLETED 응답의 ``output`` 딕셔너리를 돌려준다(없으면 빈 dict).
    제출 실패·연속 폴 실패·터미널 상태·타임아웃은 RunPodJobError 로 던진다.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    base = endpoint_url.rstrip("/")

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        try:
            run_resp = await client.post(f"{base}/run", json=payload, headers=headers)
            run_resp.raise_for_status()
            job_id = run_resp.json()["id"]
        except httpx.HTTPError as err:
            raise RunPodJobError(f"RunPod job submit failed [{label}]: {err}") from err

        deadline = time.monotonic() + poll_timeout
        poll_errors = 0
        while True:
            try:
                status_resp = await client.get(
                    f"{base}/status/{job_id}", headers=headers, timeout=_HTTP_TIMEOUT
                )
                status_resp.raise_for_status()
            except httpx.HTTPError:
                poll_errors += 1
                if poll_errors >= _MAX_CONSECUTIVE_POLL_ERRORS:
                    raise RunPodJobError(f"RunPod poll failed repeatedly [{label}]")
                await asyncio.sleep(poll_interval)
                continue

            poll_errors = 0
            data = status_resp.json()
            status = data.get("status")

            if status == "COMPLETED":
                return data.get("output") or {}
            if status in _TERMINAL_STATUSES:
                detail = str(data.get("error") or "")[:200]
                raise RunPodJobError(f"RunPod job {status} [{label}]: {detail}")
            if time.monotonic() >= deadline:
                raise RunPodJobError(f"RunPod job timed out [{label}] ({poll_timeout}s)")
            await asyncio.sleep(poll_interval)
