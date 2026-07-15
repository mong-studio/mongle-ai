"""두 LangSmith 실험의 평가자 평균을 뽑아 before/after HTML 비교표를 만든다.

실행:
  uv run python -m llm_evaluation.langsmith.compare <before_experiment> <after_experiment> -o compare.html
"""
from __future__ import annotations

import argparse
import html as _html


def experiment_scores(client, experiment: str) -> dict[str, float]:
    """실험(=LangSmith project)의 평가자별 평균 점수를 반환."""
    stats = client.read_project(project_name=experiment).feedback_stats or {}
    return {key: float(v.get("avg", 0.0)) for key, v in stats.items()}


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render_comparison_html(
    before: dict[str, float],
    after: dict[str, float],
    *,
    before_name: str,
    after_name: str,
) -> str:
    """self-contained HTML 문서(인라인 CSS, 라이트/다크 대응) 반환."""
    keys = sorted(set(before) | set(after))
    rows = []
    for k in keys:
        b, a = before.get(k), after.get(k)
        delta = None if (b is None or a is None) else a - b
        color = ""
        if delta is not None and delta < 0:
            color = ' style="color:#d33"'   # 회귀
        elif delta is not None and delta > 0:
            color = ' style="color:#2a2"'   # 개선
        delta_txt = "n/a" if delta is None else f"{delta:+.2f}"
        rows.append(
            f"<tr><td>{_html.escape(k)}</td><td>{_fmt(b)}</td>"
            f"<td>{_fmt(a)}</td><td{color}>{delta_txt}</td></tr>"
        )
    body = "\n".join(rows)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Planner eval: before/after</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #8884; padding: .4rem .8rem; text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  @media (prefers-color-scheme: dark) {{ body {{ background:#111; color:#eee; }} }}
</style></head><body>
<h1>Planner 평가 비교</h1>
<p>{_html.escape(before_name)} → {_html.escape(after_name)}</p>
<table>
<thead><tr><th>evaluator</th><th>{_html.escape(before_name)}</th>
<th>{_html.escape(after_name)}</th><th>Δ</th></tr></thead>
<tbody>
{body}
</tbody></table>
</body></html>"""


def main() -> None:
    from langsmith import Client

    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("-o", "--out", default="compare.html")
    args = ap.parse_args()

    client = Client()
    html_doc = render_comparison_html(
        experiment_scores(client, args.before),
        experiment_scores(client, args.after),
        before_name=args.before,
        after_name=args.after,
    )
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html_doc)
    print(f"작성: {args.out}")


if __name__ == "__main__":
    main()
