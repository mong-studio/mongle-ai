from __future__ import annotations

import httpx

from adapters._shared.runpod_warmup import warm_character_endpoints

LLM = "https://api.runpod.ai/v2/llm-ep"
IMG = "https://api.runpod.ai/v2/img-ep"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_warms_only_cold_endpoints() -> None:
    """콜드(워커 0)인 엔드포인트만 /run, 떠 있는 엔드포인트는 건너뛴다."""
    runs: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if req.url.path.endswith("/health"):
            cold = {"idle": 0, "ready": 0, "running": 0, "initializing": 0}
            warm = {"idle": 1}
            return httpx.Response(200, json={"workers": cold if "llm-ep" in url else warm})
        if req.url.path.endswith("/run"):
            runs.append(url)
            return httpx.Response(200, json={"id": "job-1"})
        return httpx.Response(404)

    async with _client(handler) as c:
        await warm_character_endpoints(llm_url=LLM, image_url=IMG, api_key="k", client=c)

    assert any("llm-ep" in u for u in runs)  # 콜드 → 예열
    assert not any("img-ep" in u for u in runs)  # 워커 있음 → 생략


async def test_no_run_when_all_warm() -> None:
    """워커가 꽉 차 있거나 떠 있으면 아무 잡도 던지지 않는다(슬롯 경합 방지)."""
    runs: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/health"):
            return httpx.Response(200, json={"workers": {"running": 1}})
        if req.url.path.endswith("/run"):
            runs.append(str(req.url))
            return httpx.Response(200, json={"id": "x"})
        return httpx.Response(404)

    async with _client(handler) as c:
        await warm_character_endpoints(llm_url=LLM, image_url=IMG, api_key="k", client=c)

    assert runs == []


async def test_health_error_is_non_fatal() -> None:
    """health 실패는 예열을 막지 않고 조용히 삼킨다(best-effort)."""
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/health"):
            return httpx.Response(500)
        return httpx.Response(200, json={"id": "x"})

    async with _client(handler) as c:
        await warm_character_endpoints(llm_url=LLM, image_url=None, api_key="k", client=c)
