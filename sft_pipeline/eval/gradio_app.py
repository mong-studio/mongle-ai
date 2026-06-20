"""FastAPI AI 서버 Gradio 테스트 UI.

탭별로 다음 엔드포인트를 테스트한다:
  - 플래너 채팅   POST /v1/todo/chat      (멀티턴)
  - TODO 생성     POST /v1/todo/generate  (1-shot)
  - TODO 커밋     POST /v1/todo/commit
  - 퀘스트 생성   POST /v1/quest/generate

[실행 방법] ──────────────────────────────────────────────────────────────────

1) 의존성 설치 (최초 1회)
       pip install gradio httpx

2) FastAPI 서버 시작 (터미널 A)
       uv run uvicorn api.main:app --reload --port 8010

3) Gradio UI 시작 (터미널 B)
       uv run python -m sft_pipeline.eval.gradio_app

4) 브라우저 → http://localhost:7860

[백그라운드 장시간 실행 (RunPod / 리모트 서버)]
  # tmux — 서버 재접속 후에도 프로세스 유지
  tmux new-session -d -s api 'uv run uvicorn api.main:app --port 8010'
  tmux new-session -d -s ui  'uv run python -m sft_pipeline.eval.gradio_app --host 0.0.0.0'
  # 재연결: tmux attach -t api   /   tmux attach -t ui
  # 종료:   tmux kill-session -t api   /   tmux kill-session -t ui

  # nohup — 로그 파일로 출력
  nohup uv run uvicorn api.main:app --port 8010 > api.log 2>&1 &
  nohup uv run python -m sft_pipeline.eval.gradio_app --host 0.0.0.0 > ui.log 2>&1 &
  # 종료: kill $(lsof -ti:8010)   /   kill $(lsof -ti:7860)

  # 외부 공유 링크 (Gradio 터널)
  uv run python -m sft_pipeline.eval.gradio_app --share

──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date

API_URL_DEFAULT = "http://localhost:8010"
USER_ID_DEFAULT = "test-user"


def _fmt_candidates(data: dict) -> str:
    todos = data.get("todos", [])
    calendar = data.get("calendar_events", [])
    summary = data.get("summary_text") or ""
    lines: list[str] = ["### ✅ 플랜 완성"]
    if summary:
        lines += [f"> {summary}", ""]

    if todos:
        lines += [f"**오늘 할 일** ({len(todos)}건)", "| 제목 | 마감 | 태그 |", "|------|------|------|"]
        for t in todos:
            tags = ", ".join(t.get("tags") or []) or "—"
            lines.append(f"| {t['title']} | {t['due_date']} | {tags} |")
        lines.append("")

    if calendar:
        lines += [f"**미래 일정** ({len(calendar)}건)", "| 제목 | 마감 | 태그 |", "|------|------|------|"]
        for t in calendar:
            tags = ", ".join(t.get("tags") or []) or "—"
            lines.append(f"| {t['title']} | {t['due_date']} | {tags} |")
    return "\n".join(lines)


def _fmt_follow_up(data: dict) -> str:
    question = data.get("question", "")
    aspects = data.get("missing_aspects") or []
    lines = ["### 💬 추가 정보 필요", "", question]
    if aspects:
        lines += ["", "**부족한 정보:**"] + [f"- {a}" for a in aspects]
    return "\n".join(lines)


def _fmt_out_of_scope(data: dict) -> str:
    return f"### 🚫 범위 밖\n\n{data.get('message', '')}"


def _format_response(data: dict) -> tuple[str, str]:
    """(chat_message, plan_markdown) 반환."""
    kind = data.get("kind", "")
    if kind == "candidates":
        n_todos = len(data.get("todos") or [])
        n_cal = len(data.get("calendar_events") or [])
        chat_msg = f"✅ 플랜 완성! 오늘 {n_todos}건 · 미래 {n_cal}건 → 오른쪽 패널 참고"
        plan_md = _fmt_candidates(data)
    elif kind == "follow_up":
        chat_msg = data.get("question", "추가 정보가 필요해요.")
        plan_md = _fmt_follow_up(data)
    elif kind == "out_of_scope":
        chat_msg = data.get("message", "범위를 벗어난 요청이에요.")
        plan_md = _fmt_out_of_scope(data)
    else:
        chat_msg = f"[{kind}] 알 수 없는 응답 유형"
        plan_md = f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
    return chat_msg, plan_md


def _append_chat_pair(
    history: list[dict[str, str]] | None, user_message: str, assistant_message: str
) -> list[dict[str, str]]:
    """Gradio Chatbot(type="messages") 이 요구하는 role/content 형식으로 누적한다."""
    return [
        *(history or []),
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_message},
    ]


def _call_api(
    api_url: str, path: str, payload: dict, api_key: str, timeout: int = 300
) -> tuple[str, dict]:
    """엔드포인트를 호출하고 (상태 마크다운, 응답 본문) 을 반환한다.

    연결/파싱 오류를 모두 사용자 표면에 노출한다.
    timeout 기본 300초 — RunPod Serverless 콜드스타트(vLLM 로딩 ~90초+)를
    클라이언트가 중간에 포기해 잡이 유실/중복 쌓이는 것을 방지한다.
    """
    import httpx

    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        resp = httpx.post(
            f"{api_url.rstrip('/')}{path}",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
    except Exception as error:  # noqa: BLE001 — 테스트 UI: 모든 연결 오류 표면화
        return f"❌ 연결 실패: {error}", {}

    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text}

    mark = "❌ " if resp.status_code >= 400 else "✅ "
    status = f"{mark}HTTP {resp.status_code} · {resp.elapsed.total_seconds():.2f}s"
    return status, body


def build_app(api_url_default: str = API_URL_DEFAULT):
    try:
        import gradio as gr
        import httpx
    except ImportError:
        raise SystemExit("[오류] gradio/httpx 없음.\n  pip install gradio httpx")

    def send(message, history, thread_id, api_url, api_key, user_id, today_str):
        if not message.strip():
            return history or [], thread_id, "", {}

        payload = {
            "mode": "multi",
            "user_id": user_id or USER_ID_DEFAULT,
            "message": message.strip(),
            "today": today_str,
            "thread_id": thread_id or None,
        }
        headers = {"X-API-Key": api_key} if api_key else {}

        try:
            resp = httpx.post(
                f"{api_url.rstrip('/')}/v1/todo/chat",
                json=payload,
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("result", body.get("data", body))
        except httpx.HTTPStatusError as e:
            err = f"❌ API 오류 {e.response.status_code}: {e.response.text[:200]}"
            return _append_chat_pair(history, message, err), thread_id, err, {}
        except Exception as e:
            err = f"❌ 연결 실패: {e}"
            return _append_chat_pair(history, message, err), thread_id, err, {}

        new_thread_id = data.get("thread_id", thread_id)
        chat_msg, plan_md = _format_response(data)
        return _append_chat_pair(history, message, chat_msg), new_thread_id, plan_md, data

    def reset_thread():
        return [], None, "*대화를 시작하면 여기에 플랜이 표시됩니다.*", {}, ""

    def run_generate(prompt, api_url, api_key, user_id, today_str):
        if not (prompt or "").strip():
            return "프롬프트를 입력하세요.", {}
        payload = {
            "user_id": user_id or USER_ID_DEFAULT,
            "prompt": prompt.strip(),
            "today": today_str,
        }
        return _call_api(api_url, "/v1/todo/generate", payload, api_key)

    def run_json_endpoint(path, payload_text, api_url, api_key):
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as error:
            return f"❌ JSON 파싱 실패: {error}", {}
        return _call_api(api_url, path, payload, api_key)

    example_commit = json.dumps(
        {
            "input": {
                "user_id": USER_ID_DEFAULT,
                "idempotency_key": str(uuid.uuid4()),
                "today": date.today().isoformat(),
                "todos": [
                    {
                        "title": "물 마시기",
                        "due_date": date.today().isoformat(),
                        "tags": ["건강"],
                    }
                ],
                "calendar_events": [],
            },
            "remaining_daily_quota": 5,
        },
        ensure_ascii=False,
        indent=2,
    )
    example_quest = json.dumps(
        {
            "todos": [{"todo_id": str(uuid.uuid4())}],
            "characters": [
                {
                    "character_id": str(uuid.uuid4()),
                    "name": "몽글",
                    "persona": "호기심 많고 다정한 마을 친구",
                    "speech_style": "친근한 반말",
                    "appearance_keywords": [],
                }
            ],
            "remaining_daily_quota": 5,
            "shuffle_seed": 42,
        },
        ensure_ascii=False,
        indent=2,
    )

    with gr.Blocks(title="몽글 AI 서버 테스트") as app:
        gr.Markdown("## 몽글 AI 서버 — FastAPI 엔드포인트 테스트")

        with gr.Accordion("⚙️ 설정 (모든 탭 공유)", open=False):
            with gr.Row():
                api_url_box = gr.Textbox(value=api_url_default, label="API URL", scale=2)
                api_key_box = gr.Textbox(value="", label="X-API-Key", type="password", scale=2)
                user_id_box = gr.Textbox(value=USER_ID_DEFAULT, label="user_id", scale=1)
                today_box   = gr.Textbox(value=date.today().isoformat(), label="today (YYYY-MM-DD)", scale=1)

        thread_state = gr.State(None)

        with gr.Tabs():
            with gr.Tab("플래너 채팅 · /v1/todo/chat"):
                with gr.Row():
                    with gr.Column(scale=3):
                        chatbot = gr.Chatbot(label="대화", height=480)
                        with gr.Row():
                            msg_box  = gr.Textbox(placeholder="오늘 할 일을 알려줘...", label="", scale=5)
                            send_btn = gr.Button("보내기", variant="primary", scale=1)
                            reset_btn = gr.Button("새 대화 🔄", scale=1)

                    with gr.Column(scale=2):
                        thread_label = gr.Textbox(label="thread_id", interactive=False, value="")
                        plan_view = gr.Markdown(value="*대화를 시작하면 여기에 플랜이 표시됩니다.*")
                        with gr.Accordion("Raw JSON", open=False):
                            raw_json = gr.JSON(label="응답 데이터")

                _inputs  = [msg_box, chatbot, thread_state, api_url_box, api_key_box, user_id_box, today_box]
                _outputs = [chatbot, thread_state, plan_view, raw_json]

                def _after_send(t):
                    return t or ""

                send_btn.click(send, _inputs, _outputs).then(lambda: "", outputs=msg_box).then(
                    _after_send, inputs=thread_state, outputs=thread_label
                )
                msg_box.submit(send, _inputs, _outputs).then(lambda: "", outputs=msg_box).then(
                    _after_send, inputs=thread_state, outputs=thread_label
                )
                reset_btn.click(reset_thread, outputs=[chatbot, thread_state, plan_view, raw_json, thread_label])

            with gr.Tab("TODO 생성 · /v1/todo/generate"):
                gen_prompt = gr.Textbox(
                    label="prompt",
                    placeholder="예: 내일까지 보고서 쓰고 저녁에 운동하기",
                    lines=2,
                )
                gen_btn = gr.Button("생성 요청", variant="primary")
                gen_status = gr.Markdown()
                gen_json = gr.JSON(label="응답")
                gen_btn.click(
                    run_generate,
                    [gen_prompt, api_url_box, api_key_box, user_id_box, today_box],
                    [gen_status, gen_json],
                )

            with gr.Tab("TODO 커밋 · /v1/todo/commit"):
                commit_body = gr.Code(
                    value=example_commit, language="json", label="요청 본문 (CommitRequest)"
                )
                commit_btn = gr.Button("커밋 요청", variant="primary")
                commit_status = gr.Markdown()
                commit_json = gr.JSON(label="응답")
                commit_btn.click(
                    lambda body, url, key: run_json_endpoint("/v1/todo/commit", body, url, key),
                    [commit_body, api_url_box, api_key_box],
                    [commit_status, commit_json],
                )

            with gr.Tab("퀘스트 생성 · /v1/quest/generate"):
                quest_body = gr.Code(
                    value=example_quest,
                    language="json",
                    label="요청 본문 (QuestGenerationRequest)",
                )
                quest_btn = gr.Button("생성 요청", variant="primary")
                quest_status = gr.Markdown()
                quest_json = gr.JSON(label="응답")
                quest_btn.click(
                    lambda body, url, key: run_json_endpoint("/v1/quest/generate", body, url, key),
                    [quest_body, api_url_box, api_key_box],
                    [quest_status, quest_json],
                )

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="FastAPI 파이프라인 Gradio 테스트 UI")
    parser.add_argument("--api-url", default=API_URL_DEFAULT)
    parser.add_argument("--host",    default="127.0.0.1")
    parser.add_argument("--port",    type=int, default=7860)
    parser.add_argument("--share",   action="store_true", help="Gradio 공유 링크 생성")
    args = parser.parse_args()

    app = build_app(api_url_default=args.api_url)
    app.launch(server_name=args.host, server_port=args.port, share=args.share)


if __name__ == "__main__":
    main()
