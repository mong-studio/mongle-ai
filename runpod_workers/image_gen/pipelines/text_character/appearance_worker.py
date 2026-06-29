"""Short-lived appearance-extraction worker.

생성된 픽셀아트 이미지를 입력받아 Qwen2-VL 로 외형 JSON 을 추출한다.
이 모듈을 **별도 프로세스**로 실행하면, 작업이 끝나 프로세스가 종료될 때 OS 가
VLM 의 VRAM 을 전량 회수한다 → in-process load/unload 의 VRAM 누수를 원천 차단한다.
(피드의 pipelines.feed.vlm_worker 와 동일한 격리 패턴)

stdout 의 **마지막 줄**에 외형 JSON 을 출력한다. 진단 로그는 stderr 로 보낸다.
"""

from __future__ import annotations

import json
import sys


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> None:
    if len(sys.argv) != 2:
        log("usage: python -m pipelines.text_character.appearance_worker <image_path>")
        raise SystemExit(1)

    from PIL import Image

    # VLM 로드/추출/해제 로직은 pipeline.py 에 단일 정의돼 있어 그대로 재사용한다.
    # (torch/transformers 는 그 함수들 안에서 지연 import 되므로 import 시점엔 안 올라온다.)
    from pipelines.text_character.pipeline import (
        extract_appearance,
        load_qwen,
        unload_qwen,
    )

    image = Image.open(sys.argv[1]).convert("RGB")
    model, proc = load_qwen(allow_cpu_offload=True)
    try:
        appearance_raw = extract_appearance(image, model, proc)
    finally:
        unload_qwen(model, proc)

    print(json.dumps(appearance_raw, ensure_ascii=False))


if __name__ == "__main__":
    main()
