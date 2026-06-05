# 전처리 배치 보고서 - 배치 #<NN>

- **수집 일자:** YYYY-MM-DD
- **담당자:** <이름>
- **대상 시험:** <예: 토익, SQLD>

## 1. 수집 요약

| 항목 | 수 |
| --- | --- |
| 수집 후보 URL | 0 |
| robots 차단 제외 | 0 |
| 본문 추출 실패 | 0 |
| 광고/협찬 제외 | 0 |
| 최종 선정 | 0 |

## 2. 제외 사유 집계

| 사유 | 건수 | 비고 |
| --- | --- | --- |
| robots_disallow | 0 | |
| 본문 < min_length | 0 | |
| 광고성/협찬 | 0 | |
| 중복 | 0 | |

## 3. 적용한 정규화 규칙

- 기간: D-7 / 일주일 / 2주 → time_left_days
- 하루 시간: 하루 4시간 / 3~5시간 → daily_hours_value(+min/max)
- 누락값: 미기재→공란, 추정 금지, 모호→review_flags

## 4. 품질 점검 체크리스트

- [ ] exam_type 표준코드로 매핑됨 (review_flags에 exam_type_unmapped 없음)
- [ ] time_left/daily_hours 정규화 값 확인
- [ ] result 합격/불합격 정확
- [ ] actual_plan_summary 원문 복붙 아님(재서술)
- [ ] evidence_spans ≤200자
- [ ] validate_dataset.py errors=0

## 5. 메모 / 다음 배치 이월 사항

- ...
