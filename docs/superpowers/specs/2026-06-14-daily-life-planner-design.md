# 일상(Daily-Life) 멀티턴 플래너 설계서

> **상태:** 설계 승인 대기 → 이후 `writing-plans` 로 구현 계획 작성
> **범위:** (1) 아키텍처 설계 + (2) SFT 데이터셋 설계. 런타임 코드 구현·파인튜닝 실행은 별도 단계.
> **작성일:** 2026-06-14

## 0. 한 줄 요약

기존 시험 플래너는 사실상 **단일 스키마에 하드코딩된 schema-guided slot-filler** 다.
일상(막연한 목표·반복 루틴·생활설계) 요청을 정합성 있게 처리하기 위해, 그 하드코딩을
**선언적 스키마 뱅크(slot schema bank)** 로 일반화한다. 작은 모델로 정합 플랜을 처음부터
생성하긴 무리이므로, **뉴로-심볼릭 분업**을 쓴다 — **LLM 은 "무엇을 + 상대 배치(며칠차·리듬)"** 만,
**코드가 "절대 날짜 + 제약"(상대→절대 매핑·마감 앵커·clamp)** 을 맡고, `check_plan_consistency` 가
외부 검증기(LLM-Modulo)로 닫는다. 모델은 못하는 달력 산수를 코드에 맡기되, 기계적 균등 분할을 피하려
**리듬은 LLM 의 상대 배치로 보존**한다. 봇 주도 꼬리질문은 ≤2턴, 모자란 건 사용자 revision 으로.
이 흐름을 가르치는 **멀티턴 SFT 데이터셋**(plan 타깃 = task목록+상대배치, 절대 날짜 없음)을 함께 설계한다.
별도 멀티에이전트/Deep Agent 는 만들지 않는다(L1 하이브리드 = 하네스 극).

---

## 1. 문제 정의 (Problem)

### 1.1 현재 상태

- 멀티턴 플래너(`agents/todo_creation/planner/`)는 LangGraph 그래프:
  `validate → planner → (plan_generator | follow_up | out_of_scope)`, `follow_up` 은
  `interrupt()` 로 멈췄다가 사용자 답변 후 `planner` 로 회귀.
- `planner_node` 는 `llm.judge_sufficiency(history, message, today, user_profile_memory)`
  → `(sufficient, missing_aspects, parsed_goal)` 로 분기.
- `ParsedGoal` 슬롯은 **시험 모양**(`deadline`, `daily_capacity_minutes`)뿐이고
  `intent ∈ {plan, out_of_scope}` 만 구분한다. **일상/시험 구분도, 반복(recurrence) 개념도 없다.**
- 시험 전용 슬롯·복구 로직이 `planner/goal_rules.py` 에 정규식·휴리스틱으로 하드코딩되어 있다.

### 1.2 핵심 결함

열린/모호한 일상 요청(`"운동 꾸준히 하고 싶어"`, `"균형 잡힌 한 달"`, `"매주 3번 헬스"`)은
**시험처럼 깔끔한 유한 슬롯 집합이 없다.** 단일 고정 스키마(`deadline`/`daily_capacity`)로는
이들 슬롯이 의미가 없어, 모델이 엉뚱한 질문을 하거나 정보 부족인데 바로 플랜을 만든다.

**관찰된 구체 결함 (2026-06-15 사용자 피드백):**

| P | 증상 | 근본 원인 | 해결 |
| --- | --- | --- | --- |
| P1 | "일주일 뒤 시험" → D7 시험인데 D6 시험·D7 회고로 밀림 | `_prepare_plan_days` 가 deadline 을 앵커로 안 쓰고 today 부터 순차 펼침 | **Phase 0 핫픽스**(deadline 앵커, ~10줄) + §3.5 critic 규칙 → 이후 D8 allocator 로 일반화 |
| P2 | 일상 정합 플랜 생성이 7B LoRA 에 과부하 | 작은 모델에 "처음부터 날짜별 정합 플랜"을 시킴 | D8(날짜=코드) + D10(내용=라이브러리). 본질은 lifestyle 내용 — 큐레이션 라이브러리로 정면돌파 |
| P3 | 사용자가 긴 꼬리질문을 싫어함 | 충분성 기준이 과다 슬롯 | D9 ≤2턴 + 기본값 + 사용자 revision |
| P4 | 반복 루틴 개념 자체가 런타임에 없음 | plan_kind/스키마 부재 | §3.2 routine 스키마 + allocator horizon 확장 |

### 1.3 학술적 위치

이 문제 = **schema-guided task-oriented dialogue (TOD)** 의 세 하위문제:

| 하위문제 | 근거 |
| --- | --- |
| Schema-guided slot filling | Schema-Guided Dialogue, Rastogi et al. 2020 |
| Proactive clarification — "무엇을 물을까" | IN3 (Intention-in-Interaction), QuestBench |
| 언제 그만 물을까 (sufficiency stop) | AskBench / rubric-guided RLVR |
| 일정/제약 분배 | MeetMate, Google Natural Plan, PlanGEN |
| 멀티턴 sufficiency 판단 학습 | "Teaching LMs to Gather Information Proactively", EMNLP 2025 |

**LangGraph Deep Agent 미채택 이유:** Deep Agent = 계획툴 + 서브에이전트 + 가상 파일시스템 +
장문 프롬프트로, 열린 연구·코딩 과제용이다. 본 과제는 경계가 분명한 slot-filling→일정분배라
서브에이전트/파일시스템 기계장치의 이득이 없고, 이미 동작하는 interrupt 루프를 버리게 된다.
**파인튜닝**은 전체 흐름이 아니라 *멀티턴 sufficiency judge* 에 집중 투입한다.

---

## 2. 설계 결정 (Decisions)

| # | 항목 | 결정 |
| --- | --- | --- |
| D1 | 대상 범위 | 막연한 목표형(vague_goal) + 반복 루틴형(routine) + 혼합 생활설계형(lifestyle) |
| D2 | 스키마 전략 | **의도별 스키마 뱅크(B)** + 얇은 동적 슬라이스(≤1–2 ad-hoc 슬롯) |
| D3 | 결과물 범위 | 아키텍처 설계 + SFT 데이터 설계 (런타임 구현·SFT 실행 제외) |
| D4 | 출력 형태 | `plan_kind` 별 분기: exam/vague_goal/lifestyle → `days[]`, routine → horizon 확장 |
| D5 | 반복 표현 (v1) | **Horizon 확장** — 반복을 horizon(기본 28일) 내 날짜별 `calendar_events` 로 펼침. `GenerateResult`/SFT 미러/DB 변경 0. RRULE 필드는 미래 확장 |
| D6 | 에이전트 구조 단계 | **L1 하이브리드** — 결정적 그래프 골격 유지 + 함수형 critic 루프. 툴 호출 여부는 **그래프가 결정**(모델 아님)하여 에이전트 궤적(tool-call trace) SFT 회피. 모델 1개·SFT 분포 1개 유지 |
| D7 | enrichment 제거 | enrichment 노드는 그래프에 미연결 orphan. **노드·Tavily 어댑터·port 와이어링·관련 테스트 일괄 삭제.** 시험일 조회는 v1 비범위 |
| D8 | 뉴로-심볼릭 분업 | **용량 선계산(코드) → LLM "무엇을+상대배치"(N개·며칠차·리듬) → 코드 "절대날짜+제약"(상대→절대 매핑·마감 앵커·clamp).** 모델은 **상대 배치만**, **절대 달력 산수는 코드** — 기계적 균등 분할 방지(리듬은 LLM 보존), P1 보장은 코드 clamp. 근거: LLM+P, LLM-Modulo(LLM 제안→검증기 최소 교정), "LLM as formalizer". 우겨넣기 방지: 용량 N·하루 용량 clamp(cram·silent-drop 금지). 코드 ~50줄(매핑+clamp), 무거운 솔버 비범위 |
| D9 | 턴 예산 | 봇 주도 꼬리질문 **≤2회**(여러 슬롯을 한 질문에 묶음). 캡 도달 시 **합리적 기본값**으로 즉시 플랜 생성. 모자란 건 봇이 더 묻지 않고 **사용자 revision**으로 보정(기존 edit→plan_generator 직행 경로) |
| D10 | lifestyle 내용 품질 | **사람 큐레이션 활동 라이브러리(RAP/CBR)** 로 정면돌파. 모델은 백지 창작이 아니라 라이브러리 후보를 **선택+개인화**. 라이브러리는 **SFT 시드**(시험 크롤 시드와 동일 역할)이자 **eval 골든블록**. "합성은 로컬" 정책 유지(큐레이션은 사람, 재서술은 로컬모델). 큰 모델 증류는 비채택 |
| D11 | 질문/슬롯 분리 = 노드, 모델 아님 | "질문 담당 / JSON 담당" 분리는 **단일 모델의 두 노드**(`judge_sufficiency`=슬롯 추출+충족, `follow_up`=질문)로 구현. 고전 TOD 모듈화와 동형이나 **모델은 1개**. 모델 2개 분리는 비채택 — 정확성 병목인 슬롯 추출은 분리해도 그 모델 실력에 묶이고(격리되는 건 쉬운 질문 쪽뿐), SFT 2종·턴당 2호출 비용만 증가. 근거: 약모델 debate 역효과(Talk Isn't Always Cheap), 동일예산 단일에이전트 우위, LLM 자기검증 한계 |

---

## 3. 아키텍처 (Architecture)

### 3.1 원칙: 병렬 시스템이 아니라 일반화 (L1 하이브리드)

기존 시험 플래너가 곧 단일 스키마 slot-filler 이므로, **그래프 토폴로지는 그대로 두고**
`judge_sufficiency` 와 `plan_generator` 만 스키마-aware 로 만든다. 여기에 **에이전트성을
이득이 분명한 한 곳에만** 더한다 — `plan_generator` 뒤의 **함수형 critic 루프**(§3.5).

**에이전트 궤적(agent trajectory) 회피 원칙:** 모델이 "언제 무슨 툴을 부를지" 스스로
판단하면, 그 다단계 행동 사슬(tool-call → result → 다음 행동)을 학습·검증해야 해서 SFT
정합성("학습 토큰 == 추론 토큰")이 깨진다. 따라서 본 설계에서 **툴 호출 여부는 그래프(코드)가
결정**하고, 모델은 항상 JSON 출력 1개만 낸다. critic 역시 LLM이 아니라 순수 함수다 — 둘 다
모델에게는 "입력이 조금 더 풍부해졌을 뿐", 출력 형태는 L0과 동일하다.

```
ParsedGoal.intent:  plan | out_of_scope                              (today)
        →  plan_kind: exam | routine | vague_goal | lifestyle | out_of_scope   (new)
```

`plan_kind` 는 `judge_sufficiency` 가 분류한다(별도 LLM 호출 없이 같은 호출에서 반환).

### 3.2 스키마 뱅크 — `planner/slot_schemas.py` (신규)

선언적 레지스트리. 각 엔트리 = 필수/선택 슬롯 + 질문 템플릿 + 우선순위.
`judge_sufficiency` = *plan_kind 분류 → 스키마 로드 → 채워진 필수 슬롯 표시 →
sufficient ⇔ 필수 전부 충족.*

| plan_kind | 필수 슬롯 | 선택 슬롯 |
| --- | --- | --- |
| **exam** (기존 이관) | exam_part, exam_date, daily_hours, current_level | weak_subjects, goal |
| **routine** | activity, cadence(`주 N회` 또는 요일들) | time_of_day, horizon |
| **vague_goal** | goal, first_action(걸림돌 질문으로 유도), weekly_cadence | horizon |
| **lifestyle** | domains[], 도메인별 cadence/hours_budget, horizon | fixed_blocks, priority_order |

**동적 슬라이스(C의 일부):** LLM 은 선택된 스키마에 ad-hoc 슬롯을 ≤1–2개 추가할 수 있으나
**필수 골격은 고정**이라 검증·SFT 학습 가능성을 유지한다.

`goal_rules.py` 의 시험 전용 정규식·복구(`build_recovery_goal`)·deadline 휴리스틱은
**exam 스키마 엔트리로 흡수**되어 해당 파일이 축소된다.

### 3.3 대화 흐름 — `planner_node` 내부만 변경

- Sufficiency = "plan_kind 의 필수 슬롯 전부 충족" (`needs_deadline_follow_up` 대체).
- Follow-up 은 **가장 우선순위 높은 미충족 슬롯 1개**만 질문 (IN3/QuestBench 의 최소 필요 질문).
- 기존 `_follow_up_count >= 2` 캡은 "그만 묻기" 가드로 유지(AskBench 의 stop 조건),
  스키마별 override 허용(lifestyle 은 3까지).
- 그래프 노드/엣지·`interrupt` 재개 메커니즘은 **불변**.

### 3.4 플랜 생성 & 출력 — 뉴로-심볼릭 분업 (D8)

`plan_generator` 는 **용량 계산(코드) → "무엇을+상대배치"(LLM) → "절대날짜+제약"(코드)** 로 쪼갠다.
모델은 **상대 배치(며칠차·리듬)** 만 하고 **절대 달력 산수는 코드**가 맡는다 — 모델이 못하는 산수는
코드가, 리듬 뉘앙스는 모델이 보존(코드가 균등 분배하면 기계적 플랜이 됨). P1·P2 동시 해소.

**⚠️ 우겨넣기(cram) 방지 — 양은 시간에 의존한다:** task **개수**는 남은 시간에 종속되므로,
용량을 먼저 계산해 LLM 에 목표 개수 N 을 알려준다.

**0단계 — 코드: 용량 선계산**
- 남은 일수 × 하루 가용 → "task 슬롯 약 N개" 도출. 이 N 을 1단계 LLM 에 전달.

**1단계 — LLM: N개 task 목록 + 상대 배치 (절대 날짜 없음)**
- 입력: 충족 슬롯(parsed_goal) + **목표 개수 N** + (lifestyle/vague_goal) 라이브러리 후보(§3.7).
- 출력: `[{title, rel_day(1..N) | order}]` — *무엇을* + *며칠차에*(상대 배치). **절대 달력 날짜·산수는 안 함.**
- **이유:** 코드 균등 분배는 기계적 → 리듬·뉘앙스(개념 먼저→마지막날 복습, 바쁜 날 가볍게)는 LLM 이
  상대 배치로 보존. 상대 순서는 약한 모델도 곧잘 함(절대 날짜 계산은 못해도).
- **종류별 내용 부담:** routine ≈ 0(슬롯=내용, LLM 생략), vague_goal = 소, **lifestyle = 대(P2 본질)**
  → lifestyle/vague_goal 은 백지 창작이 아니라 라이브러리 후보 **선택+개인화**(RAP/CBR).

**2단계 — 코드: 상대→절대 매핑 + 제약 clamp (날짜 산수·보장)**
- **달력 산수:** "일주일 뒤" 등 → 실제 날짜 계산. **마감일 = 하드 앵커**(마지막 날 고정).
- **매핑:** LLM 의 rel_day(1..N) → 실제 날짜로 변환(앵커 기준). **재배열·균등화 안 함 — LLM 배치 보존.**
- **clamp(보장):** deadline 이후 task 금지(P1), 하루 용량 초과 차단(cram 방지).
- deadline 이벤트(예: "시험 응시")는 deadline 날짜에. routine 은 cadence 를 horizon(기본 28일)에 펼침.
- `today == due_date` → todos, 그 외 → calendar_events (기존 C5 분기 재사용).
- 코드는 ~50줄 결정적 함수(매핑+clamp). 무거운 솔버(PDDL/Timefold) 비채택(YAGNI).

**출력 형태는 `plan_kind` 무관하게 동일** — 최종 `GenerateResult`(절대 날짜)는 **코드 매핑+clamp**
결과라 학습 대상이 아니다. **학습 대상은 LLM 의 task목록+상대배치(rel_day)** 뿐(§4.3).

**RRULE(진짜 반복 규칙)** 은 런타임+미러+서버+web+DB 동시 변경이라 v1 범위 밖, 미래 확장으로 명시.

### 3.5 런타임 critic = 외부 검증기 (LLM-Modulo)

`check_plan_consistency`(날짜·C5·품질)를 **추론 시에도 재사용**해 allocator 출력을 검증한다.
LLM-Modulo 의 "외부 sound 검증기" 역할이며, 학습·런타임이 **동일 함수**라 검증이 일관된다.

**신규 규칙(학습·런타임 공통):**
- deadline 알려진 경우 `due_date > deadline` task 금지(P1: 마감 이후 군더더기 차단).
- exam kind 는 deadline 날짜에 deadline 이벤트가 정확히 존재해야 함.
- **용량 규칙(우겨넣기 차단):** 하루 항목 수 ≤ 가용 용량. 초과면 통과 아님.

```
0단계 용량 N → 1단계 LLM(N개+상대배치) → 2단계 코드 매핑+clamp → check_plan_consistency
   ├─ 통과 → GenerateResult 반환
   └─ 용량 초과(안 맞음) → 우겨넣지 말고:
        · 유연 분량(routine/lifestyle): 개수·빈도 축소(주5→주3)로 자동 재배치
        · 고정 분량(exam): 사용자에게 알림("기간이 빠듯 — 핵심만 추리거나 기간 늘리자")
```

**우겨넣지 않는다(cram 금지).** 코드는 LLM 상대배치를 **재배열하지 않고** *매핑+clamp+용량검사*만 하고,
안 맞으면 **유연=축소 / 고정=사용자 통지**(LLM+P/LLM-Modulo 의 feasible-or-report 원칙).
재교정은 대개 코드 재실행(매핑+clamp, LLM 0회), LLM 재호출은 양 재조정이 필요할 때만 1회.
그래프 토폴로지 변화 최소(`plan_generator` self-loop 또는 검증 노드 1개).

### 3.6 slot-extractor 툴 훅 (설계만, v1 미구현)

L1 의 "툴 쓰는 추출" 다리는 **인터페이스 훅으로만** 둔다: `plan_kind`·미충족 슬롯에 따라
**그래프가** 외부 조회를 부를 자리. v1 에는 연결할 구체 툴이 없다(enrichment 는 D7 로 삭제,
캘린더 가용시간 조회는 미래). 모델-결정 tool-call 은 궤적 SFT 를 유발하므로 영구 비채택.

### 3.7 활동 라이브러리 — lifestyle 내용 품질 (D10, RAP/CBR)

P2 의 본질(lifestyle 백지 창작)을 해결하는 큐레이션 자산. 작은 모델이 내용을 **창작**하지 않고
라이브러리에서 **선택+개인화**한다(검색증강계획/사례기반).

**구조** (`planner/content_library.yaml`, 사람 큐레이션, 버전 핀):
```yaml
domains:
  운동: [{title: "30분 동네 산책", min: 30, cadence: "주3~5"},
         {title: "홈트 15분", min: 15, cadence: "주2~3"}, ...]
  학습: [{title: "영어 회화 20분", min: 20, cadence: "주3"}, ...]
  휴식: [...]; 관계: [...]; 정리: [...]
```

**흐름:** lifestyle 슬롯(domains 선택) → 코드가 해당 도메인 후보를 라이브러리에서 검색 →
모델은 후보 중 1~2개를 **고르고 말투/디테일만 개인화** → task 목록 확정 → allocator 배치.
vague_goal 은 "첫 행동" 후보를 같은 방식으로 라이브러리에서 검색.

**역할 3종:** ① 런타임 후보 소스 ② **SFT 시드**(시험 크롤 시드와 동형) ③ **eval 골든블록**.

**리스크(정직):** 라이브러리 빈약 → 플랜이 뻔해짐. 시작은 작게(약 5도메인 × 6활동), 점진 확장.
개인화는 라이브러리 항목에 **앵커**(off-library 환각 금지).

---

## 4. SFT 데이터셋 설계 (Dataset)

### 4.1 현재 SFT 구조 (참조)

- 레코드: `{"messages":[system?, user, assistant], "meta":{...}}` JSONL.
- assistant content = JSON 문자열. 플랜=`PlanOutput`(런타임 `GenerateResult` 미러:
  `summary_text/todos/calendar_events`), 꼬리질문=`{kind, question, missing_aspects}`.
- **기존 follow-up SFT(`build_ipe_followup_sft.py`)는 단일턴**(`turn_type:"single"`):
  underspecified 메시지 1개 → 질문 1개. *재개(사용자 답변→플랜)는 학습하지 않는다.*
- 검증 "2층": (1) Pydantic 미러 파싱 + (2) `check_plan_consistency`(날짜범위/C5/단조분해 품질).

### 4.2 핵심 변화 ①: 멀티턴

일상은 진짜 멀티턴이 필요하다. SFT 본질 등식 *"학습에서 본 토큰 == 추론 시 만들 토큰"* 을
지키기 위해, 멀티턴 레코드의 **각 assistant 턴은 정확히 런타임 노드가 방출하는 출력 JSON**
이어야 한다.

```
user(vague) → assistant(follow_up JSON) → user(answer) → assistant(task목록 JSON | next follow_up)
```

봇 주도 follow_up 은 **최대 2턴**(D9). 2턴 뒤엔 기본값을 채워 task 목록을 낸다.

### 4.3 핵심 변화 ②: plan 타깃 = 평평한 task 목록 (날짜 학습 안 함, D8)

뉴로-심볼릭 분업의 SFT 귀결: **모델이 학습하는 plan 턴 타깃은 절대 날짜 박힌 `PlanOutput` 이 아니라
task 목록 + 상대 배치**(`[{title, rel_day|order}]`)다. **절대 날짜 매핑(`GenerateResult`)은 추론 시
코드가 생성**하므로 학습 대상이 아니다. 모델은 *며칠차·리듬(상대)* 만 배우고 *달력 산수(절대)* 는 안 배운다.

- 작은 모델이 **절대 날짜 산수**를 학습할 필요 없음 — 상대 배치만(P1/P2 동시 해소).
- 기존 exam 크롤 SFT(절대 날짜 plan)는 **task 내용·순서 학습으로 여전히 유효**하되, 추론 시 코드가
  절대 날짜를 매핑+clamp. (v1 즉시 재라벨링 불필요 — date 필드는 상대 순서 신호로 재해석/무해.)
- routine 은 plan 턴 LLM 타깃이 없음(슬롯이 곧 정의, 코드가 cadence 펼침).

### 4.4 신규 빌더 (`sft_pipeline/build/`)

1. **`build_daily_followup_sft.py`** — (plan_kind × 미충족-슬롯-조합 × style) 시드로 멀티턴 트레이스 생성.
   `BASE_CASES` 처럼 시드는 결정론적, 재서술은 **로컬 모델**(기존 정책). `turn_type:"multi"`.
   봇 주도 follow_up ≤2턴(D9).
2. **일상 plan 타깃** — 정보 충분(또는 캡 도달+기본값) → **task 목록 + 상대 배치(rel_day)**(절대 날짜 없음, §4.3).
   절대 날짜 매핑은 학습 대상 아님(코드가 추론 시 생성). **lifestyle/vague_goal 타깃은
   `content_library.yaml`(§3.7)에서 생성** — 라이브러리 활동을 슬롯에 맞게 조합, 로컬모델 재서술.
3. **allocator 골든셋** — (task 목록 + 슬롯 + today/deadline) → 기대 `GenerateResult`. allocator(코드)
   단위 테스트용. LLM 무관, P1 회귀 방지.

`meta` 에 `domain:"daily"`, `plan_kind`, `missing_aspects`, `turn_type` 기록.

### 4.5 2층 검증 확장 (`validate_daily_sft.py` 신규 또는 `validate_dataset.py` 확장)

- **Layer 1 (스키마):** 모든 assistant 턴이 자기 kind 의 미러 스키마로 파싱(follow_up / task목록).
- **Layer 2 (의미 정합성):**
  - follow-up 은 *실제로 미충족인 필수 슬롯*을 물어야 한다.
  - task 목록은 *필수 슬롯이 전부 충족(또는 캡+기본값)된 뒤에만* 등장한다.
  - **allocator 출력 검증**: deadline 이후 task 없음(P1), routine 확장이 선언 요일·horizon 내,
    deadline 이벤트가 deadline 날짜에 존재(exam).
  - `check_plan_consistency`(날짜/C5/품질 + §3.5 신규 deadline 규칙) 재사용.

---

## 5. 논문 → 컴포넌트 매핑

| 컴포넌트 | 근거 |
| --- | --- |
| 스키마 뱅크 | Schema-Guided Dialogue (Rastogi 2020) |
| 최소 꼬리질문 | IN3, QuestBench |
| 언제 그만 물을까 | AskBench / rubric-RLVR, `follow_up_count` 캡 |
| 반복/제약 분배 | MeetMate, Natural Plan (v1 은 solver 없이 LLM-side + horizon 확장) |
| 멀티턴 sufficiency 학습 | "Teaching LMs to Gather Information Proactively" (EMNLP 2025) |
| 런타임 critic 자기교정 | Reflexion; LLM-Modulo generate-test-critique (검증기를 순수 함수로) |
| 뉴로-심볼릭 분업 (LLM=무엇을, 코드=언제) | LLM+P, LLM-Modulo (Kambhampati ICML 2024), "LLMs as Planning Formalizers" survey (ACL 2025) |
| 소형 모델일수록 분업 이득 | 뉴로-심볼릭 + local model 연구(성공률↑·스텝↓·속도↑) |
| 마감일 등 제약은 심볼릭으로 | R-ConstraintBench, Haste Makes Waste, LexiCon (LLM이 시간/선후/자원 제약에 취약) |
| 라이브러리 기반 내용(선택+개인화) | RAP(Retrieval-Augmented Planning), CBR(Case-Based Reasoning) for LLM Agents, HiPlan |

---

## 6. 영향 범위 (Touch List)

**신규:**
- `agents/todo_creation/planner/slot_schemas.py` — 스키마 뱅크 레지스트리
- `agents/todo_creation/planner/allocator.py` — 결정적 날짜 배치기(마감일 앵커, ~50줄, D8)
- `agents/todo_creation/planner/content_library.yaml` — 큐레이션 활동 라이브러리(D10, §3.7)
- `sft_pipeline/build/build_daily_followup_sft.py` — 멀티턴 일상 follow-up 빌더
- `sft_pipeline/build/validate_daily_sft.py`(또는 기존 확장) — 2층 검증 확장

**변경:**
- `planner/nodes/planner.py` — sufficiency 를 스키마 구동으로
- `planner/nodes/plan_generator.py` — LLM(task 목록) → `allocator` 호출 분리(D8) + critic 재검증 루프(§3.5)
- `planner/goal_rules.py` — 시험 전용 로직을 exam 스키마 엔트리로 흡수(축소)
- `agents/todo_creation/state.py` — `ParsedGoal` 에 `plan_kind`/일상 슬롯 추가

**삭제 (D7 — enrichment 일괄 제거):**
- `planner/nodes/enrichment.py` (그래프 미연결 orphan)
- `adapters/todo_creation/tavily_enrichment.py` (Tavily 조회 어댑터)
- `ports.enrichment` 와이어링 (config/deps 의 enrichment 포트 등록)
- 테스트: `tests/agents/todo_creation/planner/nodes/test_enrichment.py`,
  `tests/adapters/todo_creation/test_tavily_enrichment.py`
- (정리) `enrichment_context`/`enrichment_done` 잔여 state 키 참조

**불변(중요):**
- 그래프 토폴로지(critic self-loop 외), `interrupt`/resume, `GenerateResult`/`PlanOutput` 미러, DB 스키마, 서버·web.

---

## 7. 비범위 (Out of Scope)

- RRULE 진짜 반복 규칙 필드 및 그에 따른 DB/서버/web 변경.
- 외부 제약 solver(Timefold/CP) 도입.
- **모델-결정 tool-call**(에이전트 궤적 SFT) 및 L2 멀티에이전트/L3 Deep Agent 구조.
- slot-extractor 의 구체 툴(캘린더 가용시간 조회 등) — §3.6 훅만 두고 미래 확장.
- **큰 모델 증류(teacher distillation)** — lifestyle 내용은 사람 큐레이션 라이브러리로(D10), "합성은 로컬" 정책 유지.
- 단기기억 영속화(Redis 체크포인터) 등 별도 리팩토링 후보 — `docs/features/todo/chatbot-flow-and-memory.md` 참조.
- 런타임 코드의 실제 구현 및 SFT 학습 실행(다음 단계: `writing-plans`).

---

## 8. 성공 기준 (검증 가능)

1. `SLOT_SCHEMAS` 에 4개 plan_kind 엔트리가 정의되고, exam 엔트리가 기존 `goal_rules` 거동을 재현한다.
2. `judge_sufficiency` 가 일상 3종에 대해 올바른 `plan_kind` + 미충족 필수 슬롯을 반환한다(테스트).
3. routine 입력이 allocator horizon 확장으로 날짜별 `calendar_events` 가 되고 `check_plan_consistency` 통과.
3b. **P1 회귀 테스트:** "일주일 뒤 시험" → deadline 날짜에 시험 이벤트, deadline 이후 task 0개(회고 없음).
3c. 봇 주도 follow_up 이 어떤 일상 케이스에서도 ≤2턴, 캡 도달 시 기본값으로 task 목록 생성(D9).
3d. **lifestyle 내용 eval(D10):** 생성 플랜이 ≥3개 도메인 커버, 활동이 라이브러리에 앵커됨,
    하루 항목 수 현실적(예: ≤2). 라이브러리 골든블록 기준 회귀 측정.
3e. **우겨넣기 방지 테스트:** 과다 목표(예: 1일에 20개) 입력 시 하루 용량 초과 없이,
    유연 분량은 축소·고정 분량은 사용자 통지가 일어난다(cram·silent-drop 0).
4. 멀티턴 일상 SFT 레코드가 2층 검증(스키마 + 의미)을 통과한다.
5. 미러 동기화 테스트(`test_plan_schemas.py::test_mirror_matches_runtime_schema`)가 깨지지 않는다.
6. critic 루프: 의도적으로 정합성 깨진 플랜이 재생성 1회로 교정되거나 정책대로 폴백한다(테스트).
7. enrichment 일괄 삭제 후 전체 테스트 스위트가 그린(잔여 import/port 참조 0).

---

## 9. 단계별 롤아웃 (Phasing)

작은 버그(P1)를 큰 구조 베팅과 분리한다. 각 Phase 는 **독립 출고·검증 가능**.

### Phase 0 — P1 핫픽스: 프롬프트 + 영구 clamp (즉시)
- **프롬프트:** plan 생성에 "시험 = 마지막 날, 마감 이후 task 금지, 상대 배치로 리듬" 지시(배치 품질↑).
- **영구 clamp(코드, throwaway 아님):** `check_plan_consistency` 에 deadline 규칙(마감 이후 금지) 추가 +
  생성 결과를 마감일에 앵커·clamp. 이 규칙은 Phase 2 매핑·SFT 검증에서도 재사용되는 **영구물**.
- 회귀 테스트(성공기준 3b). 구조 변경 최소 — 오늘 고칠 수 있는 버그.
- 의존성: 없음. (Phase 2 가 상대→절대 매핑으로 일반화하지만, clamp 규칙은 그대로 승계 — 버려지는 코드 없음.)

### Phase 1 — 스키마 뱅크 + routine/vague_goal (내용 부담 적은 종류)
- `slot_schemas.py`, `judge_sufficiency` 스키마 구동(plan_kind 5종 분류), follow_up ≤2턴(D9).
- `allocator.py` 기본형(마감일 앵커 배치 + routine horizon 확장).
- **enrichment 일괄 삭제**(D7).
- lifestyle 은 아직 제외(내용 라이브러리 없음). vague_goal 은 소규모 후보로.
- 의존성: Phase 0 의 deadline 규칙 재사용.

### Phase 2 — 뉴로-심볼릭 완성 + lifestyle 라이브러리 + SFT
- `plan_generator` 분업 완성(LLM task목록 → allocator), critic 루프.
- `content_library.yaml`(D10) + lifestyle 경로.
- 멀티턴 SFT 빌더(§4.4) + 2층 검증 확장(§4.5) + lifestyle 내용 eval(성공기준 3d).
- 의존성: Phase 1 의 스키마 뱅크·allocator.

**원칙:** Phase 0 은 버그 수정이라 단독 머지. Phase 1·2 는 검증하며 순차 진행. 각 Phase 종료 시
`docs/features/todo/architecture.mmd` as-built 갱신(CLAUDE.md DoD).
