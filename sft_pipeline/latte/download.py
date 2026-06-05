"""MS-LaTTE 원본 데이터 재현용 다운로드.

커밋 SHA를 고정해 언제든 동일 파일을 재취득한다(버전 표류 방지).
원본은 MIT 라이선스이며 git에는 포함하지 않는다(data/sources/ 는 .gitignore).
출처: https://github.com/microsoft/MS-LaTTE (MIT License)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import requests

# 고정 커밋 SHA - 재현성을 위해 변경 시 의도적으로 갱신할 것.
PINNED_SHA = "78a8e8728e7ecc8173e69ab37ae0512f1cb8fa4a"
SOURCE_URL = f"https://raw.githubusercontent.com/microsoft/MS-LaTTE/{PINNED_SHA}/MS-LaTTE.json"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "sources" / "ms_latte.json"


def download(out_path: Path = DEFAULT_OUT, *, timeout: float = 60.0) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(SOURCE_URL, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"MS-LaTTE 다운로드 실패: {exc}") from exc
    out_path.write_bytes(resp.content)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="MS-LaTTE.json 다운로드(SHA 고정)")
    parser.add_argument("--out", dest="out_path", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    path = download(args.out_path)
    size_mb = path.stat().st_size / 1_000_000
    print(f"downloaded MS-LaTTE.json ({size_mb:.1f} MB) -> {path}")


if __name__ == "__main__":
    main()
