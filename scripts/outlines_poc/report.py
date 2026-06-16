"""측정 결과 → 결과 노트북(.ipynb) 빌더.

run.py 가 --report 로 호출. GPU·vLLM 불필요(순수 파이썬, dict→ipynb).
요약표 + 변종별 프롬프트 상세표 + 자동 판정 + 권장사항을 담은 standalone 보고서.
"""

from __future__ import annotations

import json
from typing import Any

_SAMPLE_MAX = 160


def _md_cell(text: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def _esc(text: str) -> str:
    """마크다운 표 셀용: 파이프·개행 무력화 + 길이 제한."""
    s = str(text).replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    return s[:_SAMPLE_MAX] + ("…" if len(s) > _SAMPLE_MAX else "")


def _yn(flag: bool) -> str:
    return "✅" if flag else "—"


def _summary_table(rows: list[dict]) -> str:
    head = "| variant | json_ok% | cjk% | strict% | mean_ms |\n|---|---|---|---|---|\n"
    body = "".join(
        f"| `{r['variant']}` | {r['json_ok%']:.1f} | {r['cjk%']:.1f} | "
        f"{r['strict%']:.1f} | {r['mean_ms']:.0f} |\n"
        for r in rows
    )
    return head + body


def _detail_table(records: list[dict]) -> str:
    head = (
        "| # | 입력 | 기대 | json_ok | cjk | strict | ms | 출력 샘플 |\n"
        "|---|---|---|---|---|---|---|---|\n"
    )
    body = ""
    for i, rec in enumerate(records, 1):
        body += (
            f"| {i} | {_esc(rec['prompt'])} | {rec['expect']} | "
            f"{_yn(rec['json_ok'])} | {'⚠️' if rec['cjk'] else '—'} | "
            f"{_yn(rec['strict'])} | {rec['ms']:.0f} | `{_esc(rec['raw'])}` |\n"
        )
    return head + body


def _verdict(rows: list[dict]) -> str:
    """수치에서 자동 판정 한 줄(발표용 결론 초안)."""
    if not rows:
        return "_측정 결과 없음_"
    best_json = max(rows, key=lambda r: r["json_ok%"])
    low_cjk = min(rows, key=lambda r: r["cjk%"])
    lines = [
        f"- json_ok 최고: **`{best_json['variant']}`** ({best_json['json_ok%']:.1f}%)",
        f"- cjk 최저(한자 누출 최소): **`{low_cjk['variant']}`** ({low_cjk['cjk%']:.1f}%)",
    ]
    native = next((r for r in rows if r["variant"] == "vllm_native"), None)
    if native is not None:
        if native["cjk%"] == 0:
            lines.append(
                "- ✅ `vllm_native`의 cjk%=0 → **기본 백엔드가 한자 금지 pattern을 강제**. "
                "새 의존성 없이 후보1 해결 가능."
            )
        else:
            lines.append(
                f"- ⚠️ `vllm_native`의 cjk%={native['cjk%']:.1f} → 기본 백엔드가 string "
                "pattern을 완전히 강제하지 못함. **outlines 백엔드 강제 또는 경로B 필요**."
            )
    return "\n".join(lines)


def build_report_notebook(
    *, meta: dict, rows: list[dict], records_by_variant: dict[str, list[dict]], out_path: str
) -> None:
    cells: list[dict] = []

    cells.append(
        _md_cell(
            "# 구조화 생성 PoC — 측정 결과 보고서\n"
            "## `outlines` / vLLM structured outputs (후보1 중국어 차단 + 후보2 JSON 강제)\n\n"
            f"- 실행 시각: **{meta.get('timestamp', '?')}**\n"
            f"- 베이스 모델: `{meta.get('model', '?')}`\n"
            f"- LoRA: `{meta.get('lora', '(none)')}`\n"
            f"- 프롬프트 수: **{meta.get('n', '?')}**  / 변종: "
            f"{', '.join(f'`{v}`' for v in meta.get('variants', []))}\n\n"
            "> 설계·배경은 `outlines_structured_generation_report.ipynb` 참조. "
            "본 문서는 **실측 결과**다."
        )
    )

    cells.append(
        _md_cell(
            "## 1. 요약\n\n"
            + _summary_table(rows)
            + "\n**지표:** `json_ok%`=production 수용 가능 JSON(CJK 무관) · "
            "`cjk%`=한자/가나 누출률(↓좋음) · `strict%`=제약 스키마(한자 금지 포함) 완전 통과 · "
            "`mean_ms`=평균 생성 지연.\n\n"
            "### 자동 판정\n" + _verdict(rows)
        )
    )

    cells.append(_md_cell("## 2. 변종별 프롬프트 상세"))
    for v in meta.get("variants", []):
        recs = records_by_variant.get(v, [])
        cells.append(_md_cell(f"### `{v}`\n\n" + _detail_table(recs)))

    cells.append(
        _md_cell(
            "## 3. 권장 (결과 해석 가이드)\n"
            "- `vllm_native`가 `json_ok%`~100 & `cjk%`=0 이면 → **새 의존성 0으로 후보1+2 해결**. "
            "`runpod_workers/llm/pipeline.py`에 `structured_outputs` 주입으로 바로 적용.\n"
            "- `cjk%`가 0이 아니면 → outlines 백엔드 강제 또는 `outlines_direct` 채택 검토.\n"
            "- `mean_ms` 증가폭이 크면 → 콜드스타트 잦은 서버리스 특성상 트레이드오프 재평가.\n"
            "- 다음 단계: 후보3(날짜)·후보4(enum)로 확장하며 어댑터의 재시도/가드/후처리 제거."
        )
    )

    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)
