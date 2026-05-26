from __future__ import annotations

import asyncio
import base64
import sys
import traceback
import warnings
from datetime import date
from functools import lru_cache
from pathlib import Path

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
from streamlit_app.ports_factory import (  # noqa: E402
    AppConfig,
    MissingEnvError,
    build_ports,
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
    st.markdown(
        """
        <div class="pixel-topbar">
          <div class="menu">
            <span>TOWN INFO</span>
            <span>RESIDENTS</span>
            <span>SETTINGS</span>
          </div>
          <div class="brand">몽글마을</div>
          <div class="session">GUEST</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _timer_panel() -> None:
    st.markdown(
        """
        <div class="timer-overlay">
          <div class="side-panel">
            <div class="label">&lt; FOCUS TIME &gt;</div>
            <div class="timer-display">25:00</div>
            <div class="timer-meta">0 CYCLES</div>
            <div class="pixel-row">
              <div class="pixel-btn dark">▶ START</div>
              <div class="pixel-btn">RESET</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _date_panel(today: date) -> None:
    day_short = today.strftime("%a").upper()
    date_str = today.strftime("%Y.%m.%d")
    st.markdown(
        f"""
        <div class="date-overlay">
          <div class="side-panel">
            <div class="date-display">{date_str}</div>
            <div class="date-day">{day_short}</div>
            <div class="date-hint">
              오늘의 할 일을 추가해보세요<br/>
              <span class="key">PRESS &lt;+&gt; TO ADD</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@lru_cache(maxsize=1)
def _background_data_uri() -> str:
    img_path = _PROJECT_ROOT / "assets" / "background.jpeg"
    data = base64.b64encode(img_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{data}"


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

    uploaded = st.file_uploader(
        "참고 이미지 (선택, png/jpeg, 5MB 이내)",
        type=["png", "jpg", "jpeg"],
        key="char_image",
    )
    if uploaded is not None:
        preview_col, _ = st.columns([1, 3])
        with preview_col:
            st.markdown('<div class="preview-frame">', unsafe_allow_html=True)
            st.image(uploaded, width="stretch")
            st.markdown(
                f'<div class="preview-caption">{uploaded.name}</div></div>',
                unsafe_allow_html=True,
            )
    name = st.text_input("이름 *", max_chars=50, placeholder="예) 다온, 몽글이", key="char_name")
    keyword_labels = [k.value for k in PersonalityKeyword]
    chosen = st.multiselect(
        "성격 키워드 (최대 3개)",
        keyword_labels,
        max_selections=3,
        key="char_keywords",
    )
    persona = st.text_area(
        "캐릭터 설명 *",
        height=130,
        placeholder="어떤 친구인가요?",
        max_chars=500,
        key="char_persona",
    )

    cancel_col, ok_col = st.columns([1, 1])
    if cancel_col.button("취소", key="char_cancel", width="stretch"):
        st.session_state["modal"] = None
        st.rerun()
    if ok_col.button("생성하기 →", key="char_submit", type="primary", width="stretch"):
        try:
            source_image: SourceImage | None = None
            if uploaded is not None:
                source_image = SourceImage(
                    filename=uploaded.name,
                    content_type=uploaded.type or "image/png",
                    data=uploaded.getvalue(),
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
        st.session_state["last_created"] = entity
        st.session_state["modal"] = None
        st.rerun()


@st.dialog("< TODO LIST >  오늘 뭐 할거야?", width="large")
def _todo_modal() -> None:
    st.markdown(
        '<div class="modal-sub">잎새마을 주민들이 너의 할 일을 정리해줄게</div>',
        unsafe_allow_html=True,
    )
    text = st.text_area(
        "할 일",
        value=st.session_state.get("todo_text", ""),
        height=180,
        max_chars=200,
        placeholder="예) 정자 1단계 끝내고, 청소도 하고, 강아지 산책 두 번 시켜야 함.",
        key="todo_text_input",
    )
    st.caption(f"{len(text)} / 200")

    candidates: list[dict] = st.session_state.get("todo_candidates", [])
    organize_label = "다시 정리하기 →" if candidates else "정리하기 →"

    cancel_col, ok_col = st.columns([1, 1])
    if cancel_col.button("취소", key="todo_cancel", width="stretch"):
        _reset_todo_state()
        st.session_state["modal"] = None
        st.rerun()
    if ok_col.button(
        organize_label,
        key="todo_submit",
        type="primary",
        width="stretch",
        disabled=not text.strip(),
    ):
        st.session_state["todo_text"] = text
        st.session_state["todo_candidates"] = _stub_split_tasks(text)
        st.rerun()

    candidates = st.session_state.get("todo_candidates", [])
    if not candidates:
        return

    st.markdown("---")
    delete_index: int | None = None
    for i, cand in enumerate(candidates):
        cols = st.columns([10, 1])
        with cols[0]:
            cand["title"] = st.text_input(
                "할 일 제목",
                value=cand["title"],
                key=f"cand_title_{i}",
                label_visibility="collapsed",
            )
        with cols[1]:
            if st.button("✕", key=f"cand_del_{i}", width="stretch"):
                delete_index = i
    if delete_index is not None:
        candidates.pop(delete_index)
        st.session_state["todo_candidates"] = candidates
        st.rerun()

    confirmed = [c for c in candidates if c.get("title", "").strip()]
    if st.button(
        f"확인 ({len(confirmed)})",
        key="todo_confirm",
        type="primary",
        width="stretch",
        disabled=not confirmed,
    ):
        st.session_state["last_todo_committed"] = confirmed
        _reset_todo_state()
        st.session_state["modal"] = None
        st.rerun()


def _stub_split_tasks(text: str) -> list[dict]:
    """Placeholder for `agents.todo_creation.single_turn.task_splitter`.

    Replace with real LLM split + date routing once the pipeline lands.
    """
    today = date.today()
    parts = [p.strip(" .,") for p in text.replace("\n", ",").split(",") if p.strip()]
    return [
        {"title": p, "due_date": today.isoformat(), "checked": True, "tags": []}
        for p in parts
    ]


def _reset_todo_state() -> None:
    for key in ("todo_text", "todo_candidates"):
        st.session_state.pop(key, None)


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


def _get_repo() -> InMemoryRepo:
    if "repo" not in st.session_state:
        st.session_state["repo"] = InMemoryRepo()
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
    st.markdown(
        f'<div class="gallery-title">&lt; RESIDENTS · {len(chars)} &gt;</div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    for idx, char in enumerate(chars):
        with cols[idx % 4]:
            st.image(char.image_url, width="stretch")
            st.markdown(
                f'<div class="char-card">'
                f'<div class="char-name">{char.name}</div>'
                f'<div class="char-meta">{char.personality[:40]}…</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
def main() -> None:
    _inject_css()
    _topbar()

    cfg = _get_config()
    if cfg is None:
        return
    repo = _get_repo()
    user_id, is_regen = _sidebar(repo)

    _village_map()
    _timer_panel()
    _date_panel(date.today())

    _chief_house_cta()
    _chief_dialog()

    if "last_created" in st.session_state:
        entity: CharacterEntity = st.session_state.pop("last_created")
        st.success(f"'{entity.name}' 님이 마을에 도착했어요!")

    if "last_todo_committed" in st.session_state:
        committed = st.session_state.pop("last_todo_committed")
        titles = ", ".join(c["title"] for c in committed)
        st.success(f"오늘의 할 일 {len(committed)}개가 등록되었어요 — {titles}")

    modal = st.session_state.get("modal")
    if modal == "character":
        _character_modal(user_id, is_regen, repo, cfg)
    elif modal == "todo":
        _todo_modal()
    elif modal == "plan":
        _plan_modal()

    _gallery(repo, user_id)


main()
