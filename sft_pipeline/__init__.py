"""SFT 파이프라인 패키지.

임포트 시 레포 루트의 단일 `.env` 를 1회 로드한다(API 서비스와 동일한 파일을 공용).
이미 설정된 환경변수(셸 export·CI 등)는 보존한다(override=False).
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
