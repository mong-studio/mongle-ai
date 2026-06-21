"""캐릭터 생성 비동기 잡의 프로세스 인메모리 스토어.

RunPod Pod 프록시의 100s 하드 타임아웃을 넘는 이미지 생성을 백그라운드로
분리하기 위해, /v1/character 를 submit(202)+poll(GET) 구조로 운영한다.

uvicorn 단일 워커를 가정한다. 프로세스 재시작 시 진행 중 잡은 유실되며,
호출자(Django Celery)가 폴링 타임아웃으로 FAILED 처리 후 재시도한다.
새 DB/Redis 의존성은 두지 않는다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from enum import Enum
from uuid import uuid4

from agents.character_creation.schemas import CharacterEntity


class JobState(str, Enum):
    PENDING = "pending"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class CharacterJob:
    job_id: str
    state: JobState = JobState.PENDING
    result: CharacterEntity | None = None
    error_code: str | None = None
    error_message: str | None = None


class CharacterJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, CharacterJob] = {}
        # 백그라운드 태스크의 GC 를 막기 위한 강참조 보관소.
        self._tasks: set[asyncio.Task] = set()

    def create(self) -> str:
        job_id = uuid4().hex
        self._jobs[job_id] = CharacterJob(job_id=job_id)
        return job_id

    def get(self, job_id: str) -> CharacterJob | None:
        return self._jobs.get(job_id)

    def mark_done(self, job_id: str, result: CharacterEntity) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        self._jobs[job_id] = replace(job, state=JobState.DONE, result=result)

    def mark_error(self, job_id: str, *, code: str, message: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        self._jobs[job_id] = replace(
            job, state=JobState.ERROR, error_code=code, error_message=message
        )

    def track_task(self, task: asyncio.Task) -> None:
        """detached 백그라운드 태스크를 GC 로부터 보호한다."""
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
