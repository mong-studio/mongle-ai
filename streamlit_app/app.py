from __future__ import annotations

import asyncio
import base64
import json
import random
import sys
import traceback
import warnings
from datetime import date
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

# langgraph 가 import 시 langchain-core 의 Reviver 를 인자 없이 생성하여
# LangChainPendingDeprecationWarning 을 띄운다. 라이브러리 내부 호출이라
# 사용자가 인자를 넘길 수 없으므로 import 전에 필터링한다.
# langchain_core._api.deprecation 은 import 시 자체 'default' 필터를 등록하므로
# 더 구체적인 서브클래스로 ignore 를 지정해야 우선 적용된다.
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
    "widgets.css",
    "sidebar.css",
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
            if (lbl) lbl.textContent = state.isBreak ? '< BREAK TIME >' : '< FOCUS TIME >';
            if (dsp) dsp.textContent = fmt(getRem());
            if (met) met.textContent = state.cycles + ' CYCLES';
            if (btn) btn.textContent = state.running ? '⏸ PAUSE' : '▶ START';
            /* 휴식 중이면 타이머를 골드→청량한 색으로 표시 */
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




def _diary_icon_panel() -> None:
    """회고 아이콘 버튼 — 타이머/투두 패널과 동일한 JS 패턴으로 날짜 패널 왼쪽에 고정."""
    with st.container():
        st.markdown('<span class="mg-diary-marker"></span>', unsafe_allow_html=True)
        if st.button("📓", key="open_reflection_diary"):
            st.session_state["modal"] = "reflection"
            st.rerun()

    components.html(
        """
        <script>
        (function() {
          if (window.__mg_diary_pos) return;
          window.__mg_diary_pos = true;

          function run() {
            try {
              var doc = window.parent.document;
              var marker = doc.querySelector('.mg-diary-marker');
              if (!marker) return;
              var el = marker;
              while (el) {
                if (el.getAttribute && el.getAttribute('data-testid') === 'stVerticalBlock') break;
                el = el.parentElement;
              }
              if (!el) return;

              /* 날짜 패널(right:16px, width:210px) 바로 왼쪽에 고정 */
              el.style.setProperty('position',    'fixed',                                   'important');
              el.style.setProperty('top',         '74px',                                    'important');
              el.style.setProperty('right',       '234px',                                   'important');
              el.style.setProperty('z-index',     '100',                                     'important');
              el.style.setProperty('width',       'auto',                                    'important');
              el.style.setProperty('background',  '#1a1a1a',                                 'important');
              el.style.setProperty('border',      '4px solid #3d2818',                       'important');
              el.style.setProperty('outline',     '2px solid #000',                          'important');
              el.style.setProperty('padding',     '8px 10px',                                'important');
              el.style.setProperty('box-shadow',  'inset 0 0 0 2px #5a3a1f, 6px 6px 0 rgba(0,0,0,0.55)', 'important');

              /* 버튼 자체를 투명 아이콘처럼 */
              var btn = el.querySelector('button');
              if (btn) {
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
              }
            } catch(e) {}
          }

          run();
          setInterval(run, 300);
        })();
        </script>
        """,
        height=0,
    )


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

    cols = st.columns([2, 2, 2])
    with cols[1]:
        if st.button(label, key="knock_chief", type="primary", width="stretch"):
            st.session_state["chief_open"] = not is_open
            st.session_state["modal"] = None
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
        max_chars=500,
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

        # 1) 할 일 입력 + 추가 버튼
        add_col, btn_col = st.columns([8, 2])
        with add_col:
            new_item = st.text_input(
                "직접 추가",
                placeholder="예) 세탁기 돌리기",
                key=f"todo_direct_input_{input_ver}",
                label_visibility="collapsed",
            )
        with btn_col:
            if st.button("추가 +", key="todo_direct_add", width="stretch"):
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
                    st.session_state["todo_direct_tags"] = []  # 추가 후 태그 초기화
                    st.rerun()

        # 2) 키워드 선택 레이블 + 태그 버튼
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
        dt_cols = st.columns(len(_PRESET_TAGS))
        for _ti, _tag in enumerate(_PRESET_TAGS):
            _sel = _tag in direct_tags
            with dt_cols[_ti]:
                if st.button(
                    f"✓ {_tag}" if _sel else _tag,
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
                        llm_candidates = asyncio.run(
                            TodoOpenAILLM().split_tasks(prompt=text, today=date.today())
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


def _run_todo_pipeline(text: str, user_id: str, cfg: AppConfig) -> list[dict]:
    from datetime import datetime as _dt

    from agents.todo_creation.schemas import SingleTurnInput
    from agents.todo_creation.single_turn.pipeline import run as todo_run

    inp = SingleTurnInput(user_id=user_id, prompt=text, today=date.today())
    ports = build_todo_generate_ports(cfg)
    result = asyncio.run(todo_run(inp, ports=ports, now=_dt.now()))
    return [
        {"title": t.title, "due_date": t.due_date.isoformat(), "checked": True, "tags": t.tags, "todo_id": str(uuid4())}
        for t in result.todos + result.calendar_events
    ]


def _reset_todo_state() -> None:
    for key in ("todo_text", "todo_candidates", "todo_direct", "todo_direct_input_ver",
                "todo_tags", "todo_direct_tags", "todo_step", "tag_custom_open"):
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

    char_pool = list(characters)  # 라운드로빈 풀
    random.shuffle(char_pool)
    pool_cycle = char_pool.copy()

    for item in new_todos:
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
            "done": False,
        }

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

    total = len(todo_list)
    done_count = sum(
        bool(st.session_state.get(f"todo_item_{i}", False))
        for i in range(total)
    )

    st.markdown(
        f'<div class="todo-list-header">< 오늘의 할 일 &nbsp; {done_count} / {total} ></div>',
        unsafe_allow_html=True,
    )

    # 이전 체크 상태 (퀘스트 완료 감지용)
    prev_states: dict[str, bool] = st.session_state.get("todo_prev_states", {})
    quests: dict[str, dict] = st.session_state.get("quest_assignments", {})
    quest_completed: str | None = None

    for i, item in enumerate(todo_list):
        prev_done = prev_states.get(str(i), False)

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

        # 새로 완료된 항목 → 연결된 퀘스트 완료 처리 + 토큰 +1
        if is_done and not prev_done:
            st.session_state["tokens"] = st.session_state.get("tokens", 5) + 1
            todo_id = item.get("todo_id")
            if todo_id and todo_id in quests and not quests[todo_id].get("done"):
                quests[todo_id]["done"] = True
                quest_completed = quests[todo_id]["character_name"]

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

    # CSS :has() 선택자가 이 컨테이너를 position:fixed 패널로 만든다.
    # layout.css 의 .mg-todo-anchor 규칙 참조 — JS iframe 불필요.



@st.dialog("< LONG-TERM PLAN >  장기 플랜 짜기", width="large")
def _plan_modal() -> None:
    st.markdown(
        '<div class="modal-sub">이장님과 대화하며 일자별 플랜을 만들어요</div>',
        unsafe_allow_html=True,
    )

    history: list[dict] = st.session_state.get("plan_history", [])

    if not history:
        st.markdown(
            '<div class="plan-chat-wrap"><div class="plan-empty">'
            "예) 3일 후 정보처리기사 시험을 준비해야 해."
            "</div></div>",
            unsafe_allow_html=True,
        )
    else:
        bubbles = []
        for msg in history:
            role = msg["role"]
            label = "나" if role == "user" else "이장"
            bubbles.append(
                f'<div class="plan-chat-row {role}">'
                f'<div>'
                f'<div class="plan-chat-label">{label}</div>'
                f'<div class="plan-chat-bubble">{msg["text"]}</div>'
                f"</div></div>"
            )
        st.markdown(
            f'<div class="plan-chat-wrap">{"".join(bubbles)}</div>',
            unsafe_allow_html=True,
        )

    msg = st.text_area(
        "메시지",
        height=120,
        max_chars=600,
        placeholder="목표, 기한, 하루 가용 시간 등을 알려주세요.",
        key="plan_msg",
    )
    st.caption(f"{len(msg)} / 600")

    cols = st.columns([1, 1, 1])
    if cols[0].button("닫기", key="plan_close", width="stretch"):
        st.session_state["modal"] = None
        st.rerun()
    if cols[1].button("대화 초기화", key="plan_reset", width="stretch"):
        st.session_state["plan_history"] = []
        st.rerun()
    if cols[2].button(
        "보내기 →",
        key="plan_send",
        type="primary",
        width="stretch",
        disabled=not msg.strip(),
    ):
        history.append({"role": "user", "text": msg.strip()})
        # TODO: hook up agents/todo_creation/multi_turn/pipeline.py
        # For now, stub a follow-up question so the UX shape is visible.
        history.append(
            {
                "role": "chief",
                "text": "좋아요. 목표 점수나 결과는 어떻게 되나요? 하루에 얼마나 시간을 낼 수 있어요?",
            }
        )
        st.session_state["plan_history"] = history
        st.rerun()


@st.dialog("< DAILY RETRO >  오늘 하루는 어땠어?", width="large")
def _reflection_modal() -> None:
    st.markdown(
        '<div class="modal-sub">하루의 일이 끝났어요! 내일이 기대되죠</div>',
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

    st.markdown(
        '<div class="retro-token-info">🍎 회고 작성 완료 시 사과 토큰을 받을 수 있어요 (잘한 일 +2, 아쉬운 일 +2)</div>',
        unsafe_allow_html=True,
    )

    cancel_col, ok_col = st.columns([1, 1])
    if cancel_col.button("취소", key="retro_cancel", width="stretch"):
        st.session_state["modal"] = None
        st.rerun()
    if ok_col.button("기록하기 →", key="retro_submit", type="primary", width="stretch"):
        token_gain = 0
        if len(good_text.strip()) >= 30:
            token_gain += 2
        if len(bad_text.strip()) >= 30:
            token_gain += 2
        st.session_state["tokens"] = st.session_state.get("tokens", 5) + token_gain
        st.session_state["reflection_done"] = True
        st.session_state["reflection"] = {
            "good": good_text.strip(),
            "bad": bad_text.strip(),
            "date": date.today().isoformat(),
        }
        if token_gain > 0:
            st.session_state["reflection_token_msg"] = token_gain
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
        characters = repo.list_characters(user_id)
        _assign_quests(committed, characters, cfg)
        titles = ", ".join(c["title"] for c in committed)
        st.success(f"오늘의 할 일 {len(committed)}개가 등록되었어요 — {titles}")

    if "last_created" in st.session_state:
        entity: CharacterEntity = st.session_state.pop("last_created")
        st.success(f"'{entity.name}' 님이 마을에 도착했어요!")

    # 퀘스트 완료 알림
    if "quest_completed_msg" in st.session_state:
        char_name = st.session_state.pop("quest_completed_msg")
        st.success(f"🎉 {char_name}의 퀘스트 달성! 수고했어요!")

    # 회고 토큰 지급 알림
    if "reflection_token_msg" in st.session_state:
        gained = st.session_state.pop("reflection_token_msg")
        st.success(f"🍎 회고 완료! 사과 토큰 +{gained}개를 받았어요!")

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

    _village_map()
    _timer_panel()
    _date_panel(date.today(), todo_entries or None)
    _diary_icon_panel()

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
        _plan_modal()
    elif modal == "reflection":
        _reflection_modal()
    elif modal == "char_quest":
        _char_quest_popup()

    _gallery(repo, user_id)


main()
