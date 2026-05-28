from __future__ import annotations

import asyncio
import base64
import json
import random
import sys
import traceback
import warnings
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from langchain_core._api.deprecation import (  # noqa: E402
    LangChainPendingDeprecationWarning,
)

warnings.filterwarnings(
    "ignore",
    message="The default value of `allowed_objects` will change",
    category=LangChainPendingDeprecationWarning,
)

# Streamlit는 프로젝트 루트가 sys.path에 없는 상태로 실행되므로 임포트 전에 주입한다.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env")

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from adapters.character_creation.memory_repo import InMemoryRepo  # noqa: E402
from agents.character_creation.exceptions import (  # noqa: E402
    ImageGenerationFailedError,
    LLMFailedError,
    S3UploadFailedError,
    ValidationFailedError,
    VLMFailedError,
)
from agents.character_creation.pipeline import run as pipeline_run  # noqa: E402
from agents.character_creation.schemas import (  # noqa: E402
    CharacterCreationInput,
    CharacterEntity,
    PersonalityKeyword,
    SourceImage,
)
from adapters.quest_generation.fake_llm import FakeLLM as FakeQuestLLM  # noqa: E402
from adapters.quest_generation.openai_llm import OpenAILLM as QuestOpenAILLM  # noqa: E402
from adapters.quest_generation.openai_llm import QuestTextResponse  # noqa: E402
from agents.quest_generation.schemas import Character as QuestCharacter  # noqa: E402
from streamlit_app.ports_factory import (  # noqa: E402
    AppConfig,
    MissingEnvError,
    build_ports,
    build_todo_generate_ports,
)

st.set_page_config(
    page_title="몽글마을",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ────────────────────────────────────────────────────────────────────────────
# Styling — pixel-art village aesthetic
# ────────────────────────────────────────────────────────────────────────────
_STYLES_DIR = Path(__file__).parent / "styles"
_CSS_FILES = [
    "base.css",
    "layout.css",
    "village.css",
    "chief.css",
    "todo.css",
    "quest.css",
    "feed.css",
    "calendar.css",
    "widgets.css",
    "sidebar.css",
    "feed.css",
]


def _inject_css() -> None:
    css = "\n".join(
        (_STYLES_DIR / f).read_text(encoding="utf-8") for f in _CSS_FILES
    )
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────────────────────
# Chrome panels
# ────────────────────────────────────────────────────────────────────────────
def _topbar() -> None:
    tokens = st.session_state.get("tokens", 5)
    st.markdown(
        f"""
        <div class="pixel-topbar">
          <div class="menu">
            <span>TOWN INFO</span>
            <span>RESIDENTS</span>
            <span>SETTINGS</span>
          </div>
          <div class="brand">몽글마을</div>
          <div class="session">🍎 {tokens} &nbsp; GUEST</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _timer_panel() -> None:
    # ── 1. 정적 HTML 오버레이 (main DOM → position:fixed 정상 작동) ──────────
    st.markdown(
        """
        <div class="timer-overlay">
          <div class="side-panel">
            <div class="timer-sun" id="mg-timer-sun">☀</div>
            <div class="label" id="mg-timer-label">&lt; FOCUS TIME &gt;</div>
            <div class="timer-display" id="mg-timer-display">25:00</div>
            <div class="timer-meta"   id="mg-timer-meta">0 CYCLES</div>
            <div class="pixel-row">
              <div class="pixel-btn dark" id="mg-timer-start">▶ START</div>
              <div class="pixel-btn"      id="mg-timer-reset">RESET</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── 2. JS 타이머 엔진 (iframe height=0, localStorage로 상태 유지) ─────────
    components.html(
        """
        <script>
        (function () {
          var LS_KEY = 'mg_timer_v2';
          var WORK   = 25 * 60;   // 25분
          var BREAK  =  5 * 60;   //  5분

          function fmt(s) {
            return String(Math.floor(s / 60)).padStart(2,'0') + ':' +
                   String(s % 60).padStart(2,'0');
          }
          function load() {
            try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; }
            catch { return {}; }
          }
          function save(st) { localStorage.setItem(LS_KEY, JSON.stringify(st)); }

          /* ── 초기 상태 ── */
          var state = {
            running: false, endAt: null,
            remaining: WORK, cycles: 0,
            isBreak: false
          };
          var ticker = null;

          function getRem() {
            if (state.running && state.endAt)
              return Math.max(0, Math.ceil((state.endAt - Date.now()) / 1000));
            return state.remaining;
          }

          /* ── UI 갱신 ── */
          function updateUI() {
            var doc = window.parent.document;
            var lbl = doc.getElementById('mg-timer-label');
            var dsp = doc.getElementById('mg-timer-display');
            var met = doc.getElementById('mg-timer-meta');
            var btn = doc.getElementById('mg-timer-start');
            var sun = doc.getElementById('mg-timer-sun');
            if (lbl) lbl.textContent = state.isBreak ? '< BREAK TIME >' : '< FOCUS TIME >';
            if (dsp) dsp.textContent = fmt(getRem());
            if (met) met.textContent = state.cycles + ' CYCLES';
            if (btn) btn.textContent = state.running ? '⏸ PAUSE' : '▶ START';
            /* 햇님/달님 아이콘 + 색상 */
            if (sun) sun.textContent = state.isBreak ? '🌙' : '☀';
            if (dsp) dsp.style.color = state.isBreak ? '#7ecfd4' : '';
          }

          /* ── 집중 완료 → 휴식 자동 시작 ── */
          function onWorkComplete() {
            clearInterval(ticker); ticker = null;
            state.cycles   += 1;
            state.isBreak   = true;
            state.remaining = BREAK;
            state.endAt     = Date.now() + BREAK * 1000;
            state.running   = true;
            save(state);
            ticker = setInterval(tick, 1000);
            updateUI();
          }

          /* ── 휴식 완료 → 집중 모드 리셋 ── */
          function onBreakComplete() {
            clearInterval(ticker); ticker = null;
            state.running   = false;
            state.isBreak   = false;
            state.remaining = WORK;
            state.endAt     = null;
            save(state);
            updateUI();
          }

          function tick() {
            updateUI();
            if (getRem() <= 0) {
              if (state.isBreak) { onBreakComplete(); }
              else               { onWorkComplete();  }
            }
          }

          /* ── 시작 / 일시정지 / 리셋 ── */
          function doStart() {
            if (state.running) return;
            state.endAt   = Date.now() + getRem() * 1000;
            state.running = true;
            save(state);
            ticker = setInterval(tick, 1000);
            updateUI();
          }
          function doPause() {
            if (!state.running) return;
            state.remaining = getRem();
            state.running   = false;
            state.endAt     = null;
            clearInterval(ticker); ticker = null;
            save(state);
            updateUI();
          }
          function doReset() {
            clearInterval(ticker); ticker = null;
            state.running   = false;
            state.isBreak   = false;
            state.endAt     = null;
            state.remaining = WORK;
            save(state);
            updateUI();
          }

          /* ── 버튼 연결 ── */
          function bindButtons() {
            var doc   = window.parent.document;
            var start = doc.getElementById('mg-timer-start');
            var reset = doc.getElementById('mg-timer-reset');
            if (!start || !reset) { setTimeout(bindButtons, 100); return; }

            var ns = start.cloneNode(true);
            var nr = reset.cloneNode(true);
            start.parentNode.replaceChild(ns, start);
            reset.parentNode.replaceChild(nr, reset);
            ns.style.cursor = 'pointer';
            nr.style.cursor = 'pointer';

            ns.addEventListener('click', function () {
              if (state.running) { doPause(); } else { doStart(); }
            });
            nr.addEventListener('click', doReset);
          }

          /* ── 초기화 (localStorage 복원) ── */
          function init() {
            var s = load();
            if (s && s.cycles !== undefined) {
              state.running   = !!s.running;
              state.endAt     = s.endAt   || null;
              state.remaining = s.remaining !== undefined ? s.remaining : WORK;
              state.cycles    = s.cycles   || 0;
              state.isBreak   = !!s.isBreak;
            }
            if (state.running && state.endAt) {
              if (Date.now() >= state.endAt) {
                if (state.isBreak) { onBreakComplete(); }
                else               { onWorkComplete();  }
              } else {
                ticker = setInterval(tick, 1000);
              }
            }
            updateUI();
            bindButtons();
          }

          function waitDOM() {
            if (window.parent.document.getElementById('mg-timer-display')) {
              init();
            } else {
              setTimeout(waitDOM, 50);
            }
          }
          waitDOM();
        })();
        </script>
        """,
        height=0,
    )


def _date_panel(today: date, todo_entries: list[tuple[str, bool]] | None = None) -> None:
    day_short = today.strftime("%a").upper()
    date_str = today.strftime("%Y.%m.%d")

    if todo_entries:
        done_count = sum(1 for _, done in todo_entries if done)
        total = len(todo_entries)
        hint_html = (
            f'<div class="date-hint">'
            f'<span class="key">{done_count} / {total} DONE</span>'
            f'</div>'
        )
    else:
        hint_html = (
            '<div class="date-hint">'
            "오늘의 할 일을 추가해보세요<br/>"
            '<span class="key">PRESS &lt;+&gt; TO ADD</span>'
            "</div>"
        )

    st.markdown(
        f"""
        <div class="date-overlay">
          <div class="side-panel">
            <div class="date-display">{date_str}</div>
            <div class="date-day">{day_short}</div>
            {hint_html}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )




def _icon_button_js(marker_class: str, right_px: int, run_id_key: str) -> None:
    """마커 클래스 기반으로 아이콘 버튼 컨테이너를 position:fixed 로 배치하는 JS.
    run ID 패턴으로 구 iframe 자동 종료 — todo 패널과 동일한 방식."""
    components.html(
        f"""
        <script>
        (function() {{
          var myId = (window.parent.{run_id_key} || 0) + 1;
          window.parent.{run_id_key} = myId;
          var iv;
          function applyIcon() {{
            if (window.parent.{run_id_key} !== myId) {{ clearInterval(iv); return; }}
            try {{
              var doc = window.parent.document;
              var marker = doc.querySelector('{marker_class}');
              if (!marker) return;
              var el = marker;
              while (el) {{
                if (el.getAttribute && el.getAttribute('data-testid') === 'stVerticalBlock') break;
                el = el.parentElement;
              }}
              if (!el) return;
              el.style.setProperty('position',   'fixed',   'important');
              el.style.setProperty('top',        '74px',    'important');
              el.style.setProperty('right',      '{right_px}px', 'important');
              el.style.setProperty('z-index',    '100',     'important');
              el.style.setProperty('width',      'auto',    'important');
              el.style.setProperty('background', '#1a1a1a', 'important');
              el.style.setProperty('border',     '4px solid #3d2818', 'important');
              el.style.setProperty('outline',    '2px solid #000',    'important');
              el.style.setProperty('padding',    '8px 10px','important');
              el.style.setProperty('box-shadow', 'inset 0 0 0 2px #5a3a1f, 6px 6px 0 rgba(0,0,0,0.55)', 'important');
              var btn = el.querySelector('button');
              if (btn) {{
                btn.style.setProperty('background',  'transparent', 'important');
                btn.style.setProperty('border',      'none',        'important');
                btn.style.setProperty('box-shadow',  'none',        'important');
                btn.style.setProperty('padding',     '0',           'important');
                btn.style.setProperty('font-size',   '22px',        'important');
                btn.style.setProperty('min-height',  'auto',        'important');
                btn.style.setProperty('line-height', '1',           'important');
                btn.style.setProperty('cursor',      'pointer',     'important');
                btn.style.setProperty('color',       '#f4ead6',     'important');
                btn.style.setProperty('width',       '28px',        'important');
                btn.style.setProperty('height',      '28px',        'important');
              }}
            }} catch(e) {{}}
          }}
          applyIcon();
          iv = setInterval(applyIcon, 300);
        }})();
        </script>
        """,
        height=0,
    )


def _diary_icon_panel() -> None:
    """회고 아이콘 버튼 — 날짜 패널 바로 왼쪽에 고정."""
    with st.container():
        st.markdown('<span class="mg-diary-marker" style="display:none"></span>', unsafe_allow_html=True)
        if st.button("📓", key="open_reflection_diary"):
            st.session_state["modal"] = "reflection"
            st.rerun()
    _icon_button_js('.mg-diary-marker', 234, '__mg_diary_run_id')


def _feed_icon_panel() -> None:
    """피드 아이콘 버튼 — 회고 버튼 바로 왼쪽에 고정."""
    with st.container():
        st.markdown('<span class="mg-feed-marker" style="display:none"></span>', unsafe_allow_html=True)
        if st.button("📱", key="open_feed"):
            st.session_state["modal"] = "feed"
            st.rerun()
    _icon_button_js('.mg-feed-marker', 298, '__mg_feed_run_id')


@lru_cache(maxsize=1)
def _background_data_uri() -> str:
    img_path = _PROJECT_ROOT / "assets" / "background.jpeg"
    data = base64.b64encode(img_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


@lru_cache(maxsize=32)
def _img_to_data_uri(path: str) -> str:
    """로컬 파일 경로 → base64 data URI 변환 (HTML <img src> 에 사용)."""
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://") or path.startswith("data:"):
        return path
    p = Path(path)
    if not p.exists():
        return ""
    ext = p.suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext or 'png'}"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _village_map() -> None:
    st.markdown(
        f"""
        <div class="map-wrap"
             style="background-image: url('{_background_data_uri()}');
                    background-size: cover;
                    background-position: center;
                    background-repeat: no-repeat;">
        </div>
        """,
        unsafe_allow_html=True,
    )


def _chief_house_cta() -> None:
    """Toggle the chief dialog. Stands in for clicking the chief house tile."""
    is_open = st.session_state.get("chief_open", False)
    if is_open:
        st.markdown(
            '<div class="chief-cta-hint">'
            '<span class="arrow">▼</span> 이장님이 기다리고 있어요 '
            '<span class="arrow">▼</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        label = "✕  대화 닫기"
    else:
        st.markdown(
            '<div class="chief-cta-hint">'
            "마을 가운데 이장님 집을 두드려 보세요"
            "</div>",
            unsafe_allow_html=True,
        )
        label = "🏠  이장님 집 두드리기"

    _, chief_col, cal_col, _ = st.columns([2, 3, 1, 2])
    with chief_col:
        if st.button(label, key="knock_chief", type="primary", width="stretch"):
            st.session_state["chief_open"] = not is_open
            st.session_state["modal"] = None
            st.rerun()
    with cal_col:
        if st.button("📅", key="open_calendar", width="stretch"):
            st.session_state["modal"] = "calendar"
            st.session_state["chief_open"] = False
            st.rerun()


def _chief_dialog() -> None:
    if not st.session_state.get("chief_open", False):
        return
    st.markdown(
        """
        <div class="chief-dialog">
          <div class="chief-row">
            <div>
              <div class="chief-avatar">🧙</div>
              <div class="chief-name">CHIEF</div>
            </div>
            <div>
              <div class="chief-speech">안녕! 오늘은 뭘 도와줄까?</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(3)
    if cols[0].button("📝  오늘의 TODO 만들기", key="open_todo", width="stretch"):
        st.session_state["modal"] = "todo"
        st.rerun()
    if cols[1].button("📅  장기 플랜 짜기", key="open_plan", width="stretch"):
        st.session_state["modal"] = "plan"
        st.rerun()
    if cols[2].button("👋  새 주민 맞이하기", key="open_character", width="stretch"):
        st.session_state["modal"] = "character"
        st.rerun()


# ────────────────────────────────────────────────────────────────────────────
# Modals
# ────────────────────────────────────────────────────────────────────────────
@st.dialog("< NEW RESIDENT >  새 주민 맞이하기", width="large")
def _character_modal(user_id: str, is_regen: bool, repo: InMemoryRepo, cfg: AppConfig) -> None:
    st.markdown(
        '<div class="modal-sub">몽글마을로 새 친구를 초대해요</div>',
        unsafe_allow_html=True,
    )

    img_bytes: bytes | None = st.session_state.get("char_image_bytes")
    img_name:  str   | None = st.session_state.get("char_image_name")

    if img_bytes is not None:
        # 이미지가 있으면 미리보기 + 제거 버튼만 표시 (업로더 숨김)
        prev_col, rm_col = st.columns([1, 3])
        with prev_col:
            st.markdown('<div class="preview-frame">', unsafe_allow_html=True)
            st.image(img_bytes, width="stretch")
            st.markdown(
                f'<div class="preview-caption">{img_name}</div></div>',
                unsafe_allow_html=True,
            )
        with rm_col:
            if st.button("🗑 이미지 제거", key="char_image_remove"):
                st.session_state.pop("char_image_bytes", None)
                st.session_state.pop("char_image_name", None)
                st.rerun()
    else:
        uploaded = st.file_uploader(
            "참고 이미지 (선택, png/jpeg, 5MB 이내)",
            type=["png", "jpg", "jpeg"],
            key="char_image",
        )
        if uploaded is not None:
            st.session_state["char_image_bytes"] = uploaded.read()
            st.session_state["char_image_name"]  = uploaded.name
            st.rerun()
    name = st.text_input("이름 *", max_chars=50, placeholder="예) 다온, 몽글이", key="char_name")
    keyword_labels = [k.value for k in PersonalityKeyword]
    if "char_keyword_list" not in st.session_state:
        st.session_state["char_keyword_list"] = []
    chosen: list[str] = st.session_state["char_keyword_list"]

    st.markdown(
        f'<div class="kw-label">성격 키워드 <span class="kw-count">(선택사항 · 최대 3개)</span></div>',
        unsafe_allow_html=True,
    )
    kw_cols = st.columns(4)
    for i, label in enumerate(keyword_labels):
        is_selected = label in chosen
        with kw_cols[i % 4]:
            if st.button(
                f"✓ {label}" if is_selected else label,
                key=f"kw_{label}",
                type="primary" if is_selected else "secondary",
                width="stretch",
            ):
                if is_selected:
                    chosen.remove(label)
                elif len(chosen) < 3:
                    chosen.append(label)
                st.session_state["char_keyword_list"] = chosen
                st.rerun()
    persona = st.text_area(
        "캐릭터 설명 *",
        height=130,
        placeholder="어떤 친구인가요?",
        max_chars=200,
        key="char_persona",
    )

    cancel_col, ok_col = st.columns([1, 1])
    if cancel_col.button("취소", key="char_cancel", width="stretch"):
        st.session_state.pop("char_keyword_list", None)
        st.session_state.pop("char_image_bytes", None)
        st.session_state.pop("char_image_name", None)
        st.session_state["modal"] = None
        st.rerun()
    if ok_col.button("생성하기 →", key="char_submit", type="primary", width="stretch"):
        missing = []
        if not name.strip():
            missing.append("이름")
        if not persona.strip():
            missing.append("캐릭터 설명")
        if missing:
            st.info(f"{'과 '.join(missing)}을 입력해주세요 ✏️")
            return

        try:
            source_image: SourceImage | None = None
            if img_bytes is not None:
                source_image = SourceImage(
                    filename=img_name or "image.png",
                    content_type="image/png",
                    data=img_bytes,
                )
            user_input = CharacterCreationInput(
                user_id=user_id,
                name=name,
                persona=persona,
                personality_keywords=[PersonalityKeyword(v) for v in chosen],
                source_image=source_image,
            )
        except Exception as err:  # noqa: BLE001
            st.warning(f"입력 검증 실패: {err}")
            return

        ports = build_ports(repo, cfg)
        with st.spinner("새 친구를 그리는 중..."):
            try:
                entity = asyncio.run(
                    pipeline_run(user_input, ports=ports)
                )
            except Exception as err:  # noqa: BLE001
                _handle_pipeline_error(err)
                return
        asyncio.run(repo.save(entity))
        _save_demo_chars(repo)   # 파일에 즉시 저장
        st.session_state["last_created"] = entity
        st.session_state.pop("char_keyword_list", None)
        st.session_state.pop("char_image_bytes", None)
        st.session_state.pop("char_image_name", None)
        st.session_state["modal"] = None
        st.rerun()


# ── TODO 프리셋 태그 ──────────────────────────────────────────────────────────
_PRESET_TAGS: list[str] = ["건강", "학습", "업무/프로젝트", "일상", "취미"]

_MOCK_FEEDS = [
    {
        "avatar": "🐱",
        "name": "다온",
        "bg": "#FFDAB9",
        "accent": "#F4A460",
        "emoji": "📚",
        "caption": "오늘도 열심히 공부했어요~ 수학 문제집 3장 완성! 뿌듯하다냥~ ✏️",
        "likes": 42,
        "comments": 7,
        "time": "2시간 전",
    },
    {
        "avatar": "🐶",
        "name": "몽글이",
        "bg": "#B0E0FF",
        "accent": "#6CB4E4",
        "emoji": "🏃",
        "caption": "산책 다녀왔어요! 오늘은 공원 두 바퀴! 몸이 가벼워지는 기분이야 🌸",
        "likes": 28,
        "comments": 3,
        "time": "4시간 전",
    },
    {
        "avatar": "🦊",
        "name": "솔이",
        "bg": "#C8F5C8",
        "accent": "#6DC96D",
        "emoji": "🍳",
        "caption": "요리 퀘스트 완료! 오늘 저녁은 내가 만든 계란볶음밥 🍳 맛있게 드세요!",
        "likes": 65,
        "comments": 12,
        "time": "6시간 전",
    },
]


def _feed_image_uri(bg: str, accent: str, emoji: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="340" height="340">'
        f'<rect width="340" height="340" fill="{bg}"/>'
        f'<circle cx="170" cy="160" r="100" fill="{accent}" opacity="0.35"/>'
        f'<text x="170" y="185" font-size="110" text-anchor="middle"'
        f' dominant-baseline="middle">{emoji}</text>'
        f"</svg>"
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


@st.dialog("< FEED >  마을 피드", width="large")
def _feed_modal() -> None:
    stories = "".join(
        f'<div class="insta-story-item">'
        f'<div class="insta-story-ring">'
        f'<div class="insta-story-avatar">{f["avatar"]}</div>'
        f"</div>"
        f'<div class="insta-story-name">{f["name"]}</div>'
        f"</div>"
        for f in _MOCK_FEEDS
    )

    posts = "".join(
        f'<div class="insta-post">'
        f'<div class="insta-post-header">'
        f'<div class="insta-post-user">'
        f'<div class="insta-post-ring"><div class="insta-post-avatar">{f["avatar"]}</div></div>'
        f"<div>"
        f'<div class="insta-post-username">{f["name"]}</div>'
        f'<div class="insta-post-location">몽글마을</div>'
        f"</div></div>"
        f'<div class="insta-post-more">···</div>'
        f"</div>"
        f'<div class="insta-post-image-wrap">'
        f'<img class="insta-post-image" src="{_feed_image_uri(f["bg"], f["accent"], f["emoji"])}" alt=""/>'
        f"</div>"
        f'<div class="insta-post-actions">'
        f'<span class="insta-action">🤍</span>'
        f'<span class="insta-action">💬</span>'
        f'<span class="insta-action">↗</span>'
        f'<span class="insta-action save">🔖</span>'
        f"</div>"
        f'<div class="insta-likes">좋아요 {f["likes"]}개</div>'
        f'<div class="insta-caption"><span class="uname">{f["name"]}</span> {f["caption"]}</div>'
        f'<div class="insta-comments">댓글 {f["comments"]}개 보기</div>'
        f'<div class="insta-time">{f["time"]}</div>'
        f"</div>"
        for f in _MOCK_FEEDS
    )

    st.markdown(
        f"""
        <div class="pixel-phone-wrap">
          <div class="pixel-phone">
            <div class="pixel-phone-status">
              <span>09:41</span>
              <div class="pixel-phone-notch"></div>
              <span>&#x1F4F6; &#x1F50B;</span>
            </div>
            <div class="pixel-phone-screen">
              <div class="insta-app">
                <div class="insta-nav">
                  <div class="insta-nav-logo">몽글마을</div>
                  <div class="insta-nav-icons"><span>&#x2764;&#xFE0F;</span><span>&#x2709;&#xFE0F;</span></div>
                </div>
                <div class="insta-stories">{stories}</div>
                {posts}
              </div>
            </div>
            <div class="pixel-phone-home"></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, close_col, _ = st.columns([2, 1, 2])
    if close_col.button("닫기", key="feed_close", width="stretch"):
        st.session_state["modal"] = None
        st.rerun()


@st.dialog("< TODO LIST >  오늘 뭐 할거야?", width="large")
def _todo_modal(characters: list) -> None:
    todo_step = st.session_state.get("todo_step", 1)

    # ══════════════════════════════════════════════════════
    # STEP 1/2 — 입력 화면
    # ══════════════════════════════════════════════════════
    if todo_step == 1:
        st.markdown(
            '<div class="step-tag"><span class="step">STEP 1/2</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="todo-modal-title">오늘 뭐 할거이?</div>'
            '<div class="modal-sub">이장님이 정리해주면 내가 알려줄게요</div>',
            unsafe_allow_html=True,
        )

        text = st.text_area(
            "할 일",
            value=st.session_state.get("todo_text", ""),
            height=120,
            max_chars=200,
            placeholder="예) 수학문제 1단계 끝내고, 청소도 하고, 강아지 산책 두 번 시켜야 함.",
            key="todo_text_input",
            label_visibility="collapsed",
        )
        st.caption(f"{len(text)} / 200")

        # ── 직접 추가 ─────────────────────────────────────
        st.markdown("---")
        st.markdown('<div class="todo-section-label">✏️ 바로 추가하기</div>', unsafe_allow_html=True)
        direct_items: list[dict] = st.session_state.get("todo_direct", [])
        input_ver = st.session_state.get("todo_direct_input_ver", 0)
        direct_tags: list[str] = st.session_state.get("todo_direct_tags", [])
        direct_custom_tags: list[str] = st.session_state.get("todo_direct_custom_tags", [])
        custom_input_open: bool = st.session_state.get("todo_custom_input_open", False)

        # 1) 할 일 입력 (단독 한 줄)
        new_item = st.text_input(
            "직접 추가",
            placeholder="예) 세탁기 돌리기 (최대 20자)",
            max_chars=20,
            key=f"todo_direct_input_{input_ver}",
            label_visibility="collapsed",
        )

        # 2) 키워드 선택 레이블 + 선택된 태그 pills
        tag_label_parts = "".join(
            f'<span class="todo-tag-pill" style="opacity:0.9">{t}</span>'
            for t in direct_tags
        )
        st.markdown(
            f'<div class="direct-tag-label">'
            f'# 키워드 선택 <span style="font-size:11px;opacity:0.6">(선택사항)</span>'
            f'{"&nbsp;" + tag_label_parts if direct_tags else ""}'
            f'</div>',
            unsafe_allow_html=True,
        )

        # 3) 프리셋 태그 버튼 (토글)
        dt_cols = st.columns(len(_PRESET_TAGS))
        for _ti, _tag in enumerate(_PRESET_TAGS):
            _sel = _tag in direct_tags
            with dt_cols[_ti]:
                if st.button(
                    f"{_tag}  ✕" if _sel else _tag,
                    key=f"dtag_{_tag}",
                    type="primary" if _sel else "secondary",
                    use_container_width=True,
                ):
                    if _sel:
                        direct_tags.remove(_tag)
                    else:
                        direct_tags.append(_tag)
                    st.session_state["todo_direct_tags"] = direct_tags
                    st.rerun()

        # 4) 커스텀 태그 pill (프리셋과 동일한 5컬럼 기준, 누르면 삭제)
        removed_tag: str | None = None
        if direct_custom_tags:
            # 5개씩 한 줄에 (프리셋과 동일한 너비)
            for _row_start in range(0, len(direct_custom_tags), len(_PRESET_TAGS)):
                _row = direct_custom_tags[_row_start: _row_start + len(_PRESET_TAGS)]
                _padded = _row + [None] * (len(_PRESET_TAGS) - len(_row))
                _cust_cols = st.columns(len(_PRESET_TAGS))
                for _ci, _ctag in enumerate(_padded):
                    if _ctag is not None:
                        with _cust_cols[_ci]:
                            if st.button(
                                f"{_ctag}  ✕",
                                key=f"custom_pill_{_row_start + _ci}",
                                type="primary",
                                use_container_width=True,
                            ):
                                removed_tag = _ctag
        if removed_tag:
            direct_custom_tags = [t for t in direct_custom_tags if t != removed_tag]
            direct_tags = [t for t in direct_tags if t != removed_tag]
            st.session_state["todo_direct_custom_tags"] = direct_custom_tags
            st.session_state["todo_direct_tags"] = direct_tags
            st.rerun()

        # 5) 커스텀 태그 입력 or "+ 직접 추가" 버튼
        if custom_input_open:
            custom_tag_ver = st.session_state.get("todo_custom_tag_ver", 0)
            ci_col, ci_ok_col, ci_cancel_col = st.columns([5, 1, 1])
            with ci_col:
                custom_val = st.text_input(
                    "새 키워드",
                    placeholder="새 키워드 입력 (최대 10자)",
                    key=f"todo_custom_tag_{custom_tag_ver}",
                    max_chars=10,
                    label_visibility="collapsed",
                )
            with ci_ok_col:
                if st.button("확인", key="custom_tag_ok", use_container_width=True):
                    stripped = custom_val.strip()
                    if stripped and stripped not in direct_tags:
                        direct_tags.append(stripped)
                        direct_custom_tags.append(stripped)
                        st.session_state["todo_direct_tags"] = direct_tags
                        st.session_state["todo_direct_custom_tags"] = direct_custom_tags
                        st.session_state["todo_custom_tag_ver"] = custom_tag_ver + 1
                    st.session_state["todo_custom_input_open"] = False
                    st.rerun()
            with ci_cancel_col:
                if st.button("취소", key="custom_tag_cancel", use_container_width=True):
                    st.session_state["todo_custom_input_open"] = False
                    st.rerun()
        else:
            if st.button("+ 직접 추가", key="open_custom_tag_input"):
                st.session_state["todo_custom_input_open"] = True
                st.rerun()

        # 6) 추가 버튼 — 키워드 선택 후 맨 마지막
        _, add_btn_col = st.columns([6, 2])
        with add_btn_col:
            if st.button("추가 →", key="todo_direct_add", use_container_width=True, type="primary"):
                if new_item.strip():
                    direct_items.append({
                        "title": new_item.strip(),
                        "due_date": date.today().isoformat(),
                        "checked": False,
                        "tags": list(direct_tags),
                        "todo_id": str(uuid4()),
                    })
                    st.session_state["todo_direct"] = direct_items
                    st.session_state["todo_direct_input_ver"] = input_ver + 1
                    st.session_state["todo_direct_tags"] = []
                    st.session_state["todo_direct_custom_tags"] = []
                    st.session_state["todo_custom_input_open"] = False
                    st.rerun()

        if direct_items:
            del_direct: int | None = None
            for i, item in enumerate(direct_items):
                d_cols = st.columns([10, 1])
                with d_cols[0]:
                    tag_html = "".join(
                        f'<span class="todo-tag-pill">{t}</span>' for t in item.get("tags", [])
                    )
                    st.markdown(
                        f'<div class="todo-direct-item">· {item["title"]} {tag_html}</div>',
                        unsafe_allow_html=True,
                    )
                with d_cols[1]:
                    if st.button("✕", key=f"direct_del_{i}", width="stretch"):
                        del_direct = i
            if del_direct is not None:
                direct_items.pop(del_direct)
                st.session_state["todo_direct"] = direct_items
                st.rerun()

        # ── 하단 버튼 ─────────────────────────────────────
        st.markdown("---")
        cancel_col, ok_col = st.columns([1, 1])
        if cancel_col.button("취소", key="todo_cancel", width="stretch"):
            _reset_todo_state()
            st.session_state["modal"] = None
            st.rerun()
        if ok_col.button("정리하기 →", key="todo_submit", type="primary", width="stretch"):
            if not text.strip() and not direct_items:
                st.info("할 일을 입력하거나 직접 추가해주세요 ✏️")
            else:
                st.session_state["todo_text"] = text
                # LLM 호출 (실패 시 stub 폴백)
                if text.strip():
                    try:
                        from adapters.todo_creation.openai_llm import OpenAILLM as TodoOpenAILLM  # noqa: PLC0415
                        # 당일 캘린더 일정을 프롬프트에 자동 포함
                        today_str = date.today().isoformat()
                        cal_events: list[dict] = st.session_state.get("calendar_events", [])
                        today_events = [
                            ev for ev in cal_events
                            if ev.get("start_date", "") <= today_str <= ev.get("end_date", ev.get("start_date", ""))
                        ]
                        if today_events:
                            ev_names = ", ".join(ev["title"] for ev in today_events)
                            prompt_with_cal = f"{text}\n\n[오늘 일정: {ev_names}]"
                        else:
                            prompt_with_cal = text
                        llm_candidates = asyncio.run(
                            TodoOpenAILLM().split_tasks(prompt=prompt_with_cal, today=date.today())
                        )
                        candidates = [
                            {
                                "title": c.title,
                                "due_date": c.due_date.isoformat(),
                                "checked": False,
                                "tags": list(c.tags or []),  # LLM 자동 태그만 사용
                                "todo_id": str(uuid4()),
                            }
                            for c in llm_candidates
                        ]
                    except Exception:  # noqa: BLE001
                        candidates = _stub_split_tasks(text)
                        for c in candidates:
                            c["tags"] = []  # 폴백: 태그 없음
                else:
                    candidates = []
                st.session_state["todo_candidates"] = candidates
                st.session_state["todo_step"] = 2
                st.rerun()

    # ══════════════════════════════════════════════════════
    # STEP 2/2 — 확인 화면
    # ══════════════════════════════════════════════════════
    else:
        st.markdown(
            '<div class="step-tag"><span class="step">STEP 2/2</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="todo-modal-title">오늘의 할 일</div>'
            '<div class="modal-sub">다음은 몽글마을 친구들이 도와줄 임무에요!</div>',
            unsafe_allow_html=True,
        )

        candidates: list[dict] = st.session_state.get("todo_candidates", [])
        direct_items2: list[dict] = st.session_state.get("todo_direct", [])
        all_items = [c for c in candidates if c.get("title", "").strip()] + direct_items2

        delete_index: int | None = None
        for i, item in enumerate(all_items):
            # 캐릭터 배정 (있으면 이미지, 없으면 빈 박스)
            char_img = ""
            if characters:
                char = characters[i % len(characters)]
                img_url = getattr(char, "image_url", None)
                if img_url:
                    src = _img_to_data_uri(img_url)
                    char_img = f'<img src="{src}" class="todo-step2-char-img"/>' if src else '<div class="todo-step2-char-placeholder"></div>'
                else:
                    char_img = '<div class="todo-step2-char-placeholder"></div>'
            else:
                char_img = '<div class="todo-step2-char-placeholder"></div>'

            tag_html = "".join(
                f'<span class="todo-tag-pill">{t}</span>' for t in item.get("tags", [])
            )
            row_cols = st.columns([1, 1, 8, 1])
            with row_cols[0]:
                st.checkbox("항목", key=f"step2_check_{i}", disabled=True, label_visibility="collapsed")
            with row_cols[1]:
                st.markdown(char_img, unsafe_allow_html=True)
            with row_cols[2]:
                st.markdown(
                    f'<div class="todo-step2-row">'
                    f'<span class="todo-step2-title">{item["title"]}</span>'
                    f'<span class="todo-step2-tags">{tag_html}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with row_cols[3]:
                if st.button("✕", key=f"step2_del_{i}", width="stretch"):
                    delete_index = i

        if delete_index is not None:
            # 삭제: candidates 또는 direct_items2에서 제거
            cand_len = len([c for c in candidates if c.get("title", "").strip()])
            if delete_index < cand_len:
                valid_cands = [c for c in candidates if c.get("title", "").strip()]
                valid_cands.pop(delete_index)
                st.session_state["todo_candidates"] = valid_cands
            else:
                direct_items2.pop(delete_index - cand_len)
                st.session_state["todo_direct"] = direct_items2
            st.rerun()

        st.markdown("---")
        back_col, ok_col = st.columns([1, 1])
        if back_col.button("← 다시 하기", key="todo_back", width="stretch"):
            st.session_state["todo_step"] = 1
            st.session_state.pop("todo_candidates", None)
            st.rerun()
        final_items = [c for c in candidates if c.get("title", "").strip()] + direct_items2
        if ok_col.button(
            f"확인 ({len(final_items)}개)" if final_items else "확인",
            key="todo_confirm",
            type="primary",
            width="stretch",
        ):
            if not final_items:
                st.info("추가된 할 일이 없어요 ✏️")
            else:
                st.session_state["last_todo_committed"] = final_items
                _reset_todo_state()
                st.session_state["modal"] = None
                st.rerun()


def _reset_todo_state() -> None:
    for key in ("todo_text", "todo_candidates", "todo_direct", "todo_direct_input_ver",
                "todo_tags", "todo_direct_tags", "todo_step", "tag_custom_open",
                "todo_custom_tag_ver", "todo_direct_custom_tags", "todo_custom_input_open"):
        st.session_state.pop(key, None)


def _persona_fallback_quest(char) -> str:
    """LLM 없이 캐릭터 페르소나로 퀘스트 텍스트를 만드는 템플릿 폴백."""
    personality: str = getattr(char, "personality", "") or ""
    speech_style: str = getattr(char, "speech_style", "") or ""
    name: str = char.name

    # personality / speech_style 에서 짧은 핵심 단어 추출
    p_snippet = personality[:20].rstrip("., ") if personality else ""
    s_snippet = speech_style[:20].rstrip("., ") if speech_style else ""

    templates = [
        f"{name}: 오늘도 나답게, {p_snippet}... 가보자고!",
        f"({s_snippet} 말투로) 오늘 하루도 같이 해봐요~",
        f"{name}는 오늘도 자기만의 방식으로 최선을 다할 거예요!",
        f"{p_snippet}인 {name}, 오늘의 모험을 시작합니다!",
    ]
    # p_snippet이 없으면 심플 템플릿
    if not p_snippet:
        templates = [
            f"{name}가 오늘도 곁에서 응원해요!",
            f"{name}: 같이 가요, 할 수 있어요!",
        ]
    return random.choice(templates)


def _build_quest_llm(cfg: AppConfig | None):
    """cfg가 있으면 OpenAILLM, 없으면 FakeLLM을 반환한다."""
    if cfg is None:
        return FakeQuestLLM()
    try:
        from langchain_openai import ChatOpenAI  # noqa: PLC0415

        chat = ChatOpenAI(model="gpt-4o-mini", api_key=cfg.openai_api_key)
        runnable = chat.with_structured_output(
            QuestTextResponse, method="json_schema", strict=True
        )
        return QuestOpenAILLM(runnable=runnable)
    except Exception:  # noqa: BLE001
        return FakeQuestLLM()


def _assign_quests(new_todos: list[dict], characters: list, cfg: AppConfig | None = None) -> None:
    """새로 확정된 TODO에 캐릭터를 라운드로빈으로 배정하고 페르소나 기반 퀘스트를 생성한다."""
    if not characters or not new_todos:
        return

    quests: dict[str, dict] = st.session_state.get("quest_assignments", {})
    llm = _build_quest_llm(cfg)

    # 하루 5개 제한
    today_str   = date.today().isoformat()
    quest_date  = st.session_state.get("quest_date", "")
    if quest_date != today_str:
        st.session_state["quest_date"]  = today_str
        st.session_state["quests_today"] = 0
    quests_today: int = st.session_state.get("quests_today", 0)

    char_pool = list(characters)  # 라운드로빈 풀
    random.shuffle(char_pool)
    pool_cycle = char_pool.copy()

    for item in new_todos:
        if quests_today >= 5:
            break
        todo_id = item.get("todo_id")
        if not todo_id or todo_id in quests:
            continue

        # 라운드로빈: 풀 소진 시 리셋
        if not pool_cycle:
            pool_cycle = char_pool.copy()
        char = pool_cycle.pop(0)

        # 캐릭터 → quest 스키마 변환
        kws = [char.appearance_description] if getattr(char, "appearance_description", None) else []
        quest_char = QuestCharacter(
            character_id=char.character_id,
            name=char.name,
            personality=char.personality,
            speech_style=char.speech_style,
            appearance_keywords=kws,
        )

        # LLM 호출 (실패 시 페르소나 템플릿 폴백)
        try:
            quest_text = asyncio.run(llm.generate_quest(character=quest_char))
        except Exception as _e:  # noqa: BLE001
            st.warning(f"[퀘스트 LLM 오류] {type(_e).__name__}: {_e}")
            quest_text = _persona_fallback_quest(char)

        quests[todo_id] = {
            "character_id": str(char.character_id),
            "character_name": char.name,
            "character_image": char.image_url,
            "quest_text": quest_text,
            "todo_title": item["title"],
            "personality": getattr(char, "personality", "") or "",
            "speech_style": getattr(char, "speech_style", "") or "",
            "done": False,
        }
        quests_today += 1
        st.session_state["quests_today"] = quests_today

    st.session_state["quest_assignments"] = quests


@st.dialog("< QUEST >  오늘의 퀘스트", width="small")
def _char_quest_popup() -> None:
    """캐릭터 카드 클릭 시 해당 캐릭터의 퀘스트를 팝업으로 표시한다."""
    char_name: str = st.session_state.get("selected_quest_char", "")
    quests: dict[str, dict] = st.session_state.get("quest_assignments", {})
    char_quest = next(
        (q for q in quests.values() if q["character_name"] == char_name),
        None,
    )

    if not char_quest:
        st.markdown(
            f'<div class="modal-sub">{char_name}에게 배정된 퀘스트가 없어요</div>',
            unsafe_allow_html=True,
        )
        if st.button("닫기", key="char_quest_close"):
            st.session_state["modal"] = None
            st.rerun()
        return

    done = char_quest.get("done", False)
    img_src = _img_to_data_uri(char_quest.get("character_image", ""))
    img_tag = (
        f'<img src="{img_src}" width="96" height="96"'
        f' style="object-fit:cover;image-rendering:pixelated;'
        f'border:3px solid var(--wood-dark);display:block;margin:0 auto 8px;">'
        if img_src else ""
    )
    card_class = "quest-card done" if done else "quest-card"
    status_badge = (
        '<div style="font-family:\'Press Start 2P\',monospace;font-size:8px;'
        'color:var(--wood-mid);margin-top:6px;">✓ 완료</div>'
        if done else
        '<div style="font-family:\'Press Start 2P\',monospace;font-size:8px;'
        'color:var(--gold);margin-top:6px;">▶ 진행 중</div>'
    )
    st.markdown(
        f'<div class="{card_class}" style="max-width:260px;margin:0 auto;">'
        f'{img_tag}'
        f'<div class="quest-char-name">{char_name}</div>'
        f'<div class="quest-bubble">{"✓ " if done else ""}{char_quest["quest_text"]}</div>'
        f'{status_badge}'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-family:\'DotGothic16\',monospace;font-size:12px;'
        f'color:var(--wood-mid);text-align:center;margin-top:8px;">'
        f'연결된 할 일: {char_quest.get("todo_title", "")}</div>',
        unsafe_allow_html=True,
    )
    if st.button("닫기", key="char_quest_close", use_container_width=True):
        st.session_state["modal"] = None
        st.rerun()


def _quest_section() -> None:
    """메인 화면에 캐릭터 퀘스트 카드를 표시한다."""
    quests: dict[str, dict] = st.session_state.get("quest_assignments", {})
    if not quests:
        return


    st.markdown(
        '<div class="quest-header">&lt; 오늘의 퀘스트 &gt;</div>',
        unsafe_allow_html=True,
    )

    items = list(quests.items())
    cols = st.columns(min(len(items), 4))
    for idx, (todo_id, q) in enumerate(items):
        with cols[idx % min(len(items), 4)]:
            done = q.get("done", False)
            card_class = "quest-card done" if done else "quest-card"
            img_src = _img_to_data_uri(q.get("character_image", ""))
            img_tag = f'<img src="{img_src}" class="quest-char-img"/>' if img_src else ""
            st.markdown(
                f'<div class="{card_class}">'
                f'{img_tag}'
                f'<div class="quest-char-name">{q["character_name"]}</div>'
                f'<div class="quest-bubble">{"✓ " if done else ""}{q["quest_text"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _todo_list_section() -> None:
    """오늘 확인된 TODO 목록을 체크박스와 함께 표시한다."""
    todo_list: list[dict] = st.session_state.get("todo_list", [])
    if not todo_list:
        return

    active_items = [(i, item) for i, item in enumerate(todo_list) if not item.get("failed", False)]
    failed_count = len(todo_list) - len(active_items)
    total        = len(active_items)
    done_count   = sum(
        bool(st.session_state.get(f"todo_item_{i}", False))
        for i, _ in active_items
    )

    header_extra = f" · ✕{failed_count}" if failed_count else ""
    st.markdown(
        f'<div class="todo-list-header">< 오늘의 할 일 &nbsp; {done_count} / {total}{header_extra} ></div>',
        unsafe_allow_html=True,
    )

    # 이전 체크 상태 (퀘스트 완료 감지용)
    prev_states: dict[str, bool] = st.session_state.get("todo_prev_states", {})
    quests: dict[str, dict] = st.session_state.get("quest_assignments", {})
    quest_completed: str | None = None

    for i, item in enumerate(todo_list):
        prev_done = prev_states.get(str(i), False)

        # 실패 항목 — 체크박스 없이 빨간 취소선으로 표시
        if item.get("failed", False):
            st.markdown(
                f'<div class="todo-item failed">✕ {item["title"]}</div>',
                unsafe_allow_html=True,
            )
            prev_states[str(i)] = False
            continue

        col_check, col_text = st.columns([1, 10])
        with col_check:
            is_done = st.checkbox(
                item["title"],
                key=f"todo_item_{i}",
                label_visibility="hidden",
            )
        with col_text:
            css_class = "todo-item done" if is_done else "todo-item"
            st.markdown(
                f'<div class="{css_class}">{item["title"]}</div>',
                unsafe_allow_html=True,
            )

        # 새로 완료된 항목 → 연결된 퀘스트 완료 처리 + 토큰 +1 (일일 상한 10개)
        if is_done and not prev_done:
            today_str   = date.today().isoformat()
            token_date  = st.session_state.get("todo_token_date", "")
            if token_date != today_str:
                st.session_state["todo_token_date"]  = today_str
                st.session_state["todo_tokens_today"] = 0
            if st.session_state.get("todo_tokens_today", 0) < 10:
                st.session_state["tokens"] = st.session_state.get("tokens", 5) + 1
                st.session_state["todo_tokens_today"] = st.session_state.get("todo_tokens_today", 0) + 1
            todo_id = item.get("todo_id")
            if todo_id and todo_id in quests and not quests[todo_id].get("done"):
                quests[todo_id]["done"] = True
                quest_completed = quests[todo_id]["character_name"]
                # 피드 게시물 생성 대기 목록에 추가
                pending = st.session_state.get("pending_feed_quests", [])
                pending.append(todo_id)
                st.session_state["pending_feed_quests"] = pending

        prev_states[str(i)] = is_done

    # 변경사항 저장
    st.session_state["todo_prev_states"] = prev_states
    # @st.dialog 닫힐 때 Streamlit이 위젯 상태를 리셋하는 quirk에 대한 방어:
    # 현재 체크 상태를 별도 dict에 명시적으로 저장
    st.session_state["todo_done_items"] = {
        str(i): bool(st.session_state.get(f"todo_item_{i}", False))
        for i in range(total)
    }
    if quest_completed is not None:
        st.session_state["quest_assignments"] = quests
        st.session_state["quest_completed_msg"] = quest_completed
        st.rerun()

    # JS: mg-todo-anchor 에서 walk-up → 올바른 stVerticalBlock에 position:fixed 적용
    # 갤러리 오염 방지: .gallery-title 포함 시 스킵 / run ID로 구 iframe 자기 종료
    components.html(
        """
        <script>
        (function() {
          var myId = (window.parent.__mg_todo_run_id || 0) + 1;
          window.parent.__mg_todo_run_id = myId;
          var iv;
          function run() {
            if (window.parent.__mg_todo_run_id !== myId) { clearInterval(iv); return; }
            try {
              var doc = window.parent.document;
              var anchor = doc.querySelector('.mg-todo-anchor');
              if (!anchor) return;
              var el = anchor;
              while (el) {
                if (el.getAttribute && el.getAttribute('data-testid') === 'stVerticalBlock') break;
                el = el.parentElement;
              }
              if (!el) return;
              if (el.querySelector('.gallery-title')) return;  // 갤러리 블록이면 스킵
              el.style.setProperty('position',   'fixed',   'important');
              el.style.setProperty('top',        '210px',   'important');
              el.style.setProperty('right',      '16px',    'important');
              el.style.setProperty('width',      '210px',   'important');
              el.style.setProperty('z-index',    '100',     'important');
              el.style.setProperty('box-sizing', 'border-box', 'important');
              el.style.setProperty('background', '#1a1a1a', 'important');
              el.style.setProperty('border',     '4px solid #3d2818', 'important');
              el.style.setProperty('outline',    '2px solid #000',    'important');
              el.style.setProperty('padding',    '14px 16px', 'important');
              el.style.setProperty('box-shadow', 'inset 0 0 0 2px #5a3a1f, 6px 6px 0 rgba(0,0,0,0.55)', 'important');
              el.style.setProperty('max-height', '340px',  'important');
              el.style.setProperty('overflow-y', 'auto',   'important');
            } catch(e) {}
          }
          run();
          iv = setInterval(run, 300);
        })();
        </script>
        """,
        height=0,
    )



def _generate_and_store_feed_post(quest_data: dict, cfg: AppConfig | None) -> None:
    """퀘스트 완료 데이터로 피드 게시물을 생성해 session_state 에 저장한다."""

    async def _llm_caption() -> str:
        from langchain_openai import ChatOpenAI  # noqa: PLC0415

        llm = ChatOpenAI(model=cfg.model, api_key=cfg.openai_api_key, max_tokens=300)
        todo_title  = quest_data.get("todo_title") or quest_data.get("quest_text", "")
        personality = quest_data.get("personality") or "밝고 활기참"
        speech_style = quest_data.get("speech_style") or "친근한 말투"

        quest_text_inner = quest_data.get("quest_text", todo_title)
        prompt = (
            f"퀘스트: {quest_text_inner}\n"
            f"말투: {speech_style} / 성격: {personality}\n\n"
            "이 퀘스트를 직접 수행한 1인칭 SNS 게시글을 써주세요.\n"
            "조건:\n"
            "- 퀘스트 내용을 상상해서 무슨 일이 있었는지 구체적으로\n"
            "  (예: '북쪽 언덕에서 놀이공원 찾기' → '오늘은 놀이공원을 찾으러 북쪽 언덕을 샅샅이 뒤졌어. 찾았을 때 너무 기뻐서 소리질렀다!!! 🎡')\n"
            "- 이름 언급 없이, 감정과 현장감이 생생하게\n"
            "- 한국어, 140자 이내, 이모지 1~2개, 해시태그 없이"
        )
        resp = await llm.ainvoke(prompt)
        return str(resp.content).strip()[:140]

    quest_text = quest_data.get("quest_text", "")
    todo_title = quest_data.get("todo_title") or quest_text
    char_name  = quest_data["character_name"]
    caption    = f"{quest_text}... 드디어 해냈어!! ✨"
    if cfg:
        try:
            caption = asyncio.run(_llm_caption())
        except Exception:  # noqa: BLE001
            pass  # 폴백 캡션 사용

    post = {
        "character_id":    quest_data.get("character_id", ""),
        "character_name":  char_name,
        "character_image": quest_data.get("character_image", ""),
        "caption":         caption,
        "quest_text":      quest_data.get("quest_text", ""),
        "todo_title":      todo_title,
        "created_at":      datetime.now().strftime("%-m월 %-d일 %H:%M"),
        "likes":           0,
        "comments":        [],
    }
    posts: list[dict] = st.session_state.get("feed_posts", [])
    posts.insert(0, post)
    st.session_state["feed_posts"] = posts


@st.dialog("< 📱 FEED >  캐릭터 이야기", width="large")
def _feed_modal() -> None:
    posts: list[dict] = st.session_state.get("feed_posts", [])

    if not posts:
        st.markdown(
            '<div class="feed-empty">아직 게시물이 없어요.<br>'
            "할 일을 완료하면 캐릭터들이 이야기를 올려요! 🌱</div>",
            unsafe_allow_html=True,
        )
    else:
        for i, post in enumerate(posts):
            avatar_src  = _img_to_data_uri(post.get("character_image", ""))
            avatar_tag  = (
                f'<img src="{avatar_src}" class="feed-post-avatar">'
                if avatar_src
                else '<div class="feed-post-avatar-placeholder"></div>'
            )
            char_name   = post.get("character_name", "")
            created_at  = post.get("created_at", "")
            caption     = post.get("caption", "")
            todo_title  = post.get("todo_title") or post.get("quest_text", "")
            likes       = post.get("likes", 0)
            comments: list[dict] = post.get("comments", [])
            is_liked    = st.session_state.get(f"feed_liked_{i}", False)

            # 캐릭터 이미지 (작은 고정 크기)
            img_tag = (
                f'<div class="feed-post-image-wrap">'
                f'<img src="{avatar_src}" class="feed-post-image"></div>'
                if avatar_src else ""
            )

            # 댓글 HTML
            comments_html = "".join(
                f'<div class="feed-comment-item">'
                f'<span class="feed-comment-author">나</span>&nbsp;{c["text"]}'
                f'</div>'
                for c in comments
            )
            comments_block = (
                f'<div class="feed-comments-wrap">{comments_html}</div>'
                if comments else ""
            )

            st.markdown(
                f'<div class="feed-post-card">'
                f'  <div class="feed-post-header">'
                f'    {avatar_tag}'
                f'    <span class="feed-post-char-name">{char_name}</span>'
                f'    <span class="feed-post-time">{created_at}</span>'
                f'  </div>'
                f'  {img_tag}'
                f'  <div class="feed-post-caption">{caption}</div>'
                f'  <div class="feed-quest-ref">🗺 {todo_title}</div>'
                f'  {comments_block}'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ── 좋아요 / 댓글 수 액션바 ─────────────────────────────────
            like_col, cnt_col = st.columns([2, 4])
            with like_col:
                heart = "❤️" if is_liked else "🤍"
                if st.button(
                    f"{heart} {likes}",
                    key=f"feed_like_{i}",
                    use_container_width=True,
                ):
                    if is_liked:
                        posts[i]["likes"] = max(0, likes - 1)
                        st.session_state[f"feed_liked_{i}"] = False
                    else:
                        posts[i]["likes"] = likes + 1
                        st.session_state[f"feed_liked_{i}"] = True
                    st.session_state["feed_posts"] = posts
                    st.rerun()
            with cnt_col:
                st.markdown(
                    f'<div class="feed-comment-count">💬 댓글 {len(comments)}개</div>',
                    unsafe_allow_html=True,
                )

            # ── 댓글 입력 ────────────────────────────────────────────────
            ci_col, ci_btn_col = st.columns([5, 1])
            with ci_col:
                comment_val = st.text_input(
                    "댓글",
                    placeholder="댓글 달기...",
                    key=f"feed_comment_{i}",
                    label_visibility="collapsed",
                )
            with ci_btn_col:
                if st.button("게시", key=f"feed_comment_btn_{i}", use_container_width=True):
                    if comment_val.strip():
                        posts[i].setdefault("comments", []).append({
                            "text": comment_val.strip(),
                            "created_at": datetime.now().strftime("%-m월 %-d일 %H:%M"),
                        })
                        st.session_state["feed_posts"] = posts
                        st.rerun()

            st.markdown(
                '<div class="feed-divider"></div>',
                unsafe_allow_html=True,
            )

    if st.button("닫기", key="feed_close", use_container_width=True):
        st.session_state["modal"] = None
        st.rerun()


_CAL_TAGS: list[tuple[str, str]] = [
    ("일반", "#b5934a"),
    ("업무", "#4a7fb5"),
    ("건강", "#4ab57a"),
    ("학습", "#7a4ab5"),
    ("취미", "#b54a7a"),
]
_CAL_TAG_COLOR: dict[str, str] = {name: color for name, color in _CAL_TAGS}


@st.dialog("< 📅 CALENDAR >  일정 관리", width="large")
def _calendar_modal(characters: list, cfg: AppConfig | None) -> None:
    from calendar import monthcalendar  # noqa: PLC0415

    today    = date.today()
    events: list[dict]  = st.session_state.get("calendar_events", [])
    todo_list: list[dict] = st.session_state.get("todo_list", [])
    todo_done: dict       = st.session_state.get("todo_done_items", {})
    mode: str = st.session_state.get("cal_mode", "view")   # view | add | edit
    edit_id: str | None = st.session_state.get("cal_edit_id")

    # ── 날짜 → 이벤트 맵 ──────────────────────────────────────────────────────
    def _events_on(day_str: str) -> list[dict]:
        out = []
        for ev in events:
            s = ev.get("start_date", "")
            e = ev.get("end_date", s)
            if s <= day_str <= e:
                out.append(ev)
        return out

    # ── 날짜 → TODO 맵 ────────────────────────────────────────────────────────
    todos_by_date: dict[str, list[dict]] = {}
    for idx, it in enumerate(todo_list):
        due = it.get("due_date", today.isoformat())
        todos_by_date.setdefault(due, []).append(
            {**it, "done": bool(todo_done.get(str(idx), False))}
        )

    # ══════════════════════════════════════════════════════════════════════════
    # VIEW 모드
    # ══════════════════════════════════════════════════════════════════════════
    if mode == "view":
        # ── 헤더 ──────────────────────────────────────────────────────────────
        month_kr = ["1월","2월","3월","4월","5월","6월","7월","8월","9월","10월","11월","12월"]
        hdr_col, add_btn_col = st.columns([5, 1])
        with hdr_col:
            st.markdown(
                f'<div class="cal-month-header">{today.year}년 {month_kr[today.month-1]}</div>',
                unsafe_allow_html=True,
            )
        with add_btn_col:
            if st.button("＋ 일정", key="cal_go_add", use_container_width=True, type="primary"):
                st.session_state["cal_mode"] = "add"
                st.rerun()

        # ── 달력 그리드 ───────────────────────────────────────────────────────
        day_names   = ["월", "화", "수", "목", "금", "토", "일"]
        header_html = "".join(f'<div class="cal-day-header">{d}</div>' for d in day_names)
        weeks_html  = ""
        for week in monthcalendar(today.year, today.month):
            for day in week:
                if day == 0:
                    weeks_html += '<div class="cal-day empty"></div>'
                    continue
                day_str   = date(today.year, today.month, day).isoformat()
                day_evs   = _events_on(day_str)
                has_todo  = day_str in todos_by_date
                cls       = "cal-day"
                if day == today.day: cls += " today"
                # 이벤트 컬러 도트
                dots_html = ""
                for ev in day_evs[:3]:
                    color = _CAL_TAG_COLOR.get(ev.get("tag", "일반"), "#b5934a")
                    dots_html += f'<div class="cal-dot" style="background:{color}"></div>'
                if has_todo:
                    dots_html += '<div class="cal-dot todo-dot"></div>'
                weeks_html += f'<div class="{cls}">{day}<div class="cal-dots">{dots_html}</div></div>'

        st.markdown(
            f'<div class="cal-grid">'
            f'<div class="cal-day-headers">{header_html}</div>'
            f'<div class="cal-days">{weeks_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── 태그 범례 ─────────────────────────────────────────────────────────
        legend_html = " ".join(
            f'<span class="cal-legend-dot" style="background:{c}"></span>'
            f'<span class="cal-legend-label">{n}</span>'
            for n, c in _CAL_TAGS
        ) + ' <span class="cal-legend-dot todo-dot"></span><span class="cal-legend-label">TODO</span>'
        st.markdown(f'<div class="cal-legend">{legend_html}</div>', unsafe_allow_html=True)

        # ── 이달 일정 + TODO 목록 ─────────────────────────────────────────────
        month_prefix = today.strftime("%Y-%m")
        month_events = [ev for ev in events if ev.get("start_date", "").startswith(month_prefix)]
        month_todos  = {k: v for k, v in todos_by_date.items() if k.startswith(month_prefix)}
        all_dates    = sorted(set([ev["start_date"] for ev in month_events] + list(month_todos)))

        if not all_dates:
            st.markdown('<div class="cal-empty">이달 일정이 없어요 📭</div>', unsafe_allow_html=True)
        else:
            for date_str in all_dates:
                d     = date.fromisoformat(date_str)
                label = f"{d.month}월 {d.day}일" + (" (오늘)" if d == today else "")
                st.markdown(f'<div class="cal-date-label">{label}</div>', unsafe_allow_html=True)

                # 이벤트
                for ev in [e for e in month_events if e["start_date"] == date_str]:
                    color = _CAL_TAG_COLOR.get(ev.get("tag", "일반"), "#b5934a")
                    end_str = (f' ~ {ev["end_date"][5:].replace("-","/")}' if ev["end_date"] != ev["start_date"] else "")
                    ev_col, edit_col, del_col = st.columns([9, 1, 1])
                    with ev_col:
                        st.markdown(
                            f'<div class="cal-event-item">'
                            f'<span class="cal-event-tag-bar" style="background:{color}"></span>'
                            f'<span class="cal-event-title">{ev["title"]}{end_str}</span>'
                            + (f'<span class="cal-event-desc">{ev["description"]}</span>' if ev.get("description") else "")
                            + f'</div>',
                            unsafe_allow_html=True,
                        )
                    with edit_col:
                        if st.button("✎", key=f'cal_edit_{ev["event_id"]}', use_container_width=True):
                            st.session_state["cal_mode"]    = "edit"
                            st.session_state["cal_edit_id"] = ev["event_id"]
                            st.rerun()
                    with del_col:
                        if st.button("✕", key=f'cal_del_{ev["event_id"]}', use_container_width=True):
                            st.session_state["calendar_events"] = [e for e in events if e["event_id"] != ev["event_id"]]
                            st.rerun()

                # TODO (읽기 전용)
                for it in month_todos.get(date_str, []):
                    done = it["done"]
                    cls  = "cal-todo-item done" if done else "cal-todo-item"
                    st.markdown(
                        f'<div class="{cls}">{"✓" if done else "·"}&nbsp;{it["title"]}</div>',
                        unsafe_allow_html=True,
                    )

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("닫기", key="cal_close", use_container_width=True):
            st.session_state["cal_mode"] = "view"
            st.session_state["modal"] = None
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════════
    # ADD 모드
    # ══════════════════════════════════════════════════════════════════════════
    else:
        editing = mode == "edit"
        base = next((e for e in events if e.get("event_id") == edit_id), {}) if editing else {}

        st.markdown(
            f'<div class="cal-add-card-title">{"✏️  일정 수정" if editing else "＋  새 일정"}</div>',
            unsafe_allow_html=True,
        )

        new_title = st.text_input(
            "제목 *",
            value=base.get("title", ""),
            max_chars=20,
            placeholder="일정 제목 (최대 20자)",
            key="cal_ev_title",
        )
        date_col, end_col = st.columns(2)
        with date_col:
            new_start = st.date_input("시작일 *", value=date.fromisoformat(base["start_date"]) if base.get("start_date") else today, key="cal_ev_start", format="YYYY/MM/DD")
        with end_col:
            new_end = st.date_input("종료일", value=date.fromisoformat(base["end_date"]) if base.get("end_date") else today, key="cal_ev_end", format="YYYY/MM/DD")

        new_desc = st.text_area(
            "메모",
            value=base.get("description", ""),
            max_chars=200,
            placeholder="일정 설명 (선택사항, 최대 200자)",
            height=90,
            key="cal_ev_desc",
        )

        # 태그 선택
        st.markdown('<div class="kw-label">태그</div>', unsafe_allow_html=True)
        cur_tag = st.session_state.get("cal_ev_tag", base.get("tag", "일반"))
        tag_cols = st.columns(len(_CAL_TAGS))
        for ti, (tname, tcolor) in enumerate(_CAL_TAGS):
            with tag_cols[ti]:
                selected = cur_tag == tname
                if st.button(
                    f"✓ {tname}" if selected else tname,
                    key=f"cal_tag_{tname}",
                    type="primary" if selected else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["cal_ev_tag"] = tname
                    st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        cancel_col, save_col = st.columns(2)
        with cancel_col:
            if st.button("← 취소", key="cal_form_cancel", use_container_width=True):
                st.session_state["cal_mode"] = "view"
                st.session_state.pop("cal_ev_tag", None)
                st.rerun()
        with save_col:
            if st.button("저장하기 →", key="cal_form_save", type="primary", use_container_width=True):
                if not new_title.strip():
                    st.toast("제목을 입력해주세요 ✏️")
                elif new_end < new_start:
                    st.toast("종료일이 시작일보다 앞설 수 없어요 📅")
                else:
                    ev_tag = st.session_state.pop("cal_ev_tag", "일반")
                    new_ev = {
                        "event_id":    edit_id if editing else str(uuid4()),
                        "title":       new_title.strip(),
                        "description": new_desc.strip(),
                        "start_date":  new_start.isoformat(),
                        "end_date":    new_end.isoformat(),
                        "tag":         ev_tag,
                        "created_at":  datetime.now().strftime("%-m월 %-d일 %H:%M"),
                    }
                    if editing:
                        st.session_state["calendar_events"] = [
                            new_ev if e["event_id"] == edit_id else e for e in events
                        ]
                    else:
                        events.insert(0, new_ev)
                        st.session_state["calendar_events"] = events
                    st.session_state["cal_mode"] = "view"
                    st.rerun()


def _extract_plan(text: str) -> tuple[list[dict], str] | None:
    """응답에서 ===PLAN=== ... ===END=== 블록을 파싱 → (events, summary) 반환."""
    import re  # noqa: PLC0415

    match = re.search(r"===PLAN===\s*(.*?)\s*===END===", text, re.DOTALL)
    if not match:
        return None
    try:
        data      = json.loads(match.group(1))
        summary   = data.get("summary", "")
        raw_evs   = data.get("events", [])
        events: list[dict] = []
        for ev in raw_evs:
            start = ev.get("start_date", date.today().isoformat())
            end   = ev.get("end_date", start)
            tag   = ev.get("tag", "일반")
            if tag not in _CAL_TAG_COLOR:
                tag = "일반"
            events.append({
                "event_id":    str(uuid4()),
                "title":       str(ev.get("title", ""))[:20],
                "description": "",
                "start_date":  start,
                "end_date":    end,
                "tag":         tag,
                "created_at":  datetime.now().strftime("%-m월 %-d일 %H:%M"),
            })
        return events, summary
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _call_plan_llm(history: list[dict], today: date, api_key: str) -> str:
    """이장님 LLM 멀티턴 호출 — 정보 충분 시 ===PLAN=== 블록 포함 응답 반환."""
    from langchain_openai import ChatOpenAI  # noqa: PLC0415

    system = (
        "당신은 몽글마을의 다정하고 지혜로운 이장님입니다. "
        "사용자가 목표나 장기 일정을 이야기하면 함께 플랜을 만들어드려요.\n\n"
        "대화 규칙:\n"
        "- 목표·기한·하루 가용 시간 등 정보가 부족하면 자연스럽게 추가 질문을 하세요.\n"
        "- 충분한 정보가 모이면 구체적인 일자별 플랜을 만들고 아래 포맷으로 답변하세요.\n"
        "- 평소에는 친근하고 따뜻한 이장님 말투로 대화하세요.\n"
        "- 답변은 1500자를 넘지 않게 하세요.\n\n"
        "플랜 생성 포맷 (정보가 충분할 때만):\n"
        "===PLAN===\n"
        "{\n"
        '  "summary": "플랜 요약 (200자 이내)",\n'
        '  "events": [\n'
        '    {"title": "일정 제목 (20자 이내)", "start_date": "YYYY-MM-DD", '
        '"end_date": "YYYY-MM-DD", "tag": "학습"},\n'
        "    ...\n"
        "  ]\n"
        "}\n"
        "===END===\n\n"
        f"tag 가능 값: 일반·업무·건강·학습·취미\n"
        f"오늘 날짜: {today.isoformat()}"
    )
    llm  = ChatOpenAI(model="gpt-4o-mini", api_key=api_key, max_tokens=1000)
    msgs = [{"role": "system", "content": system}] + [
        {"role": m["role"], "content": m["content"]} for m in history
    ]
    resp = llm.invoke(msgs)
    return str(resp.content).strip()[:1500]


@st.dialog("< LONG-TERM PLAN >  장기 플랜 짜기", width="large")
def _plan_modal(cfg: AppConfig | None) -> None:
    st.markdown(
        '<div class="modal-sub">이장님과 대화하며 일자별 플랜을 만들어요</div>',
        unsafe_allow_html=True,
    )

    history: list[dict]    = st.session_state.get("plan_history", [])
    pending: list[dict] | None = st.session_state.get("plan_pending_events")
    summary: str           = st.session_state.get("plan_summary", "")

    # ── 채팅 말풍선 ───────────────────────────────────────────────────────────
    if not history:
        st.markdown(
            '<div class="plan-chat-wrap"><div class="plan-empty">'
            "예) 3일 후 정보처리기사 시험을 준비해야 해."
            "</div></div>",
            unsafe_allow_html=True,
        )
    else:
        bubbles = []
        for m in history:
            role  = m["role"]                       # "user" | "assistant"
            label = "나" if role == "user" else "이장님"
            bubbles.append(
                f'<div class="plan-chat-row {role}">'
                f'<div>'
                f'<div class="plan-chat-label">{label}</div>'
                f'<div class="plan-chat-bubble">{m["content"]}</div>'
                f"</div></div>"
            )
        st.markdown(
            f'<div class="plan-chat-wrap">{"".join(bubbles)}</div>',
            unsafe_allow_html=True,
        )

    # ── 플랜 확정 대기 UI ─────────────────────────────────────────────────────
    if pending is not None:
        st.markdown(
            f'<div class="plan-pending-card">'
            f'<div class="plan-pending-title">📅 캘린더에 추가할 일정</div>'
            f'<div class="plan-pending-summary">{summary}</div>'
            + "".join(
                f'<div class="plan-pending-event">'
                f'<span class="plan-pending-dot" style="background:{_CAL_TAG_COLOR.get(ev["tag"], "#b5934a")}"></span>'
                f'{ev["title"]}'
                f'<span class="plan-pending-date">{ev["start_date"]}'
                + (f' ~ {ev["end_date"]}' if ev["end_date"] != ev["start_date"] else "")
                + f'</span></div>'
                for ev in pending
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        confirm_col, reject_col = st.columns(2)
        with confirm_col:
            if st.button("📅 캘린더에 추가 →", key="plan_confirm", type="primary", use_container_width=True):
                cal_events: list[dict] = st.session_state.get("calendar_events", [])
                cal_events.extend(pending)
                st.session_state["calendar_events"] = cal_events
                st.session_state.pop("plan_pending_events", None)
                st.session_state.pop("plan_summary", None)
                st.session_state["modal"] = None
                st.toast("📅 플랜이 캘린더에 추가됐어요!")
                st.rerun()
        with reject_col:
            if st.button("↩ 다시 작성", key="plan_reject", use_container_width=True):
                st.session_state.pop("plan_pending_events", None)
                st.session_state.pop("plan_summary", None)
                st.rerun()

    # ── 입력 영역 ─────────────────────────────────────────────────────────────
    _plan_msg_key = f"plan_msg_{st.session_state.get('plan_msg_counter', 0)}"
    msg = st.text_area(
        "메시지",
        height=100,
        max_chars=600,
        placeholder="목표, 기한, 하루 가용 시간 등을 알려주세요.",
        key=_plan_msg_key,
    )
    st.caption(f"{len(msg)} / 600")

    close_col, reset_col, send_col = st.columns([1, 1, 1])
    with close_col:
        if st.button("닫기", key="plan_close", use_container_width=True):
            st.session_state["modal"] = None
            st.rerun()
    with reset_col:
        if st.button("대화 초기화", key="plan_reset", use_container_width=True):
            st.session_state["plan_history"] = []
            st.session_state.pop("plan_pending_events", None)
            st.session_state.pop("plan_summary", None)
            st.rerun()
    with send_col:
        if st.button(
            "보내기 →",
            key="plan_send",
            type="primary",
            use_container_width=True,
            disabled=not msg.strip(),
        ):
            new_history = history + [{"role": "user", "content": msg.strip()}]

            if cfg:
                with st.spinner("이장님이 생각 중이에요..."):
                    try:
                        response = _call_plan_llm(new_history, date.today(), cfg.openai_api_key)
                    except Exception:  # noqa: BLE001
                        response = "죄송해요, 잠시 연결이 어렵네요. 다시 시도해볼까요? 🏡"
            else:
                response = "AI 설정이 필요해요. 환경변수를 확인해주세요."

            # 플랜 블록 추출
            plan_result = _extract_plan(response)
            if plan_result:
                events, plan_summary = plan_result
                clean_text = response[:response.find("===PLAN===")].strip()
                if not clean_text:
                    clean_text = "플랜을 완성했어요! 아래 일정을 캘린더에 추가해볼까요? 📅"
                new_history.append({"role": "assistant", "content": clean_text})
                st.session_state["plan_pending_events"] = events
                st.session_state["plan_summary"]        = plan_summary
            else:
                new_history.append({"role": "assistant", "content": response})

            st.session_state["plan_history"] = new_history
            st.session_state["plan_msg_counter"] = st.session_state.get("plan_msg_counter", 0) + 1
            st.rerun()


@st.dialog("< DAILY RETRO >  오늘 하루는 어땠어?", width="large")
def _reflection_modal() -> None:
    is_edit = st.session_state.get("reflection_done", False)
    saved   = st.session_state.get("reflection", {})

    st.markdown(
        f'<div class="modal-sub">{"수정 모드 — 기존 회고를 수정해요" if is_edit else "하루의 일이 끝났어요! 내일이 기대되죠"}</div>',
        unsafe_allow_html=True,
    )

    # 퀘스트를 완료한 친구들 표시
    quests: dict[str, dict] = st.session_state.get("quest_assignments", {})
    done_quests = [q for q in quests.values() if q.get("done", False)]
    st.markdown('<div class="retro-section-label">🏆 퀘스트를 완료한 친구들</div>', unsafe_allow_html=True)
    if done_quests:
        char_cols = st.columns(min(len(done_quests), 4))
        for idx, q in enumerate(done_quests):
            with char_cols[idx % min(len(done_quests), 4)]:
                img_src = _img_to_data_uri(q.get("character_image", ""))
                img_tag = (
                    f'<img src="{img_src}" width="64" height="64"'
                    f' style="object-fit:cover;image-rendering:pixelated;'
                    f'border:2px solid var(--wood-dark);display:block;margin:0 auto 4px;">'
                    if img_src else ""
                )
                st.markdown(
                    f'<div style="text-align:center">'
                    f'{img_tag}'
                    f'<div class="retro-char-name">{q["character_name"]}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.markdown(
            '<div class="retro-empty">아직 완료된 퀘스트가 없어요</div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # 수정 모드: 기존 내용 pre-fill (최초 1회)
    if is_edit and not st.session_state.get("retro_prefilled"):
        st.session_state["retro_good"]    = saved.get("good", "")
        st.session_state["retro_bad"]     = saved.get("bad", "")
        st.session_state["retro_prefilled"] = True

    good_text = st.text_area(
        "잘한 일",
        height=120,
        max_chars=400,
        placeholder="오늘 잘 한 일이나 뿌듯했던 것들을 적어봐요",
        key="retro_good",
    )
    bad_text = st.text_area(
        "아쉬운 일",
        height=120,
        max_chars=400,
        placeholder="아쉬웠던 점이나 다음엔 더 잘하고 싶은 것들을 적어봐요",
        key="retro_bad",
    )

    if is_edit:
        st.markdown(
            '<div class="retro-token-info">✏️ 수정 시 토큰 15개가 소모됩니다 🍎</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="retro-token-info">🍎 회고 작성 완료 시 사과 토큰을 받을 수 있어요 (잘한 일 +2, 아쉬운 일 +2)</div>',
            unsafe_allow_html=True,
        )

    cancel_col, ok_col = st.columns([1, 1])
    if cancel_col.button("취소", key="retro_cancel", width="stretch"):
        st.session_state.pop("retro_prefilled", None)
        st.session_state["modal"] = None
        st.rerun()
    if ok_col.button("기록하기 →", key="retro_submit", type="primary", width="stretch"):
        # 수정 모드: 토큰 15개 차감
        if is_edit:
            current_tokens = st.session_state.get("tokens", 0)
            if current_tokens < 15:
                st.warning(f"토큰이 부족해요! 수정에는 🍎 15개가 필요해요 (현재 {current_tokens}개)")
                return
            st.session_state["tokens"] = current_tokens - 15
            token_gain = 0
        else:
            token_gain = 0
            if len(good_text.strip()) >= 30:
                token_gain += 2
            if len(bad_text.strip()) >= 30:
                token_gain += 2
            st.session_state["tokens"] = st.session_state.get("tokens", 5) + token_gain

        st.session_state["reflection_done"] = True
        st.session_state["reflection"] = {
            "good": good_text.strip(),
            "bad":  bad_text.strip(),
            "date": date.today().isoformat(),
        }
        st.session_state.pop("retro_prefilled", None)
        if not is_edit and token_gain > 0:
            st.session_state["reflection_token_msg"] = token_gain
        elif is_edit:
            st.session_state["reflection_token_msg"] = -15  # 소모 알림용
        st.session_state["modal"] = None
        st.rerun()


# ────────────────────────────────────────────────────────────────────────────
# Error / config / repo
# ────────────────────────────────────────────────────────────────────────────
def _handle_pipeline_error(err: Exception) -> None:
    if isinstance(err, ValidationFailedError):
        st.error(f"[{err.code}] {err.message}")
    elif isinstance(err, LLMFailedError):
        st.error("페르소나 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.")
    elif isinstance(err, VLMFailedError):
        st.error("이미지 분석에 실패했습니다.")
    elif isinstance(err, ImageGenerationFailedError):
        st.error("이미지 생성에 실패했습니다.")
    elif isinstance(err, S3UploadFailedError):
        st.error("이미지 저장(S3)에 실패했습니다.")
    else:
        st.error(f"예상치 못한 오류: {err}")
    with st.expander("디버그 정보"):
        st.code("".join(traceback.format_exception(type(err), err, err.__traceback__)))


_DEMO_CHARS_PATH = _PROJECT_ROOT / "data" / "demo_chars.json"


def _save_demo_chars(repo: InMemoryRepo) -> None:
    """캐릭터 목록을 JSON 파일로 저장 (데모 영속성)."""
    try:
        _DEMO_CHARS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            uid: [e.model_dump(mode="json") for e in chars]
            for uid, chars in repo._characters.items()
        }
        _DEMO_CHARS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


def _load_demo_chars(repo: InMemoryRepo) -> None:
    """JSON 파일에서 캐릭터 목록을 복원 (데모 영속성)."""
    if not _DEMO_CHARS_PATH.exists():
        return
    try:
        raw: dict = json.loads(_DEMO_CHARS_PATH.read_text(encoding="utf-8"))
        for uid, chars in raw.items():
            existing_ids = {str(e.character_id) for e in repo._characters.get(uid, [])}
            for c in chars:
                if str(c.get("character_id", "")) not in existing_ids:
                    entity = CharacterEntity.model_validate(c)
                    repo._characters.setdefault(uid, []).append(entity)
    except Exception:  # noqa: BLE001
        pass


def _get_repo() -> InMemoryRepo:
    if "repo" not in st.session_state:
        repo = InMemoryRepo()
        _load_demo_chars(repo)   # 새 세션 시작 시 파일에서 복원
        st.session_state["repo"] = repo
    return st.session_state["repo"]


def _get_config() -> AppConfig | None:
    try:
        return AppConfig.from_env()
    except MissingEnvError as err:
        st.error(str(err))
        return None


def _sidebar(repo: InMemoryRepo) -> tuple[str, bool]:
    st.sidebar.markdown(
        '<div class="sidebar-title">&lt; SETTINGS &gt;</div>',
        unsafe_allow_html=True,
    )
    user_id = st.sidebar.text_input("user_id", value="demo-user")
    is_regen = st.sidebar.checkbox("재생성 모드", value=False)
    active = asyncio.run(repo.count_active(user_id))
    regen = asyncio.run(repo.today_regen_count(user_id))
    st.sidebar.metric("보유 캐릭터", f"{active}/10")
    st.sidebar.metric("오늘 재생성", f"{regen}/3")
    return user_id, is_regen


def _gallery(repo: InMemoryRepo, user_id: str) -> None:
    chars = repo.list_characters(user_id)
    if not chars:
        return
    quests: dict[str, dict] = st.session_state.get("quest_assignments", {})
    st.markdown(
        f'<div class="gallery-title">&lt; RESIDENTS · {len(chars)} &gt;</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    for idx, char in enumerate(chars):
        with cols[idx % 4]:
            img_src = _img_to_data_uri(char.image_url)
            char_quest = next(
                (q for q in quests.values() if q["character_name"] == char.name),
                None,
            )
            # 이미지 — parchment 배경으로 투명 PNG 보호
            img_tag = f'<img src="{img_src}" class="char-gallery-img">' if img_src else ""
            st.markdown(
                f'<div class="char-img-wrap">{img_tag}</div>',
                unsafe_allow_html=True,
            )
            # 이름 — 퀘스트 있으면 클릭 가능 버튼, 없으면 텍스트
            if char_quest:
                if st.button(
                    char.name,
                    key=f"gallery_char_{idx}",
                    use_container_width=True,
                ):
                    st.session_state["modal"] = "char_quest"
                    st.session_state["selected_quest_char"] = char.name
                    st.rerun()
            else:
                st.markdown(
                    f'<div class="char-name">{char.name}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div class="char-meta">{(char.personality or "")[:40]}…</div>',
                unsafe_allow_html=True,
            )


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
def main() -> None:
    # 토큰 초기화 (세션 첫 실행)
    if "tokens" not in st.session_state:
        st.session_state["tokens"] = 5

    _inject_css()
    _topbar()

    cfg = _get_config()
    if cfg is None:
        return
    repo = _get_repo()
    user_id, is_regen = _sidebar(repo)

    # 확인된 TODO → 영구 목록에 누적 + 퀘스트 배정
    if "last_todo_committed" in st.session_state:
        committed = st.session_state.pop("last_todo_committed")
        existing: list[dict] = st.session_state.get("todo_list", [])
        existing.extend(committed)
        st.session_state["todo_list"] = existing
        st.session_state["todo_list_date"] = date.today().isoformat()
        characters = repo.list_characters(user_id)
        _assign_quests(committed, characters, cfg)
        titles = ", ".join(c["title"] for c in committed)
        st.success(f"오늘의 할 일 {len(committed)}개가 등록되었어요 — {titles}")

    # ── 자정 미완료 실패 처리 ────────────────────────────────────────────────
    _today_str    = date.today().isoformat()
    _todo_list    = st.session_state.get("todo_list", [])
    _todo_list_dt = st.session_state.get("todo_list_date", _today_str)
    _done_map     = st.session_state.get("todo_done_items", {})

    if _todo_list and _todo_list_dt < _today_str:
        _uncompleted = [
            i for i, item in enumerate(_todo_list)
            if not _done_map.get(str(i), False) and not item.get("failed", False)
        ]
        if _uncompleted:
            _tokens     = st.session_state.get("tokens", 0)
            _can_extend = (
                _tokens >= 4
                and st.session_state.get("todo_extended_date") != _today_str
            )
            _warn_col, _btn_col = st.columns([3, 1])
            with _warn_col:
                st.warning(f"🔴 어제 미완료 **{len(_uncompleted)}개** 항목이 실패했어요.")
            with _btn_col:
                if _can_extend and st.button(
                    "🔄 연장 (토큰 -4)", key="midnight_extend", use_container_width=True
                ):
                    st.session_state["tokens"]            = _tokens - 4
                    st.session_state["todo_list_date"]    = _today_str
                    st.session_state["todo_extended_date"] = _today_str
                    st.toast("🔄 TODO가 오늘까지 연장됐어요! 토큰 4개 소모")
                    st.rerun()
                if st.button("실패 확인", key="midnight_dismiss", use_container_width=True):
                    for _i in _uncompleted:
                        _todo_list[_i]["failed"] = True
                    st.session_state["todo_list"]      = _todo_list
                    st.session_state["todo_list_date"] = _today_str
                    st.rerun()

    if "last_created" in st.session_state:
        entity: CharacterEntity = st.session_state.pop("last_created")
        st.success(f"'{entity.name}' 님이 마을에 도착했어요!")

    # 퀘스트 완료 알림 + 피드 게시물 생성
    if "quest_completed_msg" in st.session_state:
        char_name = st.session_state.pop("quest_completed_msg")
        st.success(f"🎉 {char_name}의 퀘스트 달성! 수고했어요!")

    # 대기 중인 피드 게시물 생성 처리
    pending_feed: list[str] = st.session_state.pop("pending_feed_quests", [])
    if pending_feed:
        quests_all: dict[str, dict] = st.session_state.get("quest_assignments", {})
        for _tid in pending_feed:
            _qdata = quests_all.get(_tid)
            if _qdata:
                _generate_and_store_feed_post(_qdata, cfg)

    # 회고 토큰 지급/소모 알림
    if "reflection_token_msg" in st.session_state:
        delta = st.session_state.pop("reflection_token_msg")
        if delta > 0:
            st.success(f"🍎 회고 완료! 사과 토큰 +{delta}개를 받았어요!")
        elif delta < 0:
            st.info(f"✏️ 회고가 수정되었어요! 토큰 {abs(delta)}개가 소모됐어요.")

    # TODO 진행 상황 계산 → 날짜 패널에 전달
    todo_list: list[dict] = st.session_state.get("todo_list", [])
    # @st.dialog 종료 시 위젯 상태가 리셋될 수 있으므로, persistent dict에서 복원
    _todo_done: dict = st.session_state.get("todo_done_items", {})
    for _i in range(len(todo_list)):
        if _todo_done.get(str(_i), False):
            st.session_state[f"todo_item_{_i}"] = True
    todo_entries: list[tuple[str, bool]] = [
        (item["title"], bool(st.session_state.get(f"todo_item_{i}", False)))
        for i, item in enumerate(todo_list)
    ]

    # TODO 전체 완료 시 회고 유도 토스트 (하루 1회)
    if todo_entries and all(done for _, done in todo_entries):
        today_str = date.today().isoformat()
        if st.session_state.get("retro_nudge_date") != today_str:
            st.session_state["retro_nudge_date"] = today_str
            st.toast("🎉 오늘 할 일을 모두 완료했어요! 회고를 작성해볼까요? 📓")

    _village_map()
    _timer_panel()
    _date_panel(date.today(), todo_entries or None)
    _diary_icon_panel()
    _feed_icon_panel()

    _chief_house_cta()
    _chief_dialog()

    with st.container():
        # CSS :has(.mg-todo-anchor) 가 이 컨테이너를 position:fixed 패널로 만든다
        # layout.css 의 mg-todo-anchor 규칙 참조
        st.markdown('<span class="mg-todo-anchor" style="display:none"></span>', unsafe_allow_html=True)
        _todo_list_section()

    modal = st.session_state.get("modal")
    characters = repo.list_characters(user_id)
    if modal == "character":
        _character_modal(user_id, is_regen, repo, cfg)
    elif modal == "todo":
        _todo_modal(characters)
    elif modal == "plan":
        _plan_modal(cfg)
    elif modal == "reflection":
        _reflection_modal()
    elif modal == "feed":
        _feed_modal()
    elif modal == "calendar":
        _calendar_modal(characters, cfg)
    elif modal == "char_quest":
        _char_quest_popup()

    _gallery(repo, user_id)


main()
