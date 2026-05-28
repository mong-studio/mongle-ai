# Combined Evaluation Files

원본 `data/evaluation/` 파일은 삭제하지 않고, 평가 종류별로 다시 묶은 파일입니다.

| 파일 | 설명 | 행 수 | 원본 패턴 |
|---|---|---:|---|
| `raw_outputs_all.jsonl` | 모델별 원문 응답, parsed_output, auto_eval, latency를 모두 합친 JSONL | 350 | `raw_outputs*.jsonl` |
| `auto_scores_all.json` | 규칙 기반 자동 평가 결과 전체를 합친 JSON | 350 | `auto_scores*.json` |
| `auto_scores_all.csv` | auto_eval 세부 필드를 펼친 자동 평가 CSV | 350 | `auto_scores*.json` |
| `judge_scores_all.jsonl` | GPT judge 정성 평가 결과 전체 JSONL | 350 | `judge_scores*.jsonl` |
| `judge_scores_all.csv` | judge_scores/judge_reasons를 펼친 정성 평가 CSV | 350 | `judge_scores*.jsonl` |
| `final_summary_all.csv` | 모델별 기능 평균 및 Final 점수를 모두 합친 CSV | 35 | `final_summary*.csv` |
| `failure_cases_all.jsonl` | 파싱/스키마/길이 등 실패 케이스 전체 JSONL | 233 | `failure_cases*.jsonl` |
| `failure_cases_all.csv` | 실패 케이스를 펼친 CSV | 233 | `failure_cases*.jsonl` |
| `semantic_similarity_all.csv` | Embedding Cosine 및 BERTScore 세부 결과 | 350 | `semantic_similarity_scores.csv` |
| `semantic_distinct_model_summary_all.csv` | 모델별 의미 유사도/다양성 요약 | 7 | `semantic_distinct_model_summary.csv` |
| `semantic_distinct_task_summary_all.csv` | 모델+태스크별 의미 유사도/다양성 요약 | 35 | `semantic_distinct_task_summary.csv` |
| `distinct_scores_all.csv` | Distinct-1/Distinct-2 세부 결과 | 35 | `distinct_scores.csv` |
| `pairwise_cosine_similarity_all.csv` | 모델 쌍별 Pairwise Cosine 세부 결과 | 1050 | `pairwise_cosine_similarity.csv` |
| `pairwise_cosine_summary_all.csv` | 모델 쌍별 Pairwise Cosine 요약 | 105 | `pairwise_cosine_summary.csv` |
| `model_comparison_all.csv` | 기존 Final 점수와 새 의미/다양성 지표를 합친 모델별 비교표 | 7 | `final_summary*.csv + semantic_distinct_model_summary.csv` |

## 추천해서 볼 파일

- `model_comparison_all.csv`: 모델별 종합 점수와 새 지표를 한 번에 보기 좋음
- `final_summary_all.csv`: 기능별 기존 Auto/Judge/Final 결과
- `semantic_distinct_model_summary_all.csv`: 모델별 Embedding/BERTScore/Distinct 요약
- `judge_scores_all.csv`: judge 세부 점수와 사유를 표 형태로 확인
- `raw_outputs_all.jsonl`: 모델 원문 출력 전체 보관용
