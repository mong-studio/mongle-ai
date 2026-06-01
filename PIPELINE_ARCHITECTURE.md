# 파이프라인 아키텍처

> 몽글마을 캐릭터 생성 파이프라인 전체 흐름 설명

---

## 전체 흐름

```
사용자가 사진 + 이름 + 페르소나 입력 (Streamlit)
        ↓
build_ports() — 모델/스토리지 초기화 (앱 시작 시 1회만)
        ↓
pipeline.run() — LangGraph 그래프 실행
```

---

## LangGraph 노드 흐름

```
[validate]
입력값 검증 (파일 형식, 크기 등)
        ↓ 병렬 실행
┌─────────────────────┬──────────────────┐
[llm_persona]          [source_upload]
GPT-4o가 페르소나 기반   원본 사진을
성격/배경/말투 텍스트     로컬 스토리지에
생성                    저장
        └──────┬────────────────┘
             [sync]
             둘 다 끝날 때까지 대기
               ↓
        [image_generator]
        LoRA 파이프라인 실행
        ① rembg — 배경 제거
        ② OpenCV Canny — 윤곽선 추출
        ③ ControlNet — 형태 고정
        ④ SDXL + LoRA — 픽셀아트 변환
               ↓
        [generated_upload]
        결과 이미지 스토리지 저장
               ↓
        [builder]
        캐릭터 최종 데이터 조립
        (이름 + 페르소나 + 이미지 URL 등)
               ↓
        Streamlit에 캐릭터 표시
```

---

## 파일별 역할

| 파일 | 역할 |
|---|---|
| `streamlit_app/app.py` | 화면 UI, 사용자 입력 받기 |
| `streamlit_app/ports_factory.py` | 모델/스토리지 초기화, LoRA 모델 캐싱 |
| `agents/character_creation/pipeline.py` | LangGraph 그래프 실행 진입점 |
| `agents/character_creation/graph.py` | 노드 연결 구조 정의 |
| `agents/character_creation/nodes/validate.py` | 입력값 검증 |
| `agents/character_creation/nodes/llm_persona.py` | GPT-4o로 페르소나 생성 |
| `agents/character_creation/nodes/source_upload.py` | 원본 사진 스토리지 업로드 |
| `agents/character_creation/nodes/image_generator.py` | 이미지 생성 노드 |
| `agents/character_creation/nodes/generated_upload.py` | 결과 이미지 스토리지 업로드 |
| `agents/character_creation/nodes/builder.py` | 캐릭터 최종 데이터 조립 |
| `adapters/character_creation/lora_image.py` | 실제 픽셀아트 변환 로직 (rembg + ControlNet + LoRA) |
| `adapters/character_creation/openai_llm.py` | GPT-4o LLM 어댑터 |
| `adapters/character_creation/local_storage.py` | 로컬 파일 스토리지 어댑터 |

---

## 이미지 변환 파이프라인 상세

`adapters/character_creation/lora_image.py`

```
원본 사진 (bytes)
    ↓
512×512 리사이즈
    ↓
rembg — 배경 제거 후 흰 배경 합성
(실패 시 원본 사용 — 배경 비율 40% 미만이면 실패로 판단)
    ↓
OpenCV Canny 엣지 추출 (low=80, high=180)
    ↓
ControlNet (diffusers/controlnet-canny-sdxl-1.0)
+ SDXL Base (stabilityai/stable-diffusion-xl-base-1.0)
+ LoRA (Hadimeeee/pixel-art-lora-sdxl)
    ↓
픽셀아트 이미지 (bytes)
```

### 추론 파라미터

| 파라미터 | 값 |
|---|---|
| `num_inference_steps` | 30 |
| `guidance_scale` | 7.5 |
| `controlnet_conditioning_scale` | 0.8 |
| `strength` | 0.6 |
| 디바이스 | MPS (Apple Silicon) / CUDA / CPU 자동 선택 |
| dtype | MPS: bfloat16 / CUDA: float16 / CPU: float32 |

---

## 환경변수

| 변수 | 설명 | 예시 |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API 키 | `sk-...` |
| `LORA_DIR` | LoRA 가중치 경로 또는 HuggingFace repo ID | `Hadimeeee/pixel-art-lora-sdxl` |
| `STORAGE_BACKEND` | 스토리지 방식 | `local` (기본값) / `s3` |
| `LLM_PROVIDER` | LLM 제공자 | `openai` (기본값) / `midm` |

---

## 실행 방법

```bash
cd /Users/hajin/Desktop/mongle-ai
streamlit run streamlit_app/app.py
```
