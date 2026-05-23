# Data

원본 데이터는 git에 커밋하지 않고 **S3 비공개 버킷**에 보관합니다.
`data/manifest.json`이 진실의 원천이며, `path`(로컬) ↔ `s3_key`(원격) 매핑과 무결성 검증용 sha256을 담습니다.

## 디렉토리

```
data/
├── raw/          # 원본 (S3 동기화, gitignore됨)
├── interim/      # 전처리 중간 산출물 (재생성 가능, gitignore됨)
├── processed/    # 최종 산출물 (재생성 가능, gitignore됨)
└── manifest.json # raw/ 의 S3 매니페스트 (git에 커밋)
```

## 설정

1. `.env.example`을 `.env`로 복사하고 `AWS_REGION`, `AWS_S3_BUCKET`, `AWS_S3_PREFIX`를 채웁니다.
2. AWS 자격증명은 `aws configure` 프로파일 사용을 권장합니다 (`.env`에 키 하드코딩 금지).
3. 의존성: `pip install -e .` (`boto3` 포함됨).

## 사용

```bash
# 환경변수 로드 후
python -m ingestion.s3_sync push   # data/raw/ → S3, 매니페스트 갱신
python -m ingestion.s3_sync pull   # 매니페스트 기준 S3 → data/raw/
```

`push`는 `data/raw/` 안의 모든 파일을 업로드하고 매니페스트를 다시 작성합니다.
`pull`은 이미 같은 sha256인 로컬 파일은 건너뜁니다.
