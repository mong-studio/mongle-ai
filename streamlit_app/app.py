from __future__ import annotations

import asyncio
import sys
import traceback
import warnings
from datetime import date
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
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=DotGothic16&display=swap');

:root {
  --forest-deep: #15200c;
  --forest-mid:  #2d3a1f;
  --forest-soft: #4a5d36;
  --parchment:        #e8d4a8;
  --parchment-light:  #f5e5c0;
  --parchment-dark:   #c4a16e;
  --wood-dark: #3d2818;
  --wood-mid:  #5a3a1f;
  --wood-light: #8b6f3a;
  --gold: #f4d27a;
  --ink:  #2d1810;
  --bone: #f4ead6;
  --shadow: rgba(0, 0, 0, 0.55);
}

* { image-rendering: pixelated; }

html, body, [class*="st-"], .stMarkdown, .stTextInput input, .stTextArea textarea {
  font-family: 'DotGothic16', monospace !important;
}

.stApp {
  background:
    radial-gradient(ellipse at 50% -10%, var(--forest-mid) 0%, var(--forest-deep) 60%, #0a1106 100%);
}

#MainMenu, footer { visibility: hidden; height: 0; }
header[data-testid="stHeader"] { background: transparent; height: 0; }
div[data-testid="stToolbar"], .stDeployButton { display: none !important; }

.block-container {
  padding-top: 0.5rem !important;
  padding-bottom: 2rem !important;
  max-width: 1320px !important;
}

/* ───── Top bar ───── */
.pixel-topbar {
  background: #0a0a0a;
  border-top: 4px solid var(--wood-dark);
  border-bottom: 4px solid var(--wood-dark);
  padding: 10px 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: 'Press Start 2P', monospace;
  color: var(--bone);
  font-size: 10px;
  letter-spacing: 2px;
  margin-bottom: 18px;
  box-shadow: 0 4px 0 rgba(0, 0, 0, 0.5);
}
.pixel-topbar .menu span {
  margin-right: 28px;
  color: var(--bone);
  opacity: 0.85;
  cursor: pointer;
}
.pixel-topbar .menu span:hover { color: var(--gold); opacity: 1; }
.pixel-topbar .brand {
  font-size: 13px;
  color: var(--gold);
  text-shadow: 2px 2px 0 #000;
}
.pixel-topbar .session { color: var(--parchment-dark); font-size: 10px; }

/* ───── Side panels ───── */
.side-panel {
  background: #1a1a1a;
  border: 4px solid var(--wood-dark);
  outline: 2px solid #000;
  padding: 14px 16px;
  color: var(--bone);
  box-shadow:
    inset 0 0 0 2px var(--wood-mid),
    6px 6px 0 var(--shadow);
}
.side-panel .label {
  font-family: 'Press Start 2P', monospace;
  font-size: 8px;
  letter-spacing: 2px;
  color: var(--parchment-dark);
  margin-bottom: 4px;
}
.timer-display {
  font-family: 'Press Start 2P', monospace;
  font-size: 40px;
  color: var(--gold);
  text-shadow: 3px 3px 0 #000;
  letter-spacing: 2px;
  text-align: center;
  padding: 6px 0;
}
.timer-meta {
  font-family: 'Press Start 2P', monospace;
  font-size: 7px;
  color: var(--bone);
  text-align: center;
  margin-bottom: 10px;
  letter-spacing: 2px;
  opacity: 0.7;
}
.pixel-row { display: flex; gap: 8px; }
.pixel-btn {
  flex: 1;
  background: var(--parchment);
  color: var(--ink);
  border: 3px solid var(--wood-dark);
  font-family: 'Press Start 2P', monospace;
  font-size: 8px;
  letter-spacing: 1px;
  padding: 6px 10px;
  text-align: center;
  box-shadow: 3px 3px 0 var(--wood-mid);
  user-select: none;
}
.pixel-btn.dark { background: var(--wood-dark); color: var(--gold); }

.date-display {
  font-family: 'Press Start 2P', monospace;
  font-size: 14px;
  color: var(--gold);
  text-shadow: 2px 2px 0 #000;
  letter-spacing: 2px;
  text-align: right;
}
.date-day {
  font-family: 'Press Start 2P', monospace;
  font-size: 22px;
  color: var(--bone);
  text-shadow: 2px 2px 0 #000;
  text-align: right;
  margin: 4px 0 8px;
}
.date-hint {
  border-top: 1px dashed var(--wood-mid);
  padding-top: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--parchment-dark);
  text-align: right;
}
.date-hint .key {
  font-family: 'Press Start 2P', monospace;
  font-size: 8px;
  color: var(--bone);
  letter-spacing: 1px;
}

/* ───── Map frame ───── */
.map-wrap {
  position: relative;
  border: 6px solid var(--wood-dark);
  outline: 3px solid #000;
  box-shadow:
    inset 0 0 0 3px var(--wood-light),
    10px 10px 0 var(--shadow);
  background: #5e8a3e;
  overflow: hidden;
  margin-top: 4px;
  aspect-ratio: 16 / 9;
}
.map-wrap::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: repeating-linear-gradient(
    0deg,
    rgba(0, 0, 0, 0.06) 0px,
    rgba(0, 0, 0, 0.06) 2px,
    transparent 2px,
    transparent 4px
  );
}

/* Pixel village grid */
.village-grid {
  display: grid;
  width: 100%;
  height: 100%;
  gap: 0;
  background: #5e8a3e;
}
.tile {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}
.tile.grass    { background: #5e8a3e; box-shadow: inset 0 0 0 1px rgba(74, 110, 48, 0.6); }
.tile.grass-d  { background: #4a6e30; }
.tile.tree     { background: #2a4a18; box-shadow: inset 0 0 0 2px #1a3008; }
.tile.tree::after {
  content: "";
  position: absolute;
  inset: 18%;
  background: #3d6520;
  box-shadow:
    inset -2px -2px 0 #1a3008,
    inset 2px 2px 0 #5d8a3a;
}
.tile.path     { background: #c19762; box-shadow: inset 0 0 0 1px #a87a4a; }
.tile.path-d   { background: #a87a4a; }
.tile.water    { background: #4a7ba8; box-shadow: inset 0 0 0 1px #3d6588; }
.tile.water::after {
  content: "≈";
  font-family: 'Press Start 2P', monospace;
  font-size: 0.55em;
  color: #6a99c4;
}
.tile.roof     { background: #a44a32; box-shadow: inset -2px -2px 0 #6e2818, inset 2px 2px 0 #c46a4a; }
.tile.wall     { background: #d4a86a; box-shadow: inset -2px -2px 0 #8b6f3a, inset 2px 2px 0 #f0c87a; }
.tile.wall::after {
  content: "";
  position: absolute;
  inset: 30% 35%;
  background: #3d2818;
}
.tile.chief-roof { background: #6a3a1f; box-shadow: inset -2px -2px 0 #3d2818, inset 2px 2px 0 #8b5a2f; }
.tile.chief-wall { background: #b88a4a; box-shadow: inset -2px -2px 0 #6a4a2a, inset 2px 2px 0 #d4a86a; }
.tile.chief-wall::after {
  content: "🏠";
  font-size: 0.7em;
}
.tile.flower {
  background: #5e8a3e;
}
.tile.flower::after {
  content: "";
  width: 30%; height: 30%;
  background: #f4d27a;
  box-shadow: 0 0 0 2px #c4a02a;
}
.tile.bush {
  background: #5e8a3e;
}
.tile.bush::after {
  content: "";
  width: 50%; height: 50%;
  background: #3d6520;
  border-radius: 2px;
}

/* ───── Chief CTA ───── */
.chief-cta-hint {
  font-family: 'Press Start 2P', monospace;
  font-size: 9px;
  letter-spacing: 2px;
  color: var(--gold);
  text-align: center;
  margin: 22px 0 6px;
  text-shadow: 2px 2px 0 #000;
  opacity: 0.9;
}
.chief-cta-hint .arrow {
  display: inline-block;
  margin: 0 10px;
  animation: bob 1.3s ease-in-out infinite;
}
@keyframes bob {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(4px); }
}

/* ───── Chief dialog ───── */
.chief-dialog {
  position: relative;
  margin-top: 18px;
  background: var(--parchment);
  border: 4px solid var(--wood-dark);
  outline: 2px solid #000;
  padding: 16px 20px 18px;
  box-shadow:
    inset 0 0 0 3px var(--parchment-dark),
    8px 8px 0 var(--shadow);
}
.chief-dialog::before {
  content: "▲";
  position: absolute;
  top: -18px;
  left: 50%;
  transform: translateX(-50%);
  color: var(--wood-dark);
  font-size: 20px;
  line-height: 1;
}

/* ───── Step tag (TODO multi-step header) ───── */
.step-tag {
  font-family: 'Press Start 2P', monospace;
  font-size: 9px;
  letter-spacing: 2px;
  color: var(--wood-dark);
  text-align: center;
  margin-bottom: 4px;
}
.step-tag .step {
  background: var(--wood-dark);
  color: var(--gold);
  padding: 3px 8px;
  margin-right: 8px;
}

/* ───── Candidate row (TODO step 2) ───── */
.cand-card {
  background: var(--parchment-light);
  border: 3px solid var(--wood-dark);
  padding: 8px 12px;
  margin: 6px 0;
  box-shadow: 3px 3px 0 var(--shadow);
}

/* ───── Plan chat ───── */
.plan-chat-wrap {
  background: var(--parchment-light);
  border: 3px solid var(--wood-dark);
  padding: 12px 14px;
  max-height: 280px;
  overflow-y: auto;
  margin-bottom: 12px;
  box-shadow: inset 2px 2px 0 rgba(0, 0, 0, 0.1);
}
.plan-chat-row {
  display: flex;
  margin: 6px 0;
}
.plan-chat-row.user   { justify-content: flex-end; }
.plan-chat-row.chief  { justify-content: flex-start; }
.plan-chat-bubble {
  max-width: 78%;
  padding: 8px 12px;
  font-family: 'DotGothic16', monospace;
  font-size: 14px;
  line-height: 1.5;
  border: 2px solid var(--wood-dark);
}
.plan-chat-row.user  .plan-chat-bubble {
  background: var(--wood-dark);
  color: var(--gold);
}
.plan-chat-row.chief .plan-chat-bubble {
  background: var(--parchment);
  color: var(--ink);
}
.plan-chat-label {
  font-family: 'Press Start 2P', monospace;
  font-size: 7px;
  color: var(--wood-dark);
  letter-spacing: 1px;
  margin-bottom: 2px;
}
.plan-empty {
  font-family: 'DotGothic16', monospace;
  font-size: 14px;
  color: var(--wood-mid);
  text-align: center;
  padding: 24px 0;
  opacity: 0.7;
}
.chief-row {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 18px;
  align-items: center;
}
.chief-avatar {
  width: 76px;
  height: 76px;
  background: linear-gradient(180deg, #d4a86a 0%, #8b6f3a 100%);
  border: 3px solid var(--wood-dark);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 42px;
  box-shadow: 3px 3px 0 var(--shadow);
}
.chief-name {
  font-family: 'Press Start 2P', monospace;
  font-size: 9px;
  color: var(--wood-dark);
  margin-top: 6px;
  text-align: center;
  letter-spacing: 1px;
}
.chief-speech {
  font-size: 18px;
  color: var(--ink);
  line-height: 1.6;
}
.chief-speech::before { content: "\\201C "; color: var(--wood-mid); }
.chief-speech::after  { content: " \\201D"; color: var(--wood-mid); }

/* ───── Buttons ───── */
.stButton > button {
  font-family: 'DotGothic16', monospace !important;
  background: var(--parchment-light) !important;
  color: var(--ink) !important;
  border: 3px solid var(--wood-dark) !important;
  border-radius: 0 !important;
  box-shadow: 4px 4px 0 var(--wood-mid) !important;
  padding: 10px 18px !important;
  font-size: 15px !important;
  font-weight: normal !important;
  letter-spacing: 1px !important;
  transition: none !important;
}
.stButton > button:hover {
  background: var(--gold) !important;
  color: var(--ink) !important;
  border-color: var(--wood-dark) !important;
  transform: translate(2px, 2px);
  box-shadow: 2px 2px 0 var(--wood-mid) !important;
}
.stButton > button:active {
  transform: translate(4px, 4px);
  box-shadow: none !important;
}
.stButton > button[kind="primary"] {
  background: var(--wood-dark) !important;
  color: var(--gold) !important;
}
.stButton > button[kind="primary"]:hover {
  background: var(--wood-mid) !important;
  color: var(--bone) !important;
}

/* ───── Inputs ───── */
.stTextInput input,
.stTextArea textarea {
  background: var(--parchment-light) !important;
  color: var(--ink) !important;
  border: 3px solid var(--wood-dark) !important;
  border-radius: 0 !important;
  font-family: 'DotGothic16', monospace !important;
  font-size: 15px !important;
  box-shadow: inset 2px 2px 0 rgba(0, 0, 0, 0.12) !important;
}
.stMultiSelect div[data-baseweb="select"] > div {
  background: var(--parchment-light) !important;
  border: 3px solid var(--wood-dark) !important;
  border-radius: 0 !important;
  font-family: 'DotGothic16', monospace !important;
}
.stTextInput label,
.stTextArea label,
.stMultiSelect label,
.stFileUploader label,
.stCheckbox label > div {
  font-family: 'Press Start 2P', monospace !important;
  font-size: 9px !important;
  color: var(--wood-dark) !important;
  letter-spacing: 1px !important;
}
.stMultiSelect [data-baseweb="tag"] {
  background: var(--wood-dark) !important;
  color: var(--gold) !important;
  border-radius: 0 !important;
  border: 2px solid var(--ink) !important;
  font-family: 'DotGothic16', monospace !important;
}
.stMultiSelect [data-baseweb="tag"] span { color: var(--gold) !important; }
.stMultiSelect [data-baseweb="tag"] svg { fill: var(--gold) !important; }

.stFileUploader section {
  background-color: var(--parchment-light) !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text x='50' y='70' font-family='monospace' font-weight='900' font-size='72' text-anchor='middle' fill='rgba(61,40,24,0.28)'>%2B</text></svg>") !important;
  background-repeat: no-repeat !important;
  background-position: center 30% !important;
  background-size: 64px 64px !important;
  border: 3px dashed var(--wood-dark) !important;
  border-radius: 0 !important;
  color: var(--ink) !important;
  min-height: 130px !important;
}
.stFileUploader section * { color: var(--ink) !important; }

/* Preview card under uploader */
.preview-frame {
  display: inline-block;
  margin-top: 10px;
  padding: 6px;
  background: var(--parchment);
  border: 3px solid var(--wood-dark);
  box-shadow: 4px 4px 0 var(--shadow);
}
.preview-frame img {
  display: block;
  width: 140px;
  height: 140px;
  object-fit: cover;
  image-rendering: pixelated;
}
.preview-caption {
  font-family: 'Press Start 2P', monospace;
  font-size: 8px;
  letter-spacing: 1px;
  color: var(--wood-dark);
  text-align: center;
  margin-top: 6px;
}

/* ───── Dialog (modal) ───── */
div[role="dialog"] {
  background: var(--parchment) !important;
  border: 4px solid var(--wood-dark) !important;
  border-radius: 0 !important;
  box-shadow:
    inset 0 0 0 3px var(--parchment-dark),
    12px 12px 0 var(--shadow) !important;
  color: var(--ink) !important;
}
div[role="dialog"] h1,
div[role="dialog"] h2,
div[role="dialog"] h3 {
  font-family: 'Press Start 2P', monospace !important;
  font-size: 12px !important;
  color: var(--wood-dark) !important;
  text-align: center !important;
  border-bottom: 2px dashed var(--wood-mid) !important;
  padding-bottom: 10px !important;
  letter-spacing: 2px !important;
  margin-bottom: 8px !important;
}
div[role="dialog"] p, div[role="dialog"] span { color: var(--ink); }
div[role="dialog"] button[aria-label="Close"] { color: var(--wood-dark) !important; }

.modal-sub {
  text-align: center;
  font-size: 14px;
  color: var(--wood-dark);
  margin-bottom: 14px;
}

/* ───── Sidebar ───── */
section[data-testid="stSidebar"] {
  background: #1a1a1a !important;
  border-right: 4px solid var(--wood-dark) !important;
}
section[data-testid="stSidebar"] * { color: var(--bone) !important; }
section[data-testid="stSidebar"] .stMetric label,
section[data-testid="stSidebar"] [data-testid="stMetricValue"] {
  color: var(--gold) !important;
}
.sidebar-title {
  font-family: 'Press Start 2P', monospace;
  font-size: 10px;
  color: var(--gold);
  letter-spacing: 2px;
  padding: 4px 0 12px;
  border-bottom: 2px dashed var(--wood-mid);
  margin-bottom: 12px;
}

/* ───── Gallery ───── */
.gallery-title {
  font-family: 'Press Start 2P', monospace;
  font-size: 11px;
  color: var(--gold);
  letter-spacing: 2px;
  border-top: 2px dashed var(--wood-mid);
  padding-top: 16px;
  margin-top: 24px;
  text-shadow: 2px 2px 0 #000;
}
.char-card {
  background: var(--parchment);
  border: 3px solid var(--wood-dark);
  padding: 8px;
  color: var(--ink);
  margin-top: 10px;
  box-shadow: 4px 4px 0 var(--shadow);
}
.char-name {
  font-family: 'Press Start 2P', monospace;
  font-size: 9px;
  color: var(--wood-dark);
  letter-spacing: 1px;
  margin-top: 6px;
}
.char-meta { font-size: 13px; color: var(--ink); }

/* ───── Alerts ───── */
.stAlert {
  border-radius: 0 !important;
  border: 3px solid var(--wood-dark) !important;
  font-family: 'DotGothic16', monospace !important;
}
</style>
"""


def _inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


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
        <div class="side-panel">
          <div class="label">&lt; FOCUS TIME &gt;</div>
          <div class="timer-display">25:00</div>
          <div class="timer-meta">0 CYCLES</div>
          <div class="pixel-row">
            <div class="pixel-btn dark">▶ START</div>
            <div class="pixel-btn">RESET</div>
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
        <div class="side-panel">
          <div class="date-display">{date_str}</div>
          <div class="date-day">{day_short}</div>
          <div class="date-hint">
            오늘의 할 일을 추가해보세요<br/>
            <span class="key">PRESS &lt;+&gt; TO ADD</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# Pixel village layout — each character is one tile.
# g=grass G=darker-grass t=tree p=path P=darker-path w=water
# r=house-roof R=chief-roof W=house-wall C=chief-wall f=flower b=bush
_VILLAGE_MAP = """\
wwttgggggtttgggggggGGtgggggGGGgg
wwgggGGggttggrrrgggggggttgggggGg
wwggtggGggggWWWggppppppptgggrrgg
wwgggggggggggggggppGGGGGppgggWWg
GggttggggrrrggggppGGGGGppggggggg
ggggggGggWWWgggpPGGRRGGppgggttgg
ggggttgggggggppPGGCCGGGppgggggGg
GGgggggGgggggpPpgggggggppGgggggg
ggffgggggrrrgppgggttgggppgggrrgg
gggggttggWWWgppgggGggggppggrWWrg
gggggggggggggppgGgggggppgggWWggg
ggbbgggttggggppgggggGppPpggggggt
GggggbbggggggppppPpppppgggttgggg
gggGgggggGggggggggggggggGgggGggg
"""


# Map character → CSS class for the village grid.
_TILE_CLASSES = {
    "g": "grass",
    "G": "grass-d",
    "t": "tree",
    "p": "path",
    "P": "path-d",
    "w": "water",
    "r": "roof",
    "R": "chief-roof",
    "W": "wall",
    "C": "chief-wall",
    "f": "flower",
    "b": "bush",
}


def _village_map() -> None:
    rows = _VILLAGE_MAP.strip().split("\n")
    cols = max(len(r) for r in rows)
    cells: list[str] = []
    for row in rows:
        for ch in row:
            css = _TILE_CLASSES.get(ch, "grass")
            cells.append(f'<div class="tile {css}"></div>')
    st.markdown(
        f"""
        <div class="map-wrap">
          <div class="village-grid"
               style="grid-template-columns: repeat({cols}, 1fr);
                      grid-template-rows: repeat({len(rows)}, 1fr);">
            {"".join(cells)}
          </div>
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
        st.session_state["todo_step"] = 1
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
    step = st.session_state.get("todo_step", 1)
    if step == 1:
        _todo_step_1()
    else:
        _todo_step_2()


def _todo_step_1() -> None:
    st.markdown(
        '<div class="step-tag"><span class="step">STEP 1/2</span>오늘의 할 일 정리</div>',
        unsafe_allow_html=True,
    )
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

    cancel_col, ok_col = st.columns([1, 1])
    if cancel_col.button("취소", key="todo_cancel_1", width="stretch"):
        _reset_todo_state()
        st.session_state["modal"] = None
        st.rerun()
    if ok_col.button(
        "정리하기 →",
        key="todo_submit_1",
        type="primary",
        width="stretch",
        disabled=not text.strip(),
    ):
        st.session_state["todo_text"] = text
        st.session_state["todo_candidates"] = _stub_split_tasks(text)
        st.session_state["todo_step"] = 2
        st.rerun()


def _todo_step_2() -> None:
    st.markdown(
        '<div class="step-tag"><span class="step">STEP 2/2</span>오늘의 할 일</div>',
        unsafe_allow_html=True,
    )
    candidates: list[dict] = st.session_state.get("todo_candidates", [])

    if not candidates:
        st.warning("정리된 할 일이 없습니다. 다시 적어주세요.")
    else:
        delete_index: int | None = None
        for i, cand in enumerate(candidates):
            with st.container():
                st.markdown('<div class="cand-card">', unsafe_allow_html=True)
                cols = st.columns([0.6, 5.5, 0.9])
                with cols[0]:
                    cand["checked"] = st.checkbox(
                        "선택",
                        value=cand.get("checked", True),
                        key=f"cand_check_{i}",
                        label_visibility="collapsed",
                    )
                with cols[1]:
                    cand["title"] = st.text_input(
                        "할 일 제목",
                        value=cand["title"],
                        key=f"cand_title_{i}",
                        label_visibility="collapsed",
                    )
                with cols[2]:
                    if st.button("✕", key=f"cand_del_{i}", width="stretch"):
                        delete_index = i
                st.markdown("</div>", unsafe_allow_html=True)
        if delete_index is not None:
            candidates.pop(delete_index)
            st.session_state["todo_candidates"] = candidates
            st.rerun()

    confirmed = [c for c in candidates if c.get("checked") and c.get("title", "").strip()]
    back_col, ok_col = st.columns([1, 1])
    if back_col.button("← 다시 적기", key="todo_back", width="stretch"):
        st.session_state["todo_step"] = 1
        st.rerun()
    if ok_col.button(
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
    for key in ("todo_text", "todo_candidates", "todo_step"):
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

    cols = st.columns([1, 4, 1])
    with cols[0]:
        _timer_panel()
    with cols[1]:
        _village_map()
    with cols[2]:
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
