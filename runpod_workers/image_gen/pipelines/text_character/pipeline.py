"""
pipelines/text_character/pipeline.py — 텍스트 설명 → 픽셀아트 캐릭터 스프라이트

흐름:
  1. Qwen2-VL-7B (텍스트)  → 한글 페르소나 → 영어 시각 프롬프트
  2. SDXL + LoRA (+ LCM)   → 픽셀아트 캐릭터 생성 (흰 배경)
  3. Qwen2-VL-7B (비전)    → 생성 이미지 외형 추출 → appearance.json
  4. solid background removal → result_nobg.png

사용:
  from pipelines.text_character.pipeline import run_pipeline
  result = run_pipeline("크림색 곰이에요. 포근하고 따뜻한 친구예요")
  result["result_nobg"].save("output.png")
"""

import gc
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from pipelines.shared.background import remove_solid_background
from pipelines.shared.character_profile import from_text_appearance

CHAR_LORA_HF = "Hadimeeee/mongle-character-lora"
LCM_LORA_HF  = "latent-consistency/lcm-lora-sdxl"
# 서브프로세스 워커를 `-m pipelines.text_character...` 로 띄울 때의 작업 디렉터리.
APP_ROOT = Path(__file__).resolve().parents[2]  # runpod_workers/image_gen
QWEN2VL_ID   = "Qwen/Qwen2-VL-7B-Instruct"

STYLE_SUFFIX = (
    "monglestyle, 32-bit pixel art sprite, "
    "soft pixel shading, clean silhouette, "
    "cute face with round dot eyes and small dot nose, "
    "full body, centered, front view, pure white background"
)

NEGATIVE = (
    "realistic, photograph, 3d render, human, person, anime, scary, "
    "complex background, multiple characters, text, watermark, "
    "extra limbs, harsh black outline, low quality, blurry, deformed"
)

TRANSLATE_SYSTEM = """\
You are a visual prompt writer for a plush-to-pixel-art character generation pipeline.

Convert a Korean character description into a concise English visual prompt.

Rules:
- Focus only on visible appearance: animal type, body color, face, ears, body shape, limbs, texture, accessories.
- Personality words → visible expression only (e.g. 용감한=confident bright eyes, 사랑스러운=rosy cheeks warm smile).
- If animal type is not specified, choose a soft plush animal that fits the description.
- If color is not specified, choose one pastel color.
- Do NOT include background, scene, action, story, name, or relationship.
- Output ONLY the English visual prompt, 25-45 words."""

VLM_APPEARANCE_PROMPT = """Analyze this pixel art stuffed animal character carefully.
Return ONLY valid JSON — no markdown, no explanation.

{
  "animal_type": "single animal type, one word (e.g. bear)",
  "body_color": "main body color, specific (e.g. cream, light pink, soft lavender)",
  "secondary_colors": ["each secondary color with location, e.g. white belly patch"],
  "body_shape": "one short phrase (e.g. round squishy, chubby oval)",
  "eye_style": "describe eyes specifically (e.g. tiny black bead eyes, large round glossy black eyes)",
  "nose_mouth": "describe nose and mouth (e.g. tiny triangular stitched nose with soft smile)",
  "ear_shape": "describe ears (e.g. small round plush ears, long upright rabbit ears)",
  "texture": "one short phrase (e.g. soft fluffy, smooth velvety plush)",
  "accessories": "visible accessories or none",
  "distinctive_features": ["each notable feature as a short phrase"],
  "has_limbs": "yes or no",
  "has_face": "yes or no",
  "overall_feel": "2-3 words (e.g. soft and cuddly)"
}"""


# ══════════════════════════════════════════════════════════════
# Qwen2-VL (번역 + 외형 추출 공용)
# ══════════════════════════════════════════════════════════════

def load_qwen(allow_cpu_offload: bool = False):
    """
    allow_cpu_offload=True : VRAM 부족 시 일부 레이어를 CPU fp32로 분산
                             (SDXL 이후 2번째 로드 시 사용)
    """
    from transformers import AutoProcessor, BitsAndBytesConfig, Qwen2VLForConditionalGeneration
    if allow_cpu_offload:
        print("  Qwen2-VL 로드 중 (8bit + cpu offload)...")
        bnb = BitsAndBytesConfig(load_in_8bit=True, llm_int8_enable_fp32_cpu_offload=True)
    else:
        print("  Qwen2-VL 로드 중 (8bit)...")
        bnb = BitsAndBytesConfig(load_in_8bit=True)
    model = Qwen2VLForConditionalGeneration.from_pretrained(
        QWEN2VL_ID, quantization_config=bnb, device_map="auto"
    ).eval()
    proc  = AutoProcessor.from_pretrained(
        QWEN2VL_ID, min_pixels=256 * 28 * 28, max_pixels=512 * 28 * 28
    )
    print("  Qwen2-VL 로드 완료")
    return model, proc


def unload_qwen(model, proc):
    import torch
    try:
        from accelerate.hooks import remove_hook_from_module
        remove_hook_from_module(model, recurse=True)
    except Exception:
        pass
    model.cpu()
    del model, proc
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    print("  Qwen2-VL VRAM 해제 완료")


def _get_devices(model):
    """cpu offload 분산 시 텍스트/비전 레이어 device를 탐지"""
    import torch
    try:
        text_dev = model.model.embed_tokens.weight.device
    except Exception:
        text_dev = torch.device("cuda")
    try:
        vis_dev = next(model.visual.parameters()).device
    except Exception:
        vis_dev = torch.device("cuda")
    return text_dev, vis_dev


def _route_inputs(raw_inputs, text_dev, vis_dev):
    """텍스트 텐서 → text_dev, 비전 텐서 → vis_dev"""
    VISION_KEYS = {"pixel_values", "image_grid_thw", "video_grid_thw", "second_per_grid_ts"}
    return {
        k: (v.to(vis_dev) if k in VISION_KEYS else v.to(text_dev)) if hasattr(v, "to") else v
        for k, v in raw_inputs.items()
    }


def translate_persona(persona_ko: str, model, proc) -> str:
    """한글 페르소나 → 영어 시각 프롬프트"""
    import torch
    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM},
        {"role": "user",   "content": persona_ko},
    ]
    text   = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    text_dev, _ = _get_devices(model)
    inputs = proc(text=[text], padding=True, return_tensors="pt").to(text_dev)
    with torch.no_grad():
        out = model.generate(
            **inputs, max_new_tokens=120, do_sample=False,
            temperature=None, top_p=None,
            pad_token_id=proc.tokenizer.eos_token_id,
        )
    result = proc.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True).strip()
    del inputs, out
    gc.collect()
    torch.cuda.empty_cache()
    return result


def extract_appearance(image, model, proc) -> dict:
    """생성된 픽셀아트 이미지 → 외형 JSON"""
    import torch
    from qwen_vl_utils import process_vision_info
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text",  "text": VLM_APPEARANCE_PROMPT},
    ]}]
    text_in  = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    img_in, _ = process_vision_info(messages)

    text_dev, vis_dev = _get_devices(model)
    raw = proc(text=[text_in], images=img_in, padding=True, return_tensors="pt")
    inputs = _route_inputs(raw, text_dev, vis_dev)

    with torch.no_grad():
        gen_ids = model.generate(**inputs, max_new_tokens=500, do_sample=False)
    raw_out = proc.decode(gen_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    del inputs, gen_ids
    gc.collect()
    torch.cuda.empty_cache()
    print(f"  VLM 출력: {raw_out[:150]}")
    try:
        clean = raw_out.strip()
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", clean, re.DOTALL)
        if m:
            clean = m.group(1)
        s, e = clean.find("{"), clean.rfind("}")
        return json.loads(clean[s:e + 1])
    except Exception as ex:
        print(f"  JSON 파싱 실패: {ex} → 기본값 사용")
        return {
            "animal_type": "bear", "body_color": "cream",
            "secondary_colors": [], "body_shape": "round squishy",
            "eye_style": "small dark button eyes", "nose_mouth": "tiny stitched nose",
            "ear_shape": "small round plush ears", "texture": "soft fluffy",
            "accessories": "none", "distinctive_features": [],
            "has_limbs": "yes", "has_face": "yes", "overall_feel": "cute and soft",
        }


def _extract_appearance_subprocess(image) -> dict:
    """STEP3 외형추출을 **별도 프로세스**로 실행한다.

    Qwen2-VL 을 같은 프로세스에서 load/unload 하면 8bit+accelerate 특성상 VRAM 이
    끝까지 회수되지 않아 요청마다 누적된다. 자식 프로세스로 분리하면 종료 시 OS 가
    VRAM 을 전량 회수하므로 누수가 0 이 된다. (피드 vlm_worker 와 동일 패턴)
    """
    with tempfile.TemporaryDirectory(prefix="appearance_") as temp_dir:
        img_path = Path(temp_dir) / "image.png"
        image.save(img_path, format="PNG")
        proc = subprocess.run(
            [sys.executable, "-m", "pipelines.text_character.appearance_worker", str(img_path)],
            cwd=str(APP_ROOT),
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            check=False,
        )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            f"appearance extraction subprocess failed (exit={proc.returncode})"
        )
    # 워커는 stdout 마지막 줄에 외형 JSON 을 출력한다(앞선 줄은 진단 로그).
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ══════════════════════════════════════════════════════════════
# SDXL 파이프라인 (txt2img)
# ══════════════════════════════════════════════════════════════

def load_sdxl_pipeline(lora_scale: float = 0.9, lcm: bool = True):
    import torch
    from diffusers import StableDiffusionXLPipeline
    print("  SDXL 로드 중...")
    pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    if lcm:
        from diffusers import LCMScheduler
        print("  LCM-LoRA + 픽셀아트 LoRA 로드 중...")
        pipe.load_lora_weights(LCM_LORA_HF,  adapter_name="lcm")
        pipe.load_lora_weights(CHAR_LORA_HF, adapter_name="pixel_art")
        pipe.set_adapters(["lcm", "pixel_art"], adapter_weights=[1.0, lora_scale])
        pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    else:
        print("  픽셀아트 LoRA 로드 중...")
        pipe.load_lora_weights(CHAR_LORA_HF)
        pipe.fuse_lora(lora_scale=lora_scale)
        pipe.unload_lora_weights()
    pipe.to("cuda")
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()  # VAE decode 피크 OOM 방지(타일 디코드)
    print("  SDXL 로드 완료")
    return pipe


def unload_sdxl_pipeline(pipe):
    import torch
    try:
        pipe.to("cpu")  # VRAM에서 먼저 내린 후 삭제
    except Exception:
        pass
    del pipe
    gc.collect()
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    gc.collect()
    torch.cuda.empty_cache()
    print("  SDXL VRAM 해제 완료")


def generate_character(pipe, prompt: str, steps: int = 8,
                       guidance: float = 1.5, seed: int = 42):
    import torch
    print(f"  생성 중 (steps={steps}, guidance={guidance})...")
    return pipe(
        prompt=prompt,
        negative_prompt=NEGATIVE,
        num_inference_steps=steps,
        guidance_scale=guidance,
        height=1024, width=1024,
        generator=torch.Generator("cuda").manual_seed(seed),
    ).images[0]


# ══════════════════════════════════════════════════════════════
# 메인 API
# ══════════════════════════════════════════════════════════════

def run_pipeline(
    persona_ko: str,
    prompt_en: str | None = None,
    lcm: bool = True,
    lora_scale: float = 0.9,
    steps: int = 8,
    seed: int = 42,
    out_dir: str = None,
) -> dict:
    """
    한글 캐릭터 설명 → 픽셀아트 캐릭터 스프라이트 생성

    Args:
        persona_ko  : 한글 캐릭터 설명 (예: "크림색 곰이에요. 포근하고 따뜻해요")
        lcm         : LCM 빠른 생성 사용 (기본 True, 8스텝)
        lora_scale  : 픽셀아트 LoRA 강도 (기본 0.9)
        steps       : 추론 스텝 수 (LCM=8, 일반=25)
        seed        : 랜덤 시드
        out_dir     : 중간 파일 저장 경로 (None이면 저장 안 함)

    Returns:
        {
          "result"      : PIL Image (흰 배경),
          "result_nobg" : PIL Image (RGBA, 투명 배경),
          "appearance"  : dict (VLM 추출 외형 정보),
          "prompt"      : str (생성에 사용된 영어 프롬프트),
          "persona_en"  : str (번역된 영어 페르소나),
        }
    """
    save = out_dir is not None
    if save:
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    # STEP 1: 한글 페르소나 → 영어 프롬프트
    # 상류(에이전트 LLM)에서 이미 영어 태그(appearance_en)를 만들어 prompt_en 으로 넘기면
    # 무거운 Qwen2-VL 번역을 건너뛴다 → 이미지 GPU VLM 로드/메모리 누수 제거. 비면 기존 번역.
    if prompt_en:
        print("[1] 페르소나 번역 생략 (이미 영어 prompt_en 수신)")
        persona_en = prompt_en
    else:
        print("[1] 페르소나 번역...")
        qwen_model, qwen_proc = load_qwen()
        persona_en = translate_persona(persona_ko, qwen_model, qwen_proc)
        print(f"  번역 결과: {persona_en}")
        unload_qwen(qwen_model, qwen_proc)

    prompt = f"{persona_en}, {STYLE_SUFFIX}"
    if save:
        (Path(out_dir) / "prompt.txt").write_text(prompt, encoding="utf-8")
    print(f"  최종 프롬프트: {prompt[:100]}...")

    # STEP 2: SDXL txt2img → 픽셀아트 캐릭터
    print("[2] 캐릭터 생성...")
    pipe   = load_sdxl_pipeline(lora_scale=lora_scale, lcm=lcm)
    result = generate_character(pipe, prompt, steps, 1.5 if lcm else 7.5, seed)
    unload_sdxl_pipeline(pipe)

    if save:
        result.save(Path(out_dir) / "result.png")

    # STEP 3: VLM 외형 추출 — 별도 프로세스로 실행해 종료 시 VLM VRAM 을 전량 회수(누수 방지)
    print("[3] 외형 추출...")
    appearance_raw = _extract_appearance_subprocess(result)
    appearance = from_text_appearance(appearance_raw)

    if save:
        (Path(out_dir) / "appearance_raw.json").write_text(
            json.dumps(appearance_raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (Path(out_dir) / "appearance.json").write_text(
            json.dumps(appearance, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # STEP 4: 배경 제거
    print("[4] 배경 제거 (누끼)...")
    result_nobg = remove_solid_background(result)
    if save:
        result_nobg.save(Path(out_dir) / "result_nobg.png")

    print("완료!")
    return {
        "result":     result,
        "result_nobg": result_nobg,
        "appearance": appearance,
        "appearance_raw": appearance_raw,
        "prompt":     prompt,
        "persona_en": persona_en,
    }
