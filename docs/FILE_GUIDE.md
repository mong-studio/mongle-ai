# 몽글마을(mongle-ai) 파일 구조 가이드

> "이 파일 왜 있어?" 싶을 때 여기서 찾으세요.
> 왜 이렇게 나눴는지(설계 의도)는 `docs/ARCHITECTURE.md` 참조.

---

## 한눈에 보기

```text
                          ┌─────────── 요청 흐름 ───────────┐
  HTTP 요청 ─→  api/  ─→  agents/  ←─(주입)─  adapters/
  (Django)    바깥문      두뇌            손발
              받기       흐름·순서       실제 호출
```

헥사고날(포트-어댑터) 아키텍처. `agents/`가 "포트(인터페이스)"를 정의하고,
`adapters/`가 그 실제 구현을 제공하고, `api/deps.py`가 둘을 조립(주입)한다.

- **세로축** = 도메인 4개: character / todo / quest / feed
- **가로축** = 레이어 3개: api → agents ← adapters
- 한 기능을 고치려면 같은 도메인 이름을 세 폴더에서 찾는다.

```text
mongle-ai/
├── api/        ── 바깥문: HTTP 받기 (FastAPI). "무엇을 받고 무엇을 돌려줄지"
├── agents/     ── 두뇌: 실제 AI 작업 흐름 (LangGraph). "어떤 순서로 처리할지"
├── adapters/   ── 손발: 외부 연동 구현체 (LLM/S3/DB). "실제로 어떻게 할지"
│
├── runpod_workers/  ── GPU 서버리스 워커 (LLM·이미지 생성, RunPod 배포)
├── sft_pipeline/    ── 파인튜닝 데이터 파이프라인 (크롤→정제→학습→평가)
├── scripts/         ── 일회성 유틸/PoC (gradio 테스트 UI 등)
└── tests/           ── 위 3레이어를 그대로 미러링한 테스트
```

---

## `api/` — HTTP 바깥문 (FastAPI)

```text
api/
├── main.py                       # 앱 진입점: create_app()으로 FastAPI 생성 + 라우터 등록 + /health
├── config.py                     # AppConfig.from_env() — 환경변수를 설정 객체로
├── deps.py                       # ★ 조립소: cfg 보고 어떤 adapter 쓸지 분기 → Ports로 묶어 주입
├── security.py                   # X-API-Key 검증 (Django만 호출 허용)
├── envelope.py                   # 응답 공통 포맷 (성공/에러 봉투)
├── errors.py                     # 예외 → HTTP 에러 핸들러 등록
├── todo_creation/
│   ├── router.py                 # 투두 엔드포인트 (chat / generate / commit)
│   └── schemas.py                # 투두 요청/응답 Pydantic 모델
├── quest_generation/
│   ├── router.py                 # 퀘스트 엔드포인트
│   └── schemas.py                # 퀘스트 요청/응답 모델
└── character_creation/
    ├── router.py                 # 캐릭터 엔드포인트
    └── schemas.py                # 캐릭터 요청/응답 모델
                                  # ⚠ feed_generation 라우터 없음 (HTTP 미노출)
```

---

## `agents/` — 두뇌, 작업 흐름 (LangGraph)

> 도메인마다 동일한 핵심 파일 패턴을 반복한다.

### 공통 파일 패턴 (모든 도메인 공통)

| 파일 | 역할 | 비유 |
|---|---|---|
| `schemas.py` | 입력/출력 데이터 모양 정의 | 서류 양식 |
| `protocols.py` | LLM·저장소가 지켜야 할 인터페이스(포트) 정의 | 계약서 |
| `state.py` | 파이프라인이 단계별로 들고 다니는 임시 데이터 | 바통 |
| `pipeline.py` | 그래프 조립 + 실행 진입점 `run()` + `Ports` 묶음 | 레시피 + 요리사 |
| `exceptions.py` | 이 도메인의 에러 종류 | 에러 분류표 |
| `debug.py` | 단계별 로그 출력 | 디버그 프린터 |
| `nodes/` | 그래프의 각 단계 구현 (1단계 = 1파일) | 레시피 각 단계 |

### 전체 트리

```text
agents/
├── _shared/
│   └── observability/
│       ├── log_config.py         # 로깅 설정
│       └── trace_base.py         # 트레이싱 공통 베이스
│
├── character_creation/
│   ├── pipeline.py · protocols.py · schemas.py · state.py · exceptions.py · debug.py
│   └── nodes/
│       ├── validate.py           # 입력 검증 + 분기
│       ├── llm_persona.py        # LLM으로 성격/페르소나 생성
│       ├── source_upload.py      # 원본 이미지 업로드
│       ├── image_generator.py    # 캐릭터 이미지 생성
│       ├── generated_upload.py   # 생성 결과 업로드
│       ├── builder.py            # 최종 엔티티 조립
│       ├── cleanup.py            # 에러 시 원본 이미지 삭제 (보상 트랜잭션)
│       └── _upload_utils.py      # 업로드 공통 유틸
│
├── todo_creation/                # 가장 큼 — 하위 도메인 3개로 한 겹 더 중첩
│   ├── pipeline.py · protocols.py · schemas.py · state.py · exceptions.py · debug.py
│   ├── config_utils.py           # 설정 헬퍼
│   ├── middleware/
│   │   └── trace_callback.py     # LangGraph 실행 트레이싱
│   ├── planner/                  # ① 대화형 플래너 (여러 턴에 걸쳐 목표를 계획으로)
│   │   ├── graph.py · pipeline.py · state.py
│   │   ├── date_parser.py        #   자연어 날짜 파싱
│   │   ├── goal_rules.py         #   목표 판정 규칙
│   │   └── nodes/
│   │       ├── validate.py       #     입력 검증(≤600자, 한국어 비율 ≥0.5) + history에 메시지 추가
│   │       ├── planner.py        #     목표가 충분한지 판정 → plan_generator / follow_up 분기
│   │       ├── enrichment.py     #     시험·자격증 키워드면 실제 일정 조회해 컨텍스트 저장
│   │       ├── follow_up.py      #     부족하면 꼬리 질문 생성 + interrupt로 일시정지(답변 대기 후 재개)
│   │       ├── plan_generator.py #     일별 플랜 생성 (마감일 이후 날짜는 제거)
│   │       └── out_of_scope.py   #     플랜과 무관한 입력엔 고정 안내문
│   ├── todo/                     # ② 한 번에 투두 생성 (단일 턴)
│   │   ├── pipeline.py · state.py
│   │   └── nodes/
│   │       ├── validate.py       #     입력 검증
│   │       ├── date_router.py    #     입력을 todo / 캘린더 이벤트 후보로 분류
│   │       ├── task_splitter.py  #     작업을 잘게 분해 (빈 결과면 1회 재시도, 무관하면 out_of_scope)
│   │       └── out_of_scope.py   #     무관한 입력엔 고정 안내문
│   └── commit/                   # ③ 완료 투두 저장 + 퀘스트 달성 체크/분배
│       ├── pipeline.py · state.py
│       └── nodes/
│           ├── validate.py       #     마감일=오늘 항목을 오늘 TODO로 재분류
│           ├── quest_gate.py     #     오늘 TODO 있고 일일 쿼터 남으면 dispatch로, 아니면 종료(카운터 증가)
│           ├── quest_dispatch.py #     QuestDispatchPort 호출해 퀘스트 분배 (실패는 조용히 skip)
│           └── save_dispatcher.py#     저장 디스패치
│
├── quest_generation/             # nodes/ 없음 — LLM 호출이 단순해 노드 분리 대신 러너로
│   ├── pipeline.py · protocols.py · schemas.py · exceptions.py
│   ├── _llm_runner.py            # LLM 호출 실행 래퍼
│   └── _pool.py                  # 여러 퀘스트 동시 생성용 실행 풀
│
└── feed_generation/              # 파이프라인 완성, 단 api 라우터 미연결
    ├── pipeline.py · protocols.py · schemas.py · state.py · exceptions.py · debug.py
    └── nodes/                    # 흐름: validate → 이미지 → 캡션 → builder
        ├── validate.py              #   입력 검증
        ├── assemble_image_prompt.py #   이미지 생성용 프롬프트 조립
        ├── img2img.py               #   원본 이미지 기반 새 이미지 생성 (img2img)
        ├── assemble_caption_ctx.py  #   캡션 생성용 컨텍스트 조립
        ├── llm_caption.py           #   LLM으로 캡션 생성
        ├── validate_caption.py      #   생성된 캡션 검증
        ├── s3_upload.py             #   결과 이미지 업로드
        └── builder.py               #   최종 피드 엔티티 조립
```

---

## `adapters/` — 손발, 포트 실제 구현

> `agents/`의 `protocols.py`에 정의된 인터페이스를 실제로 구현한 것들.
> "어떤 LLM/저장소를 쓸지" 교체할 때 여기만 바꾸면 됨. 한 포트에 여러 구현(real/fake/runpod/local).

```text
adapters/
├── _shared/
│   ├── runpod_client.py          # RunPod 호출 공통 클라이언트
│   └── storage.py                # 스토리지 공통 헬퍼
│
├── character_creation/
│   ├── qwen_llm.py               # LLMPort — 자체 호스팅 Qwen
│   ├── runpod_llm.py             # LLMPort — RunPod 서버리스
│   ├── openai_llm.py             # LLMPort — OpenAI
│   ├── runpod_image.py           # ImageGeneratorPort — RunPod GPU 워커
│   ├── lora_image.py             # ImageGeneratorPort — 로컬 LoRA 디퓨전
│   ├── s3_storage.py             # S3Port — 진짜 S3
│   ├── local_storage.py          # S3Port — 로컬 디스크 (개발용)
│   ├── passthrough_s3.py         # S3Port 래퍼 — 기존 URL은 재업로드 skip
│   ├── memory_repo.py            # RepositoryPort — 인메모리 (실DB 미연동)
│   └── _prompts.py               # 프롬프트 템플릿
│
├── todo_creation/
│   ├── qwen_llm.py · runpod_llm.py          # LLMPort 구현 2종
│   ├── tavily_enrichment.py                 # 웹 검색으로 컨텍스트 보강
│   ├── memory_quest_counter.py              # QuestCounter — 인메모리
│   ├── request_quest_counter.py             # QuestCounter — 요청 단위 쿼터
│   ├── noop_quest_dispatch.py               # QuestDispatch — 아무것도 안 함
│   ├── quest_dispatch_adapter.py            # QuestDispatch — 완료 시 퀘스트 분배
│   ├── memory_repo.py                       # RepositoryPort — 인메모리
│   ├── _prompts.py                          # 프롬프트 템플릿
│   └── _domain_wiki.py                      # 도메인 지식 사전(내부)
│
├── quest_generation/
│   ├── qwen_llm.py · runpod_llm.py · openai_llm.py   # LLMPort 구현 3종
│   ├── fake_llm.py                          # LLMPort — 테스트용 가짜 (+ LLM 미설정 시 fallback)
│   ├── memory_repo.py                        # RepositoryPort — 인메모리
│   └── _prompts.py                           # 프롬프트 템플릿
│
└── feed_generation/
    └── qwen_llm.py                           # LLMPort — 자체 호스팅 Qwen
```

---

## 부속 디렉토리

```text
runpod_workers/                   # RunPod에 배포되는 GPU 컨테이너 (api/와 독립 배포)
├── llm/
│   ├── handler.py                #   RunPod 진입점 (요청 처리)
│   ├── pipeline.py               #   추론 파이프라인
│   ├── bake.py                   #   이미지에 모델 미리 굽기
│   └── Dockerfile · requirements.txt
├── image_gen/                    #   이미지 생성 통합 워커
│   ├── handler.py                #   image/text character · feed 모드 라우팅
│   ├── pipelines/
│   │   ├── image_character/      #   사진 → 캐릭터 PNG + appearance
│   │   ├── text_character/       #   텍스트 → 캐릭터 PNG + appearance
│   │   ├── feed/                 #   appearance + quest → 피드 이미지
│   │   └── shared/               #   공통 appearance/background 유틸
│   └── Dockerfile · requirements.txt · README.md
└── setup_endpoints.py            # RunPod 엔드포인트 생성 스크립트

sft_pipeline/                     # 파인튜닝 데이터 파이프라인 (런타임 무관, 모델 제작용)
├── crawl/                        # ① 웹 크롤링: fetcher · extractor · robots · run_crawl
├── structure/                    # ② 구조화: normalize · fields · exam_types · run_structure
├── build/                        # ③ 데이터셋 생성 (~30 스크립트: build_sft_dataset, exam_synth, distractor ...)
├── train/                        # ④ 학습: train_lora · train_plain · dataset
├── eval/                         # ⑤ 평가: chat_eval · gradio_app
├── config/*.yaml                 #   추출/정규화 규칙 (exam_types, extractors, normalization)
├── data/                         #   크롤 URL 목록
├── docker/                       #   학습용 Dockerfile + run_synthesis.sh
├── io_utils.py · distractor.py   #   공통 유틸
└── tests/                        #   sft 전용 테스트

scripts/                          # 일회성 유틸 / PoC
├── gradio_planner_chat.py        #   플래너 내부 테스트 UI
├── s3_sync.py                    #   S3 동기화 (push/pull)
├── smoke_enrichment.py           #   enrichment 스모크 테스트
├── _gen_planner_notebook.py      #   노트북 생성
└── outlines_poc/                 #   구조화 출력 PoC (constrained · eval_prompts · run · report)

tests/                            # api/ agents/ adapters/ 를 1:1 미러링
├── api/                          #   엔드포인트별 (test_character, test_todo_*, test_quest, test_security ...)
├── agents/                       #   도메인별·노드별 (+ fakes.py = 가짜 포트 구현)
├── adapters/                     #   어댑터별
└── conftest.py                   # pytest 공통 픽스처
```

**루트 설정 파일:** `pyproject.toml`(의존성), `requirements-api.txt`,
`Dockerfile`·`docker-compose.yml`(API 컨테이너),
`.github/workflows/`(CI: api-tests / deploy-api / deploy-workers / sft-docker).

---

## 헷갈리는 것들 FAQ

**Q. `qwen_llm.py`가 여러 도메인에 다 있는데?**
A. 도메인마다 입출력 타입·프롬프트가 달라 각각 별도 구현. 이름만 같고 내용은 다름.

**Q. `protocols.py`는 왜 있어?**
A. Python `Protocol`로 인터페이스를 정의해두면 LLM/저장소를 교체해도 `agents/` 코드를 안 건드려도 됨. 플러그처럼 꽂았다 뺐다.

**Q. `state.py`는 왜 있어?**
A. LangGraph 노드 간 데이터를 넘기는 상태 객체. 각 노드가 읽고 써가며 파이프라인 진행.

**Q. `fake_llm.py` / `fakes.py`는 왜 있어?**
A. 테스트에서 진짜 LLM·네트워크 없이 파이프라인 전체를 돌리는 가짜 구현체. `adapters/quest_generation/fake_llm.py`는 LLM 미설정 시 fallback으로도 쓰임.

**Q. `memory_repo.py`는 왜 인메모리야?**
A. 실 DB는 Django 쪽이 담당. mongle-ai는 아직 인메모리 저장소를 사용 (영속화는 호출자/DB 레이어 책임).

**Q. `_` 접두사 파일/폴더는?**
A. 모듈 내부 전용(`_prompts.py`, `_shared/`, `_domain_wiki.py`). 외부에서 직접 import 안 함.
