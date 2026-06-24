# 플래너 설계 노트 — 논문 → 우리 코드 매핑 (개발자용)

> 동화 버전: [`sft_citation.md`](./sft_citation.md). 이 문서는 같은 5편을
> **실제 노드·심볼·계약·구현 상태**에 붙인 개발자용이다.
> "왜 이렇게 짰나"를 코드 위치와 함께 추적할 수 있게 한다.

코드 루트: `agents/todo_creation/planner/`, 어댑터: `adapters/todo_creation/`.

---

## 0. 한 줄 계약 (3-레이어)

> ⚠️ **현 상태 = LLM-Modulo의 *부분* 구현.** LLM-Modulo의 정의적 부품은
> "verifier가 reject → backprompt 재생성" 루프인데, 그 루프는 아직 없다
> (`graph.py`는 `plan_generator → END` 직행). 지금 실재하는 건 LLM 생성 +
> 결정적 후처리 필터(날짜 hard 제약)뿐. **judge + backprompt 가 들어와야
> 비로소 LLM-Modulo다**(§8 로드맵). 이 문서는 그 목표 아키텍처를 기준으로 쓴다.
>
> **SFT ↔ LLM-Modulo 모순 해소.** 논문 제목은 "LLMs *Can't* Plan"인데 이 폴더는
> 플래너를 SFT로 더 잘 계획하게 만든다 — 모순처럼 보인다. 화해:
> **SFT는 후보(candidate) 품질을 올리고, verifier는 잔여 오류를 잡는다.**
> 둘은 경쟁이 아니라 직렬이다(좋은 후보 × 싼 검증 = 적은 backprompt 횟수).

| 레이어 | 책임 | 소유자(LLM/코드/judge) | 실제 위치 |
|--------|------|------------------------|-----------|
| 의도 파악 | 충분성 판정 + 슬롯/마감 추출 | **LLM** | `qwen_llm.judge_sufficiency` → `nodes/planner.py` |
| 명확화 | 빠진 슬롯만 되묻기 | **LLM** | `nodes/follow_up.py` (interrupt/resume) |
| 후보 생성 | 일정 아이디어 + 난이도 | **LLM** | `qwen_llm.generate_plan` |
| 배치 | 날짜 계산·전개·clamp | **코드** | `plan_generator._prepare_plan_days`, `allocator.expand_routine` |
| 정합성 검증 | "이 조합 말 되나" | **judge** | ⚠️ **미배선** (§5 참조) |

핵심 원칙: **LLM은 내용·난이도, 코드는 산술(날짜), judge는 조합 검증.**
산술을 LLM에 맡기지 않는 게 LLM-Modulo의 요점(논문 1).

단, "코드 레이어"가 전부 결정적인 건 아니다. 마감 *추출*은
`date_parser.py` 의 정규식 한국어 파싱(`_parse_relative_day`/`_parse_weekday`)이라
"3주 뒤"·"다음주 토요일" 같은 표현에서 깨질 수 있다 — 결정적인 건 추출된 날짜로
하는 *배치 산술*이지, 자연어→날짜 변환이 아니다.

---

## 1. LLM-Modulo (Kambhampati 2024) — generate/verify 분리
🔗 https://arxiv.org/pdf/2402.01817

**우리가 빌린 계약**
- LLM은 "후보 계획"만, 검증은 외부 검사기. 위반은 backprompt 루프로 재생성.

**코드 앵커**
- 후보 생성: `plan_generator_node` → `llm.generate_plan(parsed_goal, today)`.
- 결정적 검사(현재 구현된 verifier): `_clamp_to_deadline` (마감 이후 제거),
  `_prepare_plan_days` (날짜 정규화·중복일 spread).
- routine 경로는 LLM을 아예 안 거치고 `allocator.expand_routine` 가 cadence를
  날짜로 전개 — "슬롯이 곧 내용"이라 generate 단계 자체가 불필요(`plan_generator.py:27`).

**현황**: hard-constraint verifier(날짜)는 코드로 구현됨. soft-constraint /
조합 정합성 judge + backprompt 루프는 **아직 없음**(§8).

**논문 사실(검증됨, 전문 확인)**
- 루프 = **Generate-Test-Critique**. LLM 후보 추측 → Reformulator가 검증용 형식 변환 →
  **critic 뱅크** → **Meta(Backprompt)Controller**가 비평 모아 되먹임 → **hard critic 전원
  통과 시 종료**(사례는 round 상한 10~15회 병행).
- critic 3종: **hard**(정확성, 외부 검증기, LLM 불가) / **soft=style**(취향·설명가능성,
  LLM·VLM 대행) / **constructive**(대안 제안). **건전성은 hard critic에서 상속**,
  **LLM은 자기검증 금지**(self-improve 불가).
- 수치: 자율 baseline **~12%**, VAL 되먹임으로 Blocksworld **82%**.

**→ 설계 함의**: 우리가 만들 "judge"는 **soft/style critic 자리**(정합성·부하). 날짜는
이미 코드 hard critic. backprompt = judge 결과를 `generate_plan` 입력으로 되먹이는 루프
(미구현). 자율 후보가 12%뿐이란 건 **SFT로 후보 품질을 올려야 backprompt 횟수가 준다**는
근거(§0 화해와 일치).

---

## 2. LLM-Modulo 여행 사례 (2024) — hard/soft 분리 본보기
🔗 https://arxiv.org/pdf/2405.20625

**우리가 빌린 것**: 제약을 hard(꼭) / soft(취향)로 나눠 검사.

**현재 hard 제약 (코드로 강제됨)**
- 마감 이후 task 금지 → `_clamp_to_deadline`.
- event-day(시험·여행 당일)는 비움 → `deadline_is_event` 플래그 + reserve 로직
  (`ParsedGoal.deadline_is_event`, judge 우선·`goal_rules.is_event_day_deadline` 폴백).
- routine 마감 clamp → `expand_routine(deadline=...)` 의 `day > deadline: break`.

**soft 제약 (미구현, 후보)**: 아침형 선호, 하루 부하 cap, 난이도 분산.
→ judge가 생기면 여기로 들어간다. 지금은 슬롯에만 존재(`daily_capacity_minutes`).

**선행조건(data model)**: "하루 부하 cap" judge는 지금 스키마로 불가능하다.
`schemas.py` `TaskCandidate = {title(≤20자), due_date, tags}` 에 **난이도·소요시간
필드가 없어서** "이 날 task 합이 cap 초과"를 계산할 근거가 없다. judge 노드보다
`TaskCandidate.estimated_minutes`(또는 difficulty) 추가가 먼저다.

**논문 사실(검증됨, 전문 확인)**
- 정확 수치: **GPT-4-Turbo 4.4% → 20.6% = 4.6x**(abstract 명시). "6배"는 본편의
  GPT-3.5 TravelPlanner 수치라 혼동 금지. GPT-3.5는 0%→5%(GPT-4 baseline 추월).
- critic 전부 **binary**(issue+backprompt 메시지 쌍 반환). **Format critic(JSON 유효성)이
  다른 모든 critic의 precondition** — 항상 먼저 실행.
- metacontroller는 단순: 모든 backprompt **concatenate** 후 재전달, **10 iteration** 상한.
- plan 표현 = **하루당 JSON 1객체**(reformulator가 자연어→JSON).
- ablation: Common 2.8 / Hard 1.6 / Json 1.1 / **All 5.0%**(합치면↑, composability).

**→ 설계 함의**: ① Format-precondition 패턴 = 우리도 **스키마/`_prepare_plan_days` 검증을
judge보다 먼저** 둬야 함(깨진 구조 위에서 정합성 판단 무의미). ② "하루당 JSON 1객체"는
우리 `PlanDay`와 같은 형태 → critic 입력 표현을 그대로 차용 가능.

---

## 3. Clarify When Necessary (Zhang & Choi 2023) — 언제/무엇을 물을까
🔗 https://arxiv.org/pdf/2311.09469

**우리가 빌린 것**: (1) 언제 묻나 (2) 무엇을 묻나 (3) 답받고 진행 — 3단계.

**코드 앵커**
- 언제: `planner_node` 가 `judge_sufficiency` 결과로 분기
  (`destinations=("plan_generator", "follow_up", "out_of_scope")`, `graph.py:26`).
- 마감 민감 목표인데 날짜 모호 → 강제 되물음: `goal_rules.needs_deadline_follow_up`
  (`_DEADLINE_SENSITIVE_WORDS`, `_AMBIGUOUS_DEADLINE_WORDS`).
- 무엇: `follow_up_node` 가 `missing_aspects` 기준 1개 질문 생성.
- 멈춤 조건: 충분성 충족 시. 반복 방지로 follow_up 누적되면 보수적으로
  plan 생성으로 fallback (`test_repeated_follow_up_falls_back_to_plan_generation`).

**계약**: follow_up → planner 재평가 엣지가 루프(`graph.py:43`). 무한 질문 금지는
누적 턴 fallback 으로 막는다.

**논문 사실(검증됨, 전문 확인)**
- "언제 묻나"를 **분류가 아니라 불확실성 추정**으로 정식화. 골라야 할 입력 =
  **aleatoric(모호성) 높고 epistemic(지식 부족) 낮은** 것(물으면 답을 알 수 있는 경우).
- **INTENT-SIM**: 질문 생성 → 사용자 답변 **10샘플(T=0.5)** → DeBERTa-NLI로 동치 묶어
  의도 분포 → **엔트로피**가 불확실성. 임계값 대신 **상호작용 예산 b%**(상위 b%만 질문).
- 결과: **10%에만 질문해도 랜덤 대비 이득 2배**.

**→ 설계 함의**: 우리 `judge_sufficiency`는 현재 **binary 분류**인데 논문은 분류를 거부한다.
정교화 경로는 "불확실성 점수 + 예산 컷오프"지만, 우리의 **슬롯-결정론**(plan_kind 필수 슬롯이
비면 질문)은 LLM 샘플링 10회가 불필요해 **비용상 더 싸다**. 의식적 트레이드오프로 남긴다 —
모호성이 슬롯으로 안 잡히는 경우에만 불확실성 추정 고려.

---

## 4. What Prompts Don't Say (2025) — underspecification
🔗 https://arxiv.org/html/2505.13360v2

**우리가 빌린 것**: 사용자 요청엔 항상 빠진 조건이 있다 → 되묻기의 *근거*.

**코드 앵커**: `plan_kind` 별 필수 슬롯 정의가 곧 "무엇이 빠졌나"의 체크리스트.
`adapters/todo_creation/_prompts.py` PLANNER_JUDGE_SYSTEM:
- exam: `exam_part, exam_date, daily_hours, current_level`
- routine: `activity, cadence, time_of_day, horizon`
- vague_goal: `goal, first_action, weekly_cadence, horizon`
- lifestyle: `domains, cadence_per_domain, horizon`
→ 슬롯 중 빠진 게 `missing_aspects` 로 흘러 follow_up 을 트리거.

**계약**: judge는 *말한 값만* 슬롯에 채운다(빈 문자열·null 금지). 안 채운 키 = 빠짐.

**논문 사실(검증됨, 전문 확인)**
- underspecification = "**유효하지만 서로 모순된 동작이 여럿** 가능"한 상태. 명시 vs 미명시
  만족률 차이로 측정(8,400 데이터포인트).
- 수치: 미명시 평균 **−22.6%**(최악 **−93.1%**), 그래도 **41%는 자동 추측**으로 충족,
  미명시는 변동성·모델 업데이트 회귀 약 2배.
- **다 명시한다고 정답 아님**: 19개 한꺼번에 명시 시 오히려 **−19%**(specification overload).
- 완화: COPRO-R(검증기 정확도를 최적화 신호, +5.8%) / Bayesian TPE(명시할 슬롯 탐색,
  +3.8% & 토큰 −41~45%).

**→ 설계 함의**: overload −19%가 **"필수 슬롯만 묻는" 현 설계의 정량 근거**다 — 슬롯 전부
묻기는 역효과. 41% 자동추측은 **follow_up 과잉 질문 경계선**(judge가 추측 가능한 슬롯은
안 물어도 됨). 장기적으로 plan_kind별 필수 슬롯 집합을 COPRO-R식으로 검증기-신호 튜닝 여지.

---

## 5. Curiosity by Design (2025) — 충분성 분류기 먼저
🔗 https://arxiv.org/pdf/2507.21285

**우리가 빌린 것**: "충분한지 판단 → 모자라면 질문 → 출력" 순서를 구현으로.

**코드 앵커**: 그게 `judge_sufficiency` 의 반환 `(sufficient: bool, missing: list, goal: dict)`.
`planner_node` 가 이 셋으로 라우팅 = intent clarity classifier 그 자체.

**논문 사실(검증됨, 전문 확인)**
- 3단계: **Intent Clarity Classifier**(DistilBERT, 4점 척도, 정확도 **73%**, 합성 4,161건) →
  **Clarification**(Gemma-3-1B-IT + LoRA) → Answering. **1회 질문만**(멀티턴 루프 없음).
- ⚠️ 평가가 **객관 pass-rate 아님 — 인간 선호 Likert**(최대 "더 정확 66%"). 추론 **133초/건**.
  GitHub 실데이터는 노이즈로 폐기 → **전부 합성 데이터**.

**→ 설계 함의**: ① classifier를 별도 소형 모델로 분리하는 패턴이 존재하나, 우리는 judge LLM
한 번에 처리(노드 추가 비용 회피). ② **133초/건은 우리 Pod 100s 벽과 충돌** → 충분성 판정은
가볍게 유지(무거운 분류기 도입 금물). ③ 합성 데이터 의존 성공 사례 = **우리 SFT도 합성
위주로 갈 수 있다는 신호**(§6.5 데이터 출처와 연결).

---

## 6. 실제 그래프 (as-built)

```
START → validate → planner ─┬─ sufficient ──────→ plan_generator → END
                            │                         │
                            ├─ missing ── follow_up ──┘ (interrupt→resume→planner)
                            │
                            └─ out_of_scope (짧고 명백히 무관한 첫 입력만) → END
```
- `validate` = `multi_validate_node`, `planner` = `planner_node`.
- `plan_generator` 내부 분기: `plan_kind == "routine"` → `expand_routine`(코드만),
  그 외 → `generate_plan`(LLM) → `_prepare_plan_days` → `_clamp_to_deadline`.

---

## 6.5 SFT 브리지 — 논문 패턴 → 학습 페어 (이 폴더의 존재 이유)

§1~6은 *런타임 그래프*다. 이 폴더는 `sft_pipeline/` 이므로 핵심 질문은
**"각 논문 패턴이 어떤 (input → target) 학습 예시가 되나"** 이다. verifier가
런타임에 잡아주는 오류를, SFT는 *애초에 후보가 그 오류를 안 내도록* 학습시킨다
(§0의 "후보 품질 ↑" = backprompt 횟수 ↓).

| 논문 패턴 | SFT input | SFT target | 데이터 출처 |
|-----------|-----------|------------|-------------|
| clarification (논문 3·5) | underspecified 발화 | follow_up 질문 1개 + 채워야 할 슬롯 | 합성/`crawl` 가공 |
| underspecification (논문 4) | 슬롯 일부 빈 목표 | `missing_aspects` 분류 | judge 라벨 |
| plan_kind 분류 | 자유 발화 | `{plan_kind, slots}` JSON | `structure/` |
| 후보 생성 (논문 1) | 충분한 parsed_goal | day별 task 후보(+난이도) | 시험=`crawl` 오프라인, 일상=합성 |

**평가**: "SFT 됐다"의 기준은 `sft_pipeline/eval/` 에 건다 — 슬롯 추출 정확도,
follow_up 적절성(과·소질문), 후보가 hard 제약(마감·event-day)을 *생성 시점에*
지키는 비율(= verifier reject 율의 역수). 런타임 verifier 통과율을 SFT 회귀 지표로 재사용.

---

## 7. 지켜야 할 불변식 (회귀 주의)

1. **마감 이후 task 0개** — `test_p1_no_task_strictly_after_deadline`.
2. **event-day 당일 비움 + 준비는 전날까지 압축** — `deadline_is_event` 경로.
   판정은 LLM 우선, 키워드 폴백. "N일까지" = N일에 그 일을 함(deadline=N).
3. **routine 은 LLM 무호출** — `generate_calls == 0` 가정(결정성·비용).
4. **goal_tag 는 코드가 sanitize** — `_normalize_goal_tag` (조사 제거, ≤20자, DB 저장형).
5. **중복일 spread** — 같은 날짜만 있으면 하루씩 펼침(`should_spread`).

---

## 8. 갭 / TODO (정직하게)

- **정합성 judge 미배선** — LLM-Modulo의 핵심인 "배치 후 조합 검증 + backprompt"
  루프가 없다(§0 참조: 그래서 현재는 *부분* 구현). 지금 verifier는 날짜 hard
  제약뿐. 하루 부하 cap·난이도 분산 같은 soft 검증은 슬롯에만 있고 강제 안 됨.
  → judge 노드 신설 시 §2 soft 제약을 여기로. **단 부하 cap은 §2 선행조건
  (`TaskCandidate`에 소요시간 필드 추가)이 먼저** — 없으면 judge가 계산 불가.
- **시험 날짜 런타임 수급** — 크롤은 오프라인 SFT 데이터 전용. 런타임은 Tavily로
  "오늘 이후 가장 가까운 회차"만 받아 채우는 설계(미구현). today 필터·정렬은 코드.
- **비-spread 당일 task 드롭** — LLM이 당일에 박은 준비 task는 압축이 아니라 드롭됨
  (유실 가능). reserve 경로의 알려진 한계.
- **routine horizon 자연어** — "한 달" 같은 표현은 v1 비범위, 기본 28일 고정
  (`_DEFAULT_ROUTINE_HORIZON`).

관련 메모리: `planner-sft-design-and-event-day`, `daily-life-planner-revival`,
`sft-multinode-migration`.
