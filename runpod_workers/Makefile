# RunPod Serverless 워커 빌드 & 배포
#
# 필수 환경변수:
#   DOCKER_USER  — Docker Hub 유저명 (예: myname)
#
# 선택 환경변수:
#   REGISTRY     — 레지스트리 (기본 docker.io)
#   IMAGE_TAG    — 이미지 태그 (기본 latest)
#
# 사용 예시:
#   DOCKER_USER=myname make deploy-all
#   DOCKER_USER=myname IMAGE_TAG=v1.2 make deploy-llm
#   make setup-endpoints  # .env 에서 RUNPOD_API_KEY 등 읽어서 실행

REGISTRY    ?= docker.io
IMAGE_TAG   ?= latest

ifndef DOCKER_USER
$(error DOCKER_USER 가 필요합니다: DOCKER_USER=myname make ...)
endif

LLM_IMAGE   := $(REGISTRY)/$(DOCKER_USER)/mongle-llm-worker
IMAGE_IMAGE := $(REGISTRY)/$(DOCKER_USER)/mongle-image-worker

.PHONY: build-llm push-llm deploy-llm \
        build-image push-image deploy-image \
        deploy-all setup-endpoints

# ── LLM 워커 (플래너·캐릭터 공용 이미지, 엔드포인트는 분리) ───────────────────
build-llm:
	docker build --platform linux/amd64 \
	  -t $(LLM_IMAGE):$(IMAGE_TAG) \
	  -t $(LLM_IMAGE):latest \
	  ./llm

push-llm:
	docker push $(LLM_IMAGE):$(IMAGE_TAG)
	@[ "$(IMAGE_TAG)" = "latest" ] || docker push $(LLM_IMAGE):latest

deploy-llm: build-llm push-llm

# ── 이미지 생성 워커 ──────────────────────────────────────────────────────────
build-image:
	docker build --platform linux/amd64 \
	  -t $(IMAGE_IMAGE):$(IMAGE_TAG) \
	  -t $(IMAGE_IMAGE):latest \
	  ./image_gen

push-image:
	docker push $(IMAGE_IMAGE):$(IMAGE_TAG)
	@[ "$(IMAGE_TAG)" = "latest" ] || docker push $(IMAGE_IMAGE):latest

deploy-image: build-image push-image

# ── 전체 배포 ─────────────────────────────────────────────────────────────────
deploy-all: deploy-llm deploy-image

# ── RunPod 엔드포인트 최초 생성 ──────────────────────────────────────────────
setup-endpoints:
	LLM_DOCKER_IMAGE=$(LLM_IMAGE):latest \
	IMAGE_DOCKER_IMAGE=$(IMAGE_IMAGE):latest \
	uv run python setup_endpoints.py
