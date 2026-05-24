from __future__ import annotations

from typing import Any

from agents.character_creation.exceptions import S3UploadFailedError
from agents.character_creation.nodes.image_upload import key_for, put_once
from agents.character_creation.state import CharacterGraphState

MAX_ATTEMPTS = 4


async def generated_upload_node(
    state: CharacterGraphState, config: dict[str, Any]
) -> dict[str, Any]:
    # in-node 루프인 이유: 실패 시 RetryPolicy 가 raise 하면 conditional_edges 가
    # cleanup_source_image 로 라우팅할 수 없어 이미 올라간 source_image 가 leak 된다.
    # state["error"] 반환으로 _ok_or_cleanup 분기가 작동하게 한다.
    ports = config["configurable"]["ports"]
    image_bytes = state.get("image_bytes")
    assert image_bytes is not None
    key = key_for(state["input"].user_id, "image/png", prefix="characters")
    last_err: S3UploadFailedError | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            url = await put_once(
                ports.s3, key=key, body=image_bytes, content_type="image/png"
            )
            return {"generated_url": url}
        except S3UploadFailedError as err:
            last_err = err
            continue
    assert last_err is not None
    return {"error": last_err}
