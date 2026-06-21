from __future__ import annotations

import base64
import json

import httpx
import pytest

from adapters.character_creation.runpod_image import RunPodImageGenerator
from agents.character_creation.exceptions import ImageGenerationFailedError
from agents.character_creation.schemas import LLMPersonaResult

ENDPOINT = "https://api.runpod.ai/v2/test-endpoint"
PNG = b"\x89PNG-fake-image-bytes"
PNG_B64 = base64.b64encode(PNG).decode()


def _generator(handler, **over) -> RunPodImageGenerator:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs = dict(
        endpoint_url=ENDPOINT,
        api_key="rp-test-key",
        poll_interval=0.0,
        timeout=5.0,
        client=client,
    )
    kwargs.update(over)
    return RunPodImageGenerator(**kwargs)


def _persona(appearance: str = "둥근 갈색 곰") -> LLMPersonaResult:
    return LLMPersonaResult(
        personality="p", speech_style="s", background="b", appearance=appearance
    )


async def _call(
    gen: RunPodImageGenerator,
    source: bytes | None = None,
    appearance: str = "둥근 갈색 곰",
) -> bytes:
    return await gen.generate(
        user_id="u1",
        llm_result=_persona(appearance),
        fallback_persona=None,
        source_image_bytes=source,
    )


@pytest.mark.asyncio
async def test_generate_completed_returns_decoded_bytes() -> None:
    """COMPLETED 응답의 image_b64 를 디코드한 bytes 를 반환한다."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1", "status": "IN_QUEUE"})
        return httpx.Response(
            200, json={"status": "COMPLETED", "output": {"image_b64": PNG_B64}}
        )

    result = await _call(_generator(handler))

    assert result == PNG
    assert requests[0].url == httpx.URL(f"{ENDPOINT}/run")
    assert requests[1].url == httpx.URL(f"{ENDPOINT}/status/job-1")


@pytest.mark.asyncio
async def test_generate_sends_bearer_auth_header() -> None:
    """모든 요청에 Bearer 인증 헤더를 보낸다."""
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(
            200, json={"status": "COMPLETED", "output": {"image_b64": PNG_B64}}
        )

    await _call(_generator(handler))

    assert seen_auth == ["Bearer rp-test-key", "Bearer rp-test-key"]


@pytest.mark.asyncio
async def test_generate_without_source_sends_null_b64() -> None:
    """source 이미지가 없으면 source_image_b64 를 null 로 보낸다."""
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(
            200, json={"status": "COMPLETED", "output": {"image_b64": PNG_B64}}
        )

    await _call(_generator(handler), source=None)

    assert payloads == [
        {
            "input": {
                "source_image_b64": None,
                "adapter": "character",
                "prompt": "둥근 갈색 곰",
            }
        }
    ]


@pytest.mark.asyncio
async def test_generate_sends_appearance_as_prompt() -> None:
    """LLM 의 appearance 묘사를 워커 text2img 용 prompt 로 보낸다."""
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(
            200, json={"status": "COMPLETED", "output": {"image_b64": PNG_B64}}
        )

    await _call(_generator(handler), appearance="별빛 같은 은색 여우")

    assert payloads[0]["input"]["prompt"] == "별빛 같은 은색 여우"


@pytest.mark.asyncio
async def test_generate_sends_character_adapter() -> None:
    """멀티-어댑터 이미지 워커가 모드를 고르도록 input.adapter='character' 를 보낸다."""
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(
            200, json={"status": "COMPLETED", "output": {"image_b64": PNG_B64}}
        )

    await _call(_generator(handler), source=b"x")

    assert payloads[0]["input"]["adapter"] == "character"


@pytest.mark.asyncio
async def test_generate_with_source_sends_base64_payload() -> None:
    """source 이미지가 있으면 base64 로 인코딩해 보낸다."""
    source = b"source-image-bytes"
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(
            200, json={"status": "COMPLETED", "output": {"image_b64": PNG_B64}}
        )

    await _call(_generator(handler), source=source)

    sent = payloads[0]["input"]["source_image_b64"]
    assert base64.b64decode(sent) == source


@pytest.mark.asyncio
async def test_generate_polls_until_completed() -> None:
    """IN_PROGRESS 동안 폴링을 계속하다 COMPLETED 에서 반환한다."""
    statuses = iter(["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        status = next(statuses)
        body: dict = {"status": status}
        if status == "COMPLETED":
            body["output"] = {"image_b64": PNG_B64}
        return httpx.Response(200, json=body)

    result = await _call(_generator(handler))

    assert result == PNG


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["FAILED", "CANCELLED", "TIMED_OUT"])
async def test_generate_terminal_failure_status_raises(status: str) -> None:
    """터미널 실패 상태면 ImageGenerationFailedError 를 던진다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(200, json={"status": status, "error": "CUDA OOM"})

    with pytest.raises(ImageGenerationFailedError):
        await _call(_generator(handler))


@pytest.mark.asyncio
async def test_generate_tolerates_transient_poll_errors() -> None:
    """폴링 중 일시적 5xx 는 견디고 다음 폴링에서 회복한다."""
    status_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        status_calls["n"] += 1
        if status_calls["n"] <= 2:
            return httpx.Response(503)
        return httpx.Response(
            200, json={"status": "COMPLETED", "output": {"image_b64": PNG_B64}}
        )

    result = await _call(_generator(handler))

    assert result == PNG


@pytest.mark.asyncio
async def test_generate_poll_errors_exhausted_cancels_and_raises() -> None:
    """폴링 오류가 연속 한도를 넘으면 잡을 취소하고 에러를 던진다."""
    cancel_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        if "/cancel/" in request.url.path:
            cancel_paths.append(request.url.path)
            return httpx.Response(200, json={})
        return httpx.Response(503)

    with pytest.raises(ImageGenerationFailedError):
        await _call(_generator(handler))

    assert cancel_paths == ["/v2/test-endpoint/cancel/job-1"]


@pytest.mark.asyncio
async def test_generate_http_error_raises() -> None:
    """HTTP 5xx 응답이면 ImageGenerationFailedError 로 감싼다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal"})

    with pytest.raises(ImageGenerationFailedError):
        await _call(_generator(handler))


@pytest.mark.asyncio
async def test_generate_missing_image_b64_raises() -> None:
    """COMPLETED 인데 output.image_b64 가 없으면 에러를 던진다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(200, json={"status": "COMPLETED", "output": {}})

    with pytest.raises(ImageGenerationFailedError):
        await _call(_generator(handler))


@pytest.mark.asyncio
async def test_generate_poll_timeout_cancels_and_raises() -> None:
    """폴링이 timeout 을 넘기면 잡을 취소하고 ImageGenerationFailedError 를 던진다."""
    cancel_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        if "/cancel/" in request.url.path:
            cancel_paths.append(request.url.path)
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"status": "IN_PROGRESS"})

    with pytest.raises(ImageGenerationFailedError):
        await _call(_generator(handler, timeout=0.0))

    assert cancel_paths == ["/v2/test-endpoint/cancel/job-1"]


@pytest.mark.asyncio
async def test_generate_cancel_failure_does_not_mask_original_error() -> None:
    """취소 호출 자체가 실패해도 원래 에러가 그대로 전달된다(best-effort)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-1"})
        if "/cancel/" in request.url.path:
            return httpx.Response(500)
        return httpx.Response(200, json={"status": "IN_PROGRESS"})

    with pytest.raises(ImageGenerationFailedError, match="초과"):
        await _call(_generator(handler, timeout=0.0))
