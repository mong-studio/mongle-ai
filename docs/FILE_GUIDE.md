# 몽글마을 파일 구조 가이드

> "이 파일 왜 있어?" 싶을 때 여기서 찾으세요.

---

## 한눈에 보는 전체 구조

```
mongle-ai/
├── streamlit_app/       ← 화면 (UI)
├── agents/              ← AI 두뇌 (파이프라인 로직)
├── adapters/            ← AI 두뇌가 외부와 연결되는 플러그
├── src/                 ← 유틸리티 스크립트
├── tests/               ← 테스트
├── docs/                ← 문서
├── notebooks/           ← 개발용 시각화
└── data/                ← 로컬 저장소 / S3 매니페스트
```

---

## streamlit_app/ — 화면

| 파일 | 역할 |
|---|---|
| `app.py` | 앱 진입점. 모든 화면(캐릭터, TODO, 퀘스트, 피드 등)이 여기에 있음 |
| `ports_factory.py` | 환경변수 읽어서 AI 모델·저장소를 골라 연결해주는 설정 공장 |
| `styles/*.css` | 화면별 CSS (sidebar, feed, calendar, todo, ...) |

---

## agents/ — AI 파이프라인

> 각 피처마다 동일한 구조를 반복합니다.

### 공통 파일 패턴 (모든 피처에 동일하게 존재)

| 파일 | 역할 | 비유 |
|---|---|---|
| `schemas.py` | 데이터 모양 정의 (입력/출력 타입) | 서류 양식 |
| `protocols.py` | AI·저장소가 지켜야 할 인터페이스 정의 | 계약서 |
| `state.py` | 파이프라인이 단계별로 들고 다니는 임시 데이터 | 바통 |
| `pipeline.py` | 노드 연결 구조 정의 + 실제 실행 진입점. `build_graph()`와 `run()` 함수 제공 | 레시피 + 요리사 |
| `exceptions.py` | 이 피처에서 발생하는 에러 종류 | 에러 분류표 |
| `debug.py` | 개발용 로그 출력 | 디버그 프린터 |
| `nodes/` | 파이프라인의 각 단계 구현 | 레시피 각 단계 |


### 피처별 nodes/ 파일들

**character_creation/nodes/**

| 파일 | 하는 일 |
|---|---|
| `validate.py` | 입력값 검증 |
| `llm_persona.py` | LLM으로 캐릭터 성격 생성 |
| `vlm_analyzer.py` | VLM으로 업로드 이미지 분석 |
| `_upload_utils.py` | 이미지 업로드 공통 유틸 (source_upload, generated_upload가 공유) |
| `source_upload.py` | 원본 이미지 S3 업로드 |
| `image_generator.py` | LoRA로 캐릭터 이미지 생성 |
| `generated_upload.py` | 생성된 이미지 S3 업로드 |
| `builder.py` | 최종 캐릭터 엔티티 조립 |
| `cleanup.py` | 에러 시 S3 원본 이미지 삭제 (보상 트랜잭션) |

**todo_creation/** — single_turn vs multi_turn vs commit 3개로 나뉨

| 폴더 | 언제 쓰임 |
|---|---|
| `single_turn/` | 한 번에 TODO 생성 |
| `multi_turn/` | 대화형으로 TODO 생성 (follow-up 질문 포함) |
| `commit/` | 완료된 TODO를 저장하고 퀘스트 달성 체크 |

**todo_creation/middleware/**

| 파일 | 하는 일 |
|---|---|
| `trace_callback.py` | LangChain 콜백 기반 트레이스 로거. 현재 앱에서 직접 사용되지 않음 |

---

## adapters/ — 외부 연결 플러그

> `agents/`의 `protocols.py`에 정의된 인터페이스를 실제로 구현한 것들.
> "어떤 LLM을 쓸지" 교체할 때 여기만 바꾸면 됨.

**character_creation/**

| 파일 | 역할 |
|---|---|
| `openai_llm.py` | OpenAI GPT로 캐릭터 성격 생성 |
| `qwen_llm.py` | Qwen 7B로 캐릭터 성격 생성 |
| `openai_vlm.py` | GPT-4o Vision으로 이미지 분석 |
| `lora_image.py` | LoRA 모델로 캐릭터 이미지 생성 (현재 사용 중) |
| `memory_repo.py` | 인메모리 캐릭터 저장소 (앱 실행 중 상태 유지용) |
| `local_storage.py` | 로컬 파일 저장 (개발용, S3 대체) |
| `s3_storage.py` | S3 실제 저장 |
| `_prompts.py` | 이 어댑터에서 쓰는 프롬프트 조각 |

**quest_generation/**

| 파일 | 역할 |
|---|---|
| `openai_llm.py` | OpenAI로 퀘스트 텍스트 생성 |
| `qwen_llm.py` | Qwen 7B로 퀘스트 텍스트 생성 |
| `memory_repo.py` | 인메모리 저장소 (todo·character·quest 조회용) |

**todo_creation/**

| 파일 | 역할 |
|---|---|
| `qwen_llm.py` | Qwen 7B로 TODO 생성 |
| `memory_repo.py` | 인메모리 TODO 저장소 |
| `memory_quest_counter.py` | 인메모리 퀘스트 카운터 |
| `quest_dispatch_adapter.py` | TODO 완료 시 퀘스트 생성 파이프라인 연결 |

**feed_generation/**

| 파일 | 역할 |
|---|---|
| `qwen_llm.py` | Qwen 7B로 피드 캡션 생성. 파이프라인은 완성됐으나 현재 앱 UI에 미연결 |

---

## src/ — 유틸리티

| 파일 | 역할 |
|---|---|
| `ingestion/s3_sync.py` | 로컬 `data/raw/` ↔ S3 동기화 스크립트. `python -m ingestion.s3_sync push/pull`로 수동 실행 |
| `prompts/*/` | 마크다운으로 작성된 프롬프트 템플릿 |

---

## tests/ — 테스트

`agents/`와 `adapters/`의 구조를 그대로 미러링.

| 파일 패턴 | 역할 |
|---|---|
| `fakes.py` | 테스트용 가짜 구현체 |
| `conftest.py` | pytest 공통 픽스처 |
| `test_*.py` | 각 모듈 단위 테스트 |

---

## 루트 문서 파일들

| 파일 | 상태 | 설명 |
|---|---|---|
| `CLAUDE.md` | 현행 | Claude Code 작업 가이드 (라우팅 허브) |
| `README.md` | 현행 | 프로젝트 소개 |
| `CHANGELOG.md` | 현행 | 변경 이력 |
| `AGENTS.md` | 구버전 | CLAUDE.md의 구버전 (Codex 기준). 내부 링크 깨짐. 제거 검토 필요 |
| `CLAUDE_CODE_WORKFLOW.md` | 참고용 | Claude Code 작업 후기. 운영 문서 아님 |

---

## data/ 폴더

| 경로 | 설명 |
|---|---|
| `data/manifest.json` | S3에 올라간 파일 목록 (s3_sync가 관리) |
| `data/local_storage/` | LocalStorage 어댑터가 저장하는 폴더. `.gitignore` 대상 |
| `data/raw/` | S3에 올릴 원본 데이터 (`.gitignore` 대상) |

---

## notebooks/ 폴더

LangGraph 파이프라인 구조를 시각화하는 Jupyter 노트북. CI와 무관한 개발용 도구.

---

## 정리: 헷갈리는 것들 FAQ

**Q. `openai_llm.py`가 adapters에도 있고 여러 피처에도 있는데?**
A. 피처마다 입출력 타입이 달라서 각각 별도 구현. 이름은 같아도 내용이 다름.

**Q. `tests/*/fake_llm.py`나 `tests/*/fakes.py`는 왜 있어?**
A. 테스트할 때 OpenAI API 안 쓰고도 파이프라인 전체를 돌릴 수 있게 하는 가짜 구현체. `adapters/quest_generation/fake_llm.py`는 앱에서 LLM 미설정 시 fallback으로도 사용됨.

**Q. `protocols.py`는 왜 있어?**
A. Python의 `Protocol`로 인터페이스를 정의해두면, LLM을 교체해도 agents 코드를 건드릴 필요 없음. 플러그처럼 꽂았다 뺐다 가능.

**Q. `state.py`는 왜 있어?**
A. LangGraph 노드 간에 데이터를 넘길 때 쓰는 TypedDict. 각 노드가 이 상태를 읽고 써가며 파이프라인 진행.

**Q. `memory_repo.py`가 adapters에도 있고 agents에도 있던데?**
A. `agents/character_creation/repository.py`는 현재 앱에서 쓰이지 않음. 실제 앱은 `adapters/character_creation/memory_repo.py`를 사용함.
