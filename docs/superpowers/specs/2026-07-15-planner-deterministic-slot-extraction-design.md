# 결정적 슬롯 추출 (planner over-clarification 근본 수정)

- 날짜: 2026-07-15
- 브랜치: `feat/planner-deterministic-slot-extraction` (PR #191 데이터셋 위에 스택)
- 관련: `agents/todo_creation/planner/` (nodes/planner.py, goal_rules.py, allocator.py, date_parser.py, slot_schemas.py)

## 배경 / 문제

19케이스 확장 eval(`planner-8b17283c`)에서 routing_correct 0.63, candidates 기대 10건 중 실제 도달 3건. 나머지가 follow_up으로 새는 근본 원인은 **모델(judge_sufficiency)이 사용자가 명시한 결정적 정보를 슬롯으로 추출하지 못함**:

| 케이스 | missing | 원인 |
| --- | --- | --- |
| 포트폴리오 "하루 2시간, 다음 달까지" | horizon, available_time | 둘 다 말했는데 미추출 |
| 발표자료 "매일 1시간, 금요일" | available_time | "매일 1시간" 미추출 |
| 월수금 러닝 | cadence | 요일 cadence 미추출(+복구 불가) |
| 매일 아침 독서 | cadence | "매일" cadence 미추출(+복구 불가) |

`json_mode`/`guided_json`(구조 강제화)는 **형식**만 보장하지 **값 추출**을 못 함. slots를 required로 강제하면 환각 유발(현재 프롬프트가 일부러 방지). LangChain OutputParser류는 파싱 오류 복구용이라 값 누락엔 무효. → **결정적으로 파싱 가능한 값(날짜·기간·빈도)은 코드가 텍스트에서 직접 추출**해야 한다(LLM-Modulo: 결정적인 건 코드가 authoritative).

## 목표 / 비목표

목표
- 사용자 텍스트에서 **날짜(horizon/deadline)·기간(available_time)·빈도(cadence)**를 결정적으로 추출해 슬롯을 채운다. 코드값이 authoritative(있으면 우선), 없으면 모델 slots fallback.
- 흩어진 복구(`recover_cadence`·`merge_deadline`·iter3 cadence 패치)를 이 경로로 통합.
- **작은 코드** — 신규 모듈/거창한 추상화 없이 기존 파서 재사용 + 정규식 확장 + 배선.

비목표
- exam_part(토익/JLPT), 한국사 오분류 = 분류/도메인 문제라 **별도 iteration**.
- required 슬롯 **세트 불변**(바는 적정 — 진짜 모호한 케이스는 여전히 물어야 함; "살 빼고 싶어"·"영어 잘하고 싶어"가 follow_up 맞게 나옴).
- 의미적 슬롯(domains·current_level·background) 제외(결정적 아님).
- 새 LLM/에이전트 추가 없음(순수 코드).

## 설계

### 1. 파서 (기존 재사용 + 소량 확장)
- **날짜** — `date_parser.parse_explicit_deadline(text, today)` **그대로 재사용**.
- **빈도** — `allocator.recover_cadence` **확장**: 현재 "주 N회"만 → 명시 요일("월수금")·"매일"도 반환.
- **기간** — **신설** `parse_daily_capacity(text) -> str | None`: "하루/매일 N시간·분" 정규식 파싱, 정규화 문자열 반환.

### 2. 추출 + 매핑 (planner_node 배선)
`planner_node`의 else-분기(비 exam/event)에서 `missing_required` **직전에**, `collect_user_text(state)`로 추출한 값을 plan_kind 슬롯 이름에 매핑해 채운다:
- date → exam:`exam_date` / event:`event_date` / 그 외:`horizon`
- freq → routine:`cadence` / event·vague_goal:`weekly_cadence`
- duration → exam:`daily_hours` / project:`available_time`
- **authoritative**: 코드 파싱값이 있으면 그 슬롯에 세팅(모델값 덮음), 없으면 모델값 유지.
- 기존 iter3 cadence 패치(157–161줄)는 이 로직으로 대체·통합.

### 3. 경계 / 리스크
- 파서는 **보수적**(명확한 패턴만 발화) → authoritative 오파싱으로 정상값 clobber 방지.
- exam/event는 이미 전용 normalize 경로가 있으므로, 매핑은 충돌 없이 보강만.

## 테스트
- **파서 순수 유닛테스트** — 실패 케이스 그대로: "다음 달까지"→date, "하루 2시간"/"매일 1시간"→duration, "월수금"/"매일"→freq. 각 pass/fail + 음성(추출 없어야 하는 모호 입력).
- **배선 테스트** — planner_node에서 미추출 슬롯이 채워져 sufficient→plan_generator (iter3 회귀 테스트와 동형).
- **통합** — 19케이스 eval before(`planner-8b17283c`)/after.

## 성공 기준
- 추출 실패 4건(포트폴리오·발표자료·월수금·매일 독서)이 **candidates 도달**(한국사는 분류 이슈라 제외).
- routing_correct 상승, 다른 지표 회귀 0, 환각 슬롯 0(korean_only·structure_valid 유지).

## 미해결(후속)
- exam_part 파트 없는 시험(토익/JLPT), 한국사 project 오분류 = 별도 분류 iteration.
- 검증은 19케이스 데이터셋(PR #191) 필요 — 이 브랜치가 그 위에 스택.
