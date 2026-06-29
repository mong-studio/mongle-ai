from __future__ import annotations

import asyncio
import base64
import random
import time
from typing import Any

import httpx

from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.schemas import ImageGenerationResult, LLMPersonaResult

_TERMINAL_FAILURE_STATUSES = ("FAILED", "CANCELLED", "TIMED_OUT")
_HTTP_TIMEOUT = 30.0
_MAX_CONSECUTIVE_POLL_ERRORS = 3
_ERROR_DETAIL_MAX_LEN = 200


class RunPodImageGenerator:
    """ImageGeneratorPort 구현체 — RunPod Serverless 이미지 생성 워커 호출.

    /run 으로 잡을 제출하고 /status/{id} 를 폴링한다. 콜드스타트(모델 로드)가
    수 분 걸릴 수 있어 동기식 /runsync 대신 폴링 방식을 쓴다.
    """

    def __init__(
        self,
        *,
        endpoint_url: str,
        api_key: str,
        poll_interval: float = 2.0,
        timeout: float = 600.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url.rstrip("/")
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._client = client

    async def generate(
        self,
        *,
        user_id: str,
        llm_result: LLMPersonaResult,
        fallback_persona: str | None,
        source_image_bytes: bytes | None = None,
    ) -> ImageGenerationResult:
        # 사진이 없으면 워커가 이 prompt 로 text2img 한다(사진 있으면 무시·img2img).
        prompt = (llm_result.appearance_en or llm_result.appearance or fallback_persona or "").strip() or None
        try:
            mode = "image_character" if source_image_bytes is not None else "text_character"
            return await self._submit_and_poll(
                mode=mode,
                source_image_bytes=source_image_bytes,
                prompt=prompt,
            )
        except ImageGenerationFailedError:
            raise
        except Exception as err:
            raise ImageGenerationFailedError(
                f"[ERROR] RunPod image generation failed: {err}"
            ) from err

    async def generate_feed(
        self,
        reference_url: str,
        character_prompt: str,
        scene_prompt: str,
        appearance_payload: dict[str, Any] | None = None,
    ) -> bytes:
        """피드: reference 이미지 기반 5단계 feed 모드(adapter="feed").

        character_prompt(캐릭터 포즈)와 scene_prompt(배경 장면)를 워커로 보내
        캐릭터 img2img→배경→합성→블렌딩까지 마친 완성 PNG를 받는다.
        """
        if not appearance_payload:
            raise ImageGenerationFailedError(
                "[ERROR] v2 feed generation requires character.appearance_payload"
            )
        try:
            result = await self._submit_and_poll(
                mode="feed",
                prompt=character_prompt,
                scene_prompt=scene_prompt,
                appearance_payload=appearance_payload,
            )
            return result.image_bytes
        except ImageGenerationFailedError:
            raise
        except Exception as err:
            raise ImageGenerationFailedError(
                f"[ERROR] RunPod feed 생성 실패: {err}"
            ) from err

    async def _submit_and_poll(
        self,
        *,
        mode: str,
        source_image_bytes: bytes | None = None,
        prompt: str | None = None,
        scene_prompt: str | None = None,
        appearance_payload: dict[str, Any] | None = None,
    ) -> ImageGenerationResult:
        source_b64 = (
            base64.b64encode(source_image_bytes).decode()
            if source_image_bytes is not None
            else None
        )
        # 워커 핸들러는 seed 가 없으면 42로 고정해버려서, 매 요청마다 새 시드를 보내야
        # 한다(고정 시드 + LCM 의 낮은 guidance_scale 조합은 프롬프트와 무관하게 같은
        # 캐릭터로 수렴함).
        job_input: dict[str, Any] = {"mode": mode, "seed": random.randint(0, 2**32 - 1)}
        if mode == "image_character":
            job_input["image"] = source_b64
            job_input["source_image_b64"] = source_b64
        elif mode == "text_character":
            job_input["persona"] = prompt or ""
            job_input["prompt"] = prompt or ""
        elif mode == "feed":
            job_input["appearance"] = appearance_payload
            job_input["quest_ko"] = scene_prompt
            job_input["prompt"] = prompt
        else:
            raise ImageGenerationFailedError(f"[ERROR] unsupported image mode: {mode}")
        payload = {
            "input": job_input
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            run_resp = await client.post(
                f"{self._endpoint_url}/run",
                json=payload,
                headers=headers,
                timeout=_HTTP_TIMEOUT,
            )
            run_resp.raise_for_status()
            job_id = run_resp.json()["id"]

            deadline = time.monotonic() + self._timeout
            poll_errors = 0
            while True:
                try:
                    status_resp = await client.get(
                        f"{self._endpoint_url}/status/{job_id}",
                        headers=headers,
                        timeout=_HTTP_TIMEOUT,
                    )
                    status_resp.raise_for_status()
                except httpx.HTTPError:
                    # 일시적 네트워크 단절·5xx 는 연속 한도까지 견딘다
                    poll_errors += 1
                    if poll_errors >= _MAX_CONSECUTIVE_POLL_ERRORS:
                        await self._cancel_job(client, headers, job_id)
                        raise
                    if time.monotonic() >= deadline:
                        await self._cancel_job(client, headers, job_id)
                        raise ImageGenerationFailedError(
                            f"[ERROR] RunPod job 폴링이 {self._timeout}s 를 초과했습니다"
                        )
                    await asyncio.sleep(self._poll_interval)
                    continue

                poll_errors = 0
                data = status_resp.json()
                status = data.get("status")

                if status == "COMPLETED":
                    output = data.get("output") or {}
                    if output.get("status") == "failed":
                        detail = str(output.get("error"))[:_ERROR_DETAIL_MAX_LEN]
                        raise ImageGenerationFailedError(
                            f"[ERROR] RunPod worker failed: {detail}"
                        )
                    image_b64 = output.get("image") or output.get("image_b64")
                    if not image_b64:
                        raise ImageGenerationFailedError(
                            "[ERROR] RunPod COMPLETED 응답에 output.image_b64 가 없습니다"
                        )
                    return ImageGenerationResult(
                        image_bytes=base64.b64decode(image_b64),
                        appearance_payload=output.get("appearance"),
                    )

                if status in _TERMINAL_FAILURE_STATUSES:
                    detail = str(data.get("error"))[:_ERROR_DETAIL_MAX_LEN]
                    raise ImageGenerationFailedError(
                        f"[ERROR] RunPod job {status}: {detail}"
                    )

                if time.monotonic() >= deadline:
                    await self._cancel_job(client, headers, job_id)
                    raise ImageGenerationFailedError(
                        f"[ERROR] RunPod job 폴링이 {self._timeout}s 를 초과했습니다"
                    )
                await asyncio.sleep(self._poll_interval)
        finally:
            if owns_client:
                await client.aclose()

    async def _cancel_job(
        self, client: httpx.AsyncClient, headers: dict[str, str], job_id: str
    ) -> None:
        """폴링 포기 시 RunPod 잡 취소 - GPU 중복 과금 방지 (best-effort).

        취소 실패가 원래 에러를 가리면 안 되므로 예외는 모두 삼킨다.
        """
        try:
            await client.post(
                f"{self._endpoint_url}/cancel/{job_id}",
                headers=headers,
                timeout=_HTTP_TIMEOUT,
            )
        except Exception:  # noqa: BLE001
            pass
