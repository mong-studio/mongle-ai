"""일상(§4.6) SFT 데이터 파이프라인 스모크 노트북 생성기.

`sft_pipeline/eval/daily_sft_smoke.ipynb` 를 결정적으로 빌드한다(손으로 JSON 쓰지 않음).
다시 만들려면: `uv run python scripts/build_daily_sft_smoke_notebook.py`

이 노트북은 §4.6 데이터 파이프라인(crawl→추출→structure→노드 빌더→검증)을
RunPod pod(또는 로컬)에서 한 셀씩 돌려보고, 생성된 SFT 레코드를 눈으로 확인하기 위한 것.
파이프라인 본체는 CPU 만으로 돌아간다(GPU 불필요). GPT-4o 라이브 추출 섹션만 OPENAI_API_KEY 필요,
학습(Task 11)은 별도 GPU 단계.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "sft_pipeline/eval/daily_sft_smoke.ipynb"


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _src(lines)}


def code(*lines: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": _src(lines),
    }


def _src(lines: tuple[str, ...]) -> list[str]:
    text = "\n".join(lines)
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


CELLS = [
    md(
        "# 일상(§4.6) SFT 데이터 파이프라인 스모크",
        "",
        "**대상:** 설계서 §4.6 — 진짜 한국어 일상 후기를 크롤→GPT-4o 특징추출→**결정론 타깃**으로",
        "가공해 planner 의 비-시험(일상) judge·generator·critic 노드 SFT 데이터를 만든다.",
        "",
        "## 파이프라인 (시험 파이프라인 미러)",
        "```",
        "raw_daily.csv  ──(run_daily_structure)──▶  structured_daily.csv",
        "structured_daily.csv  ──(build_daily_nodes_sft)──▶  daily_nodes.jsonl  (judge·goal_tag·generator·critic)",
        "structured_daily.csv  ──(build_daily_followup_sft)──▶  daily_followup.jsonl  (멀티턴 judge)",
        "daily_nodes.jsonl  ──(validate_dataset·coherence_eval·daily_triviality_scan)──▶  품질 게이트",
        "```",
        "**GPT-4o 는 features 추출만**(구조 JSON 타깃은 코드 결정론). 라이브 크롤·추출은 §5(게이팅).",
        "",
        "## RunPod pod 에서 실행",
        "```bash",
        "# pod 안, 리포 루트에서",
        "uv sync",
        "uv run jupyter lab --ip 0.0.0.0 --no-browser --allow-root",
        "# 또는 비대화 실행:",
        "uv run --with jupyter --with nbconvert jupyter nbconvert \\",
        "  --to notebook --execute --inplace sft_pipeline/eval/daily_sft_smoke.ipynb",
        "```",
        "데이터 파이프라인 본체는 **CPU 만으로** 돈다(GPU 불필요). §5 라이브 추출만 `OPENAI_API_KEY` 필요.",
    ),
    md("## 0. 셋업"),
    code(
        "import sys, json",
        "from datetime import date",
        "from pathlib import Path",
        "",
        "# 리포 루트를 path 에 추가(노트북이 sft_pipeline/eval/ 에 있어도 cwd 기준 탐색).",
        "ROOT = Path.cwd()",
        "while not (ROOT / 'sft_pipeline').is_dir() and ROOT != ROOT.parent:",
        "    ROOT = ROOT.parent",
        "if str(ROOT) not in sys.path:",
        "    sys.path.insert(0, str(ROOT))",
        "print('repo root:', ROOT)",
        "",
        "TODAY = date(2026, 6, 24)  # 결정적 재현용 고정 기준일",
        "OUT_DIR = Path('/tmp/daily_sft_smoke'); OUT_DIR.mkdir(parents=True, exist_ok=True)",
        "FIXTURE = ROOT / 'sft_pipeline/fixtures/raw_daily.csv'",
        "print('fixture exists:', FIXTURE.exists())",
    ),
    md(
        "## 1. raw_daily → structured_daily",
        "",
        "픽스처(진짜 후기 발췌 형식의 소량 샘플)를 정규화한다. `real_breakdown` 은",
        "`활동|빈도|시간대; 활동|빈도|시간대` 형식, `domains` 는 택소노미(운동·학습·휴식·관계·정리).",
        "`review_flags` 가 비어 있어야 깨끗한 케이스다(plan_kind·domain·cadence 매핑 성공).",
    ),
    code(
        "import csv",
        "from sft_pipeline.structure.run_daily_structure import read_raw_daily, write_structured_daily",
        "",
        "raw_rows = read_raw_daily(FIXTURE)",
        "structured_path = OUT_DIR / 'structured_daily.csv'",
        "n = write_structured_daily(raw_rows, structured_path)",
        "print(f'structured {n} cases -> {structured_path}')",
        "",
        "for r in csv.DictReader(open(structured_path, encoding='utf-8')):",
        "    print(f\"[{r['plan_kind']:9}] {r['goal_text']:14} domains={r['domains']:12}\"",
        "          f\" cadence={r['cadence']:6} horizon={r['horizon_days']:>3} flags={r['review_flags'] or '(none)'}\")",
        "    print('      real_breakdown:', r['real_breakdown'])",
    ),
    md(
        "## 2. structured_daily → 노드 SFT 레코드",
        "",
        "케이스당 judge·goal_tag·generator·critic(positive/offgoal/triviality) 레코드를 만든다.",
        "**generator 타깃은 추출된 `real_breakdown` 그대로**(필러 잡무 합성 없음).",
        "시스템 프롬프트는 런타임 미러 상수 재사용(train==serve).",
    ),
    code(
        "from collections import Counter",
        "from sft_pipeline.build.lib.build_daily_nodes_sft import build_samples as build_nodes",
        "from sft_pipeline.io_utils import write_jsonl",
        "",
        "samples = build_nodes(structured_path, today=TODAY)",
        "nodes_path = OUT_DIR / 'daily_nodes.jsonl'",
        "write_jsonl(samples, nodes_path)",
        "print('records:', len(samples), '->', nodes_path)",
        "print('node 분포:', dict(Counter(s['meta']['node'] for s in samples)))",
        "print('provenance:', dict(Counter(s['meta']['provenance'] for s in samples)))",
    ),
    md("### 2-1. 노드별 샘플 들여다보기 (judge / generator / critic)"),
    code(
        "def show(node, label=None, n=1):",
        "    hits = [s for s in samples if s['meta']['node'] == node",
        "            and (label is None or s['meta'].get('label') == label)]",
        "    for s in hits[:n]:",
        "        print('='*70)",
        "        print('NODE:', node, '| label:', s['meta'].get('label', '-'), '| prov:', s['meta']['provenance'])",
        "        print('--- user (앞 300자) ---')",
        "        print(s['messages'][1]['content'][:300])",
        "        print('--- assistant ---')",
        "        print(json.dumps(json.loads(s['messages'][-1]['content']), ensure_ascii=False, indent=2)[:900])",
        "",
        "show('judge')",
    ),
    code("show('generator')"),
    code(
        "# critic positive vs triviality(필러 잡무) negative 대비",
        "show('critic', label='positive')",
        "show('critic', label='triviality')",
    ),
    md(
        "## 3. 멀티턴 follow-up (history-내재 judge 레코드)",
        "",
        "저정보 입력 → 꼬리질문 → 답변 후 judge(충분). 런타임 재진입(planner.py)과 동일하게",
        "직전 Q&A 는 **user content 의 history** 에 내재(단일 judge 레코드, 시스템 프롬프트 1개).",
    ),
    code(
        "from sft_pipeline.build.lib.build_daily_followup_sft import build_samples as build_followup",
        "",
        "fu = build_followup(structured_path, TODAY)",
        "fu_path = OUT_DIR / 'daily_followup.jsonl'",
        "write_jsonl(fu, fu_path)",
        "print('multiturn records:', len(fu), '->', fu_path)",
        "if fu:",
        "    s = fu[0]",
        "    print('roles:', [m['role'] for m in s['messages']], '| turn_type:', s['meta']['turn_type'])",
        "    print('missing_aspects:', s['meta']['missing_aspects'])",
        "    print('--- user (history 내재) ---'); print(s['messages'][1]['content'][:400])",
        "    print('--- assistant judge ---')",
        "    print(json.dumps(json.loads(s['messages'][-1]['content']), ensure_ascii=False, indent=2)[:500])",
    ),
    md(
        "## 4. 품질 게이트 — validate · coherence · daily triviality",
        "",
        "- `validate_dataset` : 1층(형식·언어) + 2층(플랜 정합성, exam/daily-latte 만). daily 노드는 1층.",
        "- `eval_dataset` : 정량 지표(중복·길이·기계적 분해 등).",
        "- `daily_triviality_scan` : **daily generator 레코드의 days[] 제목을 직접 스캔**해 필러 잡무 비율 측정",
        "  (§4.6 anti-filler — PLAN_PROVENANCES 무관).",
        "",
        "기대: validate `errors=0`, daily triviality `value≈0`(픽스처가 깨끗하면).",
    ),
    code(
        "from sft_pipeline.build.lib.validate_dataset import validate_samples",
        "from sft_pipeline.build.lib.coherence_eval import eval_dataset, daily_triviality_scan",
        "",
        "rep = validate_samples(nodes_path)",
        "print(f\"[validate] ok={rep['ok']} errors={len(rep['errors'])}\")",
        "for e in rep['errors'][:10]:",
        "    print('  -', e)",
        "assert not rep['errors'], '검증 오류 — 위 메시지 확인'",
    ),
    code(
        "triv = daily_triviality_scan(samples)",
        "print('[daily triviality]', json.dumps(triv, ensure_ascii=False, indent=2))",
        "",
        "# 정량 지표 요약(generator days[] 는 PlanOutput 미러가 아니라 plan 게이트엔 안 잡힘 — 분포만 참고)",
        "rep2 = eval_dataset(samples)",
        "print('n_samples:', rep2['n_samples'], '| by_provenance:', rep2['by_provenance'])",
    ),
    code(
        "# generator 제목에 필러 잡무(확인/점검/정리)가 없어야 한다(positive 경로)",
        "bad = []",
        "for s in samples:",
        "    if s['meta']['node'] != 'generator':",
        "        continue",
        "    a = json.loads(s['messages'][-1]['content'])",
        "    for d in a.get('days', []):",
        "        for t in d.get('tasks', []):",
        "            if any(w in t['title'] for w in ('확인', '점검', '정리')):",
        "                bad.append(t['title'])",
        "print('generator 필러 제목:', bad or '(없음 — OK)')",
        "assert not bad, 'generator positive 경로에 필러 잡무가 새어 들어감'",
    ),
    md(
        "## 5. (선택·게이팅) 라이브 크롤 + GPT-4o 특징추출",
        "",
        "진짜 URL 에서 본문을 긁어(robots 준수) GPT-4o 로 features 를 추출한다.",
        "**`OPENAI_API_KEY` 가 있을 때만** 동작(없으면 추출기가 `None` 반환). `RUN_LIVE=True` 로 켠다.",
        "ToS·robots 를 보수적으로 준수하고, 공개 가능한 소량 URL 만 쓴다.",
    ),
    code(
        "RUN_LIVE = False  # ← OPENAI_API_KEY 준비 후 True 로",
        "",
        "if RUN_LIVE:",
        "    import os",
        "    from sft_pipeline.crawl.run_crawl import run as crawl_run",
        "    from sft_pipeline.crawl.daily_extractor import build_client_from_env, extract_daily_features",
        "",
        "    # 1) URL 목록(공개·robots 허용 소량). pod 의 /tmp 에 작성.",
        "    urls_path = OUT_DIR / 'urls.txt'",
        "    urls_path.write_text('\\n'.join([",
        "        '# 여기에 진짜 일상 후기 URL 을 한 줄씩 (robots 허용·ToS 준수)',",
        "        # 'https://blog.example.com/my-running-routine',",
        "    ]), encoding='utf-8')",
        "    crawl_csv = OUT_DIR / 'crawl_results.csv'",
        "    rows = crawl_run(urls_path=urls_path, out_csv=crawl_csv)",
        "    print('crawled:', len(rows), '| robots-blocked:',",
        "          sum(1 for r in rows if r['error'] == 'robots_disallow'))",
        "",
        "    # 2) GPT-4o 특징 추출(키 없으면 client=None → 모두 None 드롭)",
        "    client = build_client_from_env()",
        "    print('OpenAI client:', 'OK' if client else 'None(키 없음 — 추출 스킵)')",
        "    extracted = []",
        "    for r in rows:",
        "        if r.get('error') or not r.get('extracted_text'):",
        "            continue",
        "        feat = extract_daily_features(r['extracted_text'], source_url=r['source_url'],",
        "                                      source_type='blog', client=client)",
        "        if feat:",
        "            extracted.append(feat)",
        "    print('추출 성공:', len(extracted), '/', len(rows))",
        "    for f in extracted[:3]:",
        "        print(' ', f['plan_kind'], '|', f['goal_text'], '| rb:', f['real_breakdown'][:60])",
        "    # 3) extracted → raw_daily.csv 로 저장하면 §1~4 를 이 데이터로 재실행 가능.",
        "else:",
        "    print('RUN_LIVE=False — 라이브 크롤/추출 건너뜀(OPENAI_API_KEY 준비 후 True)')",
    ),
    md(
        "## 다음 단계",
        "",
        "- 라이브 추출(§5)로 모은 `raw_daily.csv` 로 §1~4 재실행 → 진짜 데이터 품질 확인.",
        "- 충분히 쌓이면 **시험 + 일상 혼합**(`mix_dataset`, 회귀 방지) → `train/train_lora.py` 로 planner LoRA 재학습(Task 11, GPU).",
        "- 학습 전/후 `scripts/live_planner_smoke.py` + `daily_triviality_scan` 으로 슬롯 환각·필러 잡무 감소 측정.",
    ),
]


def main() -> None:
    for i, cell in enumerate(CELLS):
        cell["id"] = f"cell-{i:02d}"
    nb = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT} ({len(CELLS)} cells)")


if __name__ == "__main__":
    main()
