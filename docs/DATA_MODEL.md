# DATA_MODEL.md

> **몽글마을 (Monggeul Village) — 데이터베이스 스키마 정의서**

---

## 0. 개요

본 문서는 몽글마을 서비스의 데이터베이스 스키마를 정의한다. `mongle-server`(Django 5.2)의 실제 모델 정의(`apps/*/models.py`)를 기준으로 도메인별로 그룹화하여 기술하며, 요구사항정의서(v1.2)와의 차이/논의 필요 사항을 마지막 섹션에 정리한다.

> **기준**: 본 문서는 Django 모델을 as-built 로 반영한 것이다. Django auth/admin 내부 테이블(`auth_*`, `django_*`) 및 `users`의 PermissionsMixin 컬럼(`is_superuser`, `last_login`, `groups`, `user_permissions`)은 도메인 외이므로 생략한다.

### 도메인 그룹

| 도메인                   | 테이블                                                              |
| ------------------------ | ------------------------------------------------------------------- |
| **회원 / 인증**          | `users`, `social_accounts`, `refresh_tokens`                        |
| **캐릭터**               | `source_images`, `character_generation_jobs`, `characters`          |
| **TODO / 일정 / 퀘스트** | `todos`, `quests`, `schedules`, `tags`                              |
| **피드 (SNS)**           | `posts`, `comments`, `replies`                                      |
| **회고**                 | `reflections`                                                       |
| **토큰 / 운영**          | `token_transactions`, `notifications`, `img_gen_logs`               |

### 공통 규칙

- **PK 정책**
  - 사용자 식별/도메인 엔티티(사용자, 캐릭터, TODO, 퀘스트, 일정, 피드 등): `VARCHAR(36)` UUID, `DEFAULT (UUID())`
  - 부수/내부 관리 테이블(소셜 계정, 리프레시 토큰, 이미지 생성 로그, 태그): `INT AUTO_INCREMENT`
- **타임스탬프**: `created_at DATETIME DEFAULT CURRENT_TIMESTAMP`, 수정 가능한 엔티티는 `updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP` 권장
- **불리언**: `TINYINT(1)` 사용 (MySQL convention)
- **외래키 삭제 정책**: 별도 명시 없는 한 `ON DELETE RESTRICT` 기본
- **사용자 탈퇴 시 데이터 보존 정책**: 사용자가 탈퇴해도 생성한 콘텐츠(`posts`, `comments` 등)는 **보존**한다. 탈퇴 처리는 `users.is_active = 0` 로 soft delete 하되, 작성자 식별이 필요한 참조 FK는 `ON DELETE SET NULL` 또는 "탈퇴한 사용자" 표시 처리 (REQ-AUTH-006 확정 사항)

---

## 1. 회원 / 인증

### 1.1 `users` — 사용자 계정

| 컬럼            | 타입         | 제약             | 기본값              | 설명                                                                        |
| --------------- | ------------ | ---------------- | ------------------- | --------------------------------------------------------------------------- |
| `user_id`         | VARCHAR(36)  | **PK**, NOT NULL | `(UUID())`          | 사용자 고유 식별자 (Django `UUIDField`)                                       |
| `email`           | VARCHAR(254) | UNIQUE           |                     | 로그인 이메일 (`USERNAME_FIELD`, RFC 5321 형식 검증)                          |
| `password`        | VARCHAR(128) |                  |                     | 해시된 비밀번호 (Django `AbstractBaseUser`). 소셜 전용 사용자는 unusable 해시 |
| `user_name`       | VARCHAR(8)   |                  |                     | 닉네임 (한글/영문/숫자, 2~8자, 중복 허용)                                     |
| `job`             | VARCHAR(20)  | blank 허용       | `''`                | 직업 (선택 입력)                                                              |
| `birth`           | DATE         | NOT NULL         |                     | 생년월일                                                                      |
| `token_balance`   | INT          |                  | `5`                 | 보유 토큰(사과) 잔액                                                          |
| `is_active`       | TINYINT(1)   |                  | `1`                 | 활성 계정 여부 (탈퇴 시 0)                                                    |
| `is_aiconsent`    | TINYINT(1)   |                  | `0`                 | AI 학습 데이터 활용 동의 여부 (REQ-PRIV-001)                                  |
| `is_staff`        | TINYINT(1)   |                  | `0`                 | Django admin 접근 권한                                                        |
| `login_type`      | VARCHAR(10)  | ENUM            | `email`             | 로그인 수단 (`email`/`kakao`/`google`/`naver`)                               |
| `personalization` | JSON         |                  | `{}`                | 사용자 개인화 설정 (Django `JSONField`)                                       |
| `created_at`      | DATETIME     |                  | `CURRENT_TIMESTAMP` | 가입일시 (`auto_now_add`)                                                     |
| `updated_at`      | DATETIME     |                  | `CURRENT_TIMESTAMP` | 마지막 수정일시 (`auto_now`)                                                  |

- Django `AbstractBaseUser` + `PermissionsMixin` 기반 커스텀 유저. `USERNAME_FIELD = email`, `REQUIRED_FIELDS = []`
- PermissionsMixin 컬럼(`is_superuser`, `last_login` 등)은 도메인 외로 본 표에서 생략
- 관련 요구사항: REQ-AUTH-001 / 002 / 005 / 006

### 1.2 `social_accounts` — 소셜 로그인 연동

| 컬럼                | 타입         | 제약                     | 기본값              | 설명                     |
| ------------------- | ------------ | ------------------------ | ------------------- | ------------------------ |
| `social_account_id` | INT          | **PK**, AUTO_INCREMENT   |                     |                          |
| `user_id`           | VARCHAR(36)  | **FK** → `users.user_id` |                     |                          |
| `provider`          | VARCHAR(20)  |                          |                     | 소셜 플랫폼 (`kakao` 등) |
| `provider_id`       | VARCHAR(255) | UNIQUE                   |                     | 플랫폼 사용자 식별자     |
| `created_at`        | DATETIME     |                          | `CURRENT_TIMESTAMP` | 연동일시                 |

- 관계: `users` 1 : 1 `social_accounts` (현재 ERD 기준. 향후 멀티 플랫폼 확장 시 1:N 검토)
- 관련 요구사항: REQ-AUTH-003

### 1.3 `refresh_tokens` — 자동 로그인 토큰

| 컬럼               | 타입         | 제약                     | 기본값              | 설명                 |
| ------------------ | ------------ | ------------------------ | ------------------- | -------------------- |
| `refresh_token_id` | INT          | **PK**, AUTO_INCREMENT             |                     |                                  |
| `user_id`          | VARCHAR(36)  | **FK** → `users.user_id`, CASCADE  |                     |                                  |
| `token_hash`       | VARCHAR(255) | UNIQUE                             |                     | 해시된 리프레시 토큰             |
| `device_info`      | VARCHAR(255) |                                    |                     | 기기 식별 정보                   |
| `expires_at`       | DATETIME     |                                    |                     | 만료일시 (2주)                   |
| `persistent`       | TINYINT(1)   |                                    | `1`                 | 자동 로그인 유지 여부            |
| `created_at`       | DATETIME     |                                    | `CURRENT_TIMESTAMP` |                                  |

- 관계: `users` 1 : N `refresh_tokens` (`ON DELETE CASCADE`)
- 관련 요구사항: REQ-AUTH-002 [자동 로그인]
- 비밀번호 변경/로그아웃/2주 미접속 시 무효화 처리 필요

---

## 2. 캐릭터

> 캐릭터 생성은 **비동기 Job 방식**이다: 원본 이미지 업로드(`source_images`) → 생성 Job 제출/폴링(`character_generation_jobs`) → 확정 등록(`characters`). (`character-async-appearance` 참조)

### 2.1 `source_images` — 업로드 원본 이미지 (presigned)

| 컬럼            | 타입         | 제약                              | 기본값              | 설명                                                       |
| --------------- | ------------ | --------------------------------- | ------------------- | ---------------------------------------------------------- |
| `source_img_id` | VARCHAR(36)  | **PK**, NOT NULL                  | `(UUID())`          |                                                            |
| `user_id`       | VARCHAR(36)  | **FK** → `users.user_id`, CASCADE |                     | 업로더                                                     |
| `object_key`    | VARCHAR(500) |                                   |                     | S3 object key                                              |
| `content_type`  | VARCHAR(50)  |                                   |                     | MIME 타입                                                  |
| `status`        | VARCHAR(20)  | ENUM                              | `PENDING_UPLOAD`    | `PENDING_UPLOAD`/`UPLOAD_COMPLETED`/`UPLOAD_EXPIRED`       |
| `expires_at`    | DATETIME     |                                   |                     | presigned URL 만료일시                                     |
| `created_at`    | DATETIME     |                                   | `CURRENT_TIMESTAMP` |                                                            |

- 관계: `users` 1 : N `source_images`

### 2.2 `character_generation_jobs` — 캐릭터 생성 Job (비동기)

| 컬럼                    | 타입         | 제약                                       | 기본값              | 설명                                                  |
| ----------------------- | ------------ | ------------------------------------------ | ------------------- | ----------------------------------------------------- |
| `job_id`                | VARCHAR(36)  | **PK**, NOT NULL                           | `(UUID())`          |                                                       |
| `user_id`               | VARCHAR(36)  | **FK** → `users.user_id`, CASCADE          |                     | 요청자                                                |
| `source_img_id`         | VARCHAR(36)  | **FK** → `source_images`, SET NULL, NULL   | `NULL`              | 원본 이미지 (텍스트-only 생성 시 NULL)                |
| `personality_keywords`  | JSON         |                                            | `[]`                | 성격 키워드 목록                                      |
| `custom_prompt`         | VARCHAR(200) | blank 허용                                 | `''`                | 사용자 커스텀 프롬프트                                |
| `status`                | VARCHAR(20)  | ENUM                                       | `QUEUED`            | `QUEUED`/`IN_PROGRESS`/`SUCCEEDED`/`FAILED`/`CONSUMED` |
| `gen_img_object_key`    | VARCHAR(500) | blank 허용                                 | `''`                | 생성 이미지 S3 key                                    |
| `gen_img_url`           | TEXT         | blank 허용                                 | `''`                | 생성된 8비트 픽셀 이미지 URL                          |
| `persona`               | TEXT         | blank 허용                                 | `''`                | AI 생성 페르소나                                      |
| `appearance`            | VARCHAR(255) | blank 허용                                 | `''`                | AI 생성 외형 묘사. 확정 등록 시 `characters.visual` 로 이전 |
| `created_at`            | DATETIME     |                                            | `CURRENT_TIMESTAMP` |                                                       |
| `updated_at`            | DATETIME     |                                            | `CURRENT_TIMESTAMP` |                                                       |

- 관계: `users` 1 : N `character_generation_jobs`, `source_images` 1 : N jobs
- `status = CONSUMED` 은 해당 Job 으로 `characters` 확정 등록이 끝난 상태
- 관련 요구사항: REQ-CHAR-001, REQ-CHAR-004

### 2.3 `characters` — 캐릭터

| 컬럼              | 타입         | 제약                                                    | 기본값              | 설명                                                                 |
| ----------------- | ------------ | ------------------------------------------------------- | ------------------- | -------------------------------------------------------------------- |
| `character_id`    | VARCHAR(36)  | **PK**, NOT NULL                                        | `(UUID())`          |                                                                      |
| `user_id`         | VARCHAR(36)  | **FK** → `users.user_id`, CASCADE                       |                     | 소유자                                                               |
| `generation_job_id` | VARCHAR(36) | **FK** → `character_generation_jobs`, **1:1**, SET NULL | `NULL`              | 생성 출처 Job (`OneToOne`)                                           |
| `character_name`  | VARCHAR(8)   |                                                         |                     | 캐릭터 이름                                                          |
| `origin_img_url`  | TEXT         | blank 허용                                              | `''`                | 사용자 업로드 원본 이미지 (presigned 서명으로 길어질 수 있어 TEXT)   |
| `gen_img_url`     | TEXT         |                                                         |                     | 생성된 8비트 픽셀 이미지                                             |
| `persona`         | TEXT         |                                                         |                     | 캐릭터 페르소나 (성격 키워드 + 설명 종합)                            |
| `visual`          | VARCHAR(255) | blank 허용                                              | `''`                | VLM 외형 묘사 (이미지 입력 시에만, 재생성 일관성·퀘스트/피드 참조용) |
| `is_active`       | TINYINT(1)   |                                                         | `1`                 | 활성화 여부 (삭제 시 0, "이사" 컨셉)                                 |
| `created_at`      | DATETIME     |                                                         | `CURRENT_TIMESTAMP` |                                                                      |
| `updated_at`      | DATETIME     |                                                         | `CURRENT_TIMESTAMP` |                                                                      |

- 관계: `users` 1 : N `characters` (계정당 최대 10명 — 애플리케이션 레벨 제약), `character_generation_jobs` 1 : 1 `characters`
- **삭제 시 처리 (확정)**: 캐릭터 삭제(`is_active = 0`, "이사" 컨셉) 시 해당 캐릭터에 할당된 미완료 `quests`는 **다른 활성 캐릭터에 재할당**한다 (애플리케이션 레벨에서 `quests.character_id` UPDATE). 단, 해당 캐릭터의 기존 `posts`/`replies`는 보존된다.
- 관련 요구사항: REQ-CHAR-001, REQ-CHAR-004

### 2.4 `img_gen_logs` — 이미지 재생성 이력

| 컬럼             | 타입        | 제약                              | 기본값              | 설명                          |
| ---------------- | ----------- | --------------------------------- | ------------------- | ----------------------------- |
| `img_gen_log_id` | INT         | **PK**, AUTO_INCREMENT            |                     |                               |
| `user_id`        | VARCHAR(36) | **FK** → `users.user_id`, CASCADE |                     |                               |
| `gen_cnt`        | INT         |                                   |                     | 누적 재생성 횟수              |
| `created_at`     | DATETIME    |                                   | `CURRENT_TIMESTAMP` |                               |
| `updated_at`     | DATETIME    |                                   | `CURRENT_TIMESTAMP` |                               |

- 정책: 1일 3회 제한 (REQ-CHAR-001 [캐릭터 생성])
- **변경 사항**: 기존 설계의 `gen_date` + `UNIQUE(user_id, gen_date)` 는 현 모델에 없다. 대신 `gen_cnt`/`updated_at` 로 관리하며, 일자별 제한 판정 로직은 애플리케이션에서 처리한다.

---

## 3. TODO / 일정 / 퀘스트

### 3.1 `todos` — TODO 항목

| 컬럼          | 타입                                               | 제약                     | 기본값     | 설명                          |
| ------------- | -------------------------------------------------- | ------------------------ | ---------- | ----------------------------- |
| `todo_id`     | VARCHAR(36)                              | **PK**, NOT NULL                  | `(UUID())`    |                  |
| `user_id`     | VARCHAR(36)                              | **FK** → `users.user_id`, CASCADE |               |                  |
| `tag_id`      | INT                                      | **FK** → `tags.tag_id`, PROTECT   |               |                  |
| `content`     | VARCHAR(20)                              |                                   |               | TODO 내용        |
| `status`      | ENUM(`IN_PROGRESS`,`COMPLETED`,`FAILED`) |                                   | `IN_PROGRESS` |                  |
| `todo_date`   | DATE                                     |                                   |               | 해당 TODO의 날짜 |
| `created_at`  | DATETIME                                 |                                   | `CURRENT_TIMESTAMP` |            |
| `updated_at`  | DATETIME                                 |                                   | `CURRENT_TIMESTAMP` |            |

- 관계: `users` 1 : N `todos`, `tags` 1 : N `todos` (`tag` 삭제는 `PROTECT`)
- 매일 자정 미완료 시 `FAILED` 처리 배치 필요
- **변경 사항**: `PENDING` 상태와 `is_extended`(24h 연장) 컬럼은 현 모델에 없다. 기본 상태가 `IN_PROGRESS`
- 관련 요구사항: REQ-PLAN-001, REQ-PLAN-002

### 3.2 `quests` — 캐릭터 퀘스트

| 컬럼           | 타입        | 제약                               | 기본값     | 설명                                                          |
| -------------- | ----------- | ---------------------------------- | ---------- | ------------------------------------------------------------- |
| `quest_id`           | VARCHAR(36) | **PK**, NOT NULL                            | `(UUID())`    |                                                               |
| `character_id`       | VARCHAR(36) | **FK** → `characters.character_id`, CASCADE |               |                                                               |
| `todo_id`            | VARCHAR(36) | **FK** → `todos.todo_id`, CASCADE           |               |                                                               |
| `content`            | TEXT        |                                             |               | 퀘스트 내용 (캐릭터 페르소나·외형 관련, 사용자 TODO와는 독립) |
| `status`             | ENUM(`IN_PROGRESS`,`COMPLETED`,`FAILED`) |                | `IN_PROGRESS` |                                                               |
| `character_reaction` | TEXT        | blank 허용                                  | `''`          | 퀘스트에 대한 캐릭터 반응 (피드/말풍선 소스)                  |
| `created_at`         | DATETIME    |                                             | `CURRENT_TIMESTAMP` |                                                         |
| `updated_at`         | DATETIME    |                                             | `CURRENT_TIMESTAMP` |                                                         |

- 관계: `todos` 1 : N `quests`, `characters` 1 : N `quests`
- TODO 확정 시 랜덤 캐릭터에 할당 (REQ-PLAN-001 [캐릭터 퀘스트])
- **변경 사항**: 상태 기본값은 `IN_PROGRESS`(소문자 `pending` 아님), `PENDING` 없음. 캐릭터 삭제 FK는 모델상 `CASCADE`이나 애플리케이션은 재할당으로 처리(REQ-CHAR-004)
- 관련 요구사항: REQ-PLAN-001, REQ-PLAN-002

### 3.3 `schedules` — 캘린더 일정

| 컬럼          | 타입         | 제약                     | 기본값     | 설명           |
| ------------- | ------------ | ------------------------ | ---------- | -------------- |
| `schedule_id` | VARCHAR(36)  | **PK**, NOT NULL                  | `(UUID())` |                |
| `user_id`     | VARCHAR(36)  | **FK** → `users.user_id`, CASCADE |            |                |
| `tag_id`      | INT          | **FK** → `tags.tag_id`, PROTECT   |            |                |
| `title`       | VARCHAR(20)  |                                   |            | 일정 제목      |
| `description` | VARCHAR(200) | blank 허용                        | `''`       |                |
| `start_date`  | DATE         |                                   |            |                |
| `end_date`    | DATE         | NULL 허용                         | `NULL`     | 연속 일정 표현 |

- 관계: `users` 1 : N `schedules`, `tags` 1 : N `schedules` (`tag` 삭제는 `PROTECT`)
- 관련 요구사항: REQ-PLAN-003 (챗봇 수락 시 자동 생성), REQ-PLAN-004~007

### 3.4 `tags` — 태그 (사용자별)

| 컬럼      | 타입        | 제약                               | 기본값 | 설명        |
| --------- | ----------- | ---------------------------------- | ------ | ----------- |
| `tag_id`  | INT         | **PK**, NOT NULL, AUTO_INCREMENT            |        |             |
| `user_id` | VARCHAR(36) | **FK** → `users.user_id`, NOT NULL, CASCADE |        | 태그 소유자 |
| `content` | VARCHAR(20) |                                             |        | 태그 이름   |
| `color`   | VARCHAR(7)  |                                             |        | HEX 색상 (기본값은 애플리케이션 레벨) |

- **확정 정책**: 태그는 **사용자 단위로 관리**된다. 사용자마다 본인의 프로젝트/카테고리별 태그를 자유롭게 생성·관리할 수 있다.
- 권장 인덱스: `UNIQUE(user_id, content)` — 동일 사용자가 중복 태그명 생성 방지
- `todos`, `schedules` 모두에서 참조 (태그 생성자와 TODO/일정 소유자는 동일 사용자여야 함 — 애플리케이션 레벨 검증)
- 관계: `users` 1 : N `tags`

---

## 4. 피드 (SNS)

### 4.1 `posts` — 캐릭터 게시물

| 컬럼           | 타입         | 제약                               | 기본값              | 설명                                                         |
| -------------- | ------------ | ---------------------------------- | ------------------- | ------------------------------------------------------------ |
| `post_id`      | VARCHAR(36)  | **PK**, NOT NULL                            | `(UUID())`          |                                                              |
| `character_id` | VARCHAR(36)  | **FK** → `characters.character_id`, CASCADE |                     | 작성 캐릭터                                                  |
| `quest_id`     | VARCHAR(36)  | **FK** → `quests.quest_id`, CASCADE         |                     | 트리거된 퀘스트                                              |
| `content`      | VARCHAR(150) |                                             |                     | 게시글 본문 (REQ-FEED-001)                                   |
| `img_url`      | VARCHAR(500) |                                             |                     | 게시물 이미지 (하루 5개 제한)                                |
| `is_liked`     | TINYINT(1)   |                                             | `0`                 | 좋아요 여부 (사용자가 본인 캐릭터 피드에 토글, REQ-FEED-002) |
| `created_at`   | DATETIME     |                                             | `CURRENT_TIMESTAMP` |                                                              |
| `updated_at`   | DATETIME     |                                             | `CURRENT_TIMESTAMP` |                                                              |

- 관계: `characters` 1 : N `posts`, `quests` 1 : N `posts` (퀘스트 완료 시 1개 생성)
- 관련 요구사항: REQ-FEED-001~004

### 4.2 `comments` — 댓글

| 컬럼         | 타입        | 제약                     | 기본값              | 설명            |
| ------------ | ----------- | ------------------------ | ------------------- | --------------- |
| `comment_id` | VARCHAR(36) | **PK**, NOT NULL         | `(UUID())`          |                 |
| `post_id`    | VARCHAR(36) | **FK** → `posts.post_id` |                     |                 |
| `user_id`    | VARCHAR(36) | **FK** → `users.user_id` |                     | 작성자 (사용자) |
| `content`    | VARCHAR(50) |                          |                     |                 |
| `created_at` | DATETIME    |                          | `CURRENT_TIMESTAMP` |                 |

- 정책: 댓글 작성 시 토큰 3개 소모, 1일 최대 5개 (애플리케이션 레벨 검증)
- 관계: `posts` 1 : N `comments`, `users` 1 : N `comments`

### 4.3 `replies` — 캐릭터 자동 답글

| 컬럼           | 타입        | 제약                               | 기본값              | 설명             |
| -------------- | ----------- | ---------------------------------- | ------------------- | ---------------- |
| `reply_id`     | VARCHAR(36) | **PK**, NOT NULL                   | `(UUID())`          |                  |
| `comment_id`   | VARCHAR(36) | **FK** → `comments.comment_id`     |                     |                  |
| `character_id` | VARCHAR(36) | **FK** → `characters.character_id` |                     | 답글 작성 캐릭터 |
| `content`      | TEXT        |                                    |                     |                  |
| `created_at`   | DATETIME    |                                    | `CURRENT_TIMESTAMP` |                  |

- 정책: 댓글 작성 10분 후 자동 생성
- 관계: `comments` 1 : 1 `replies`, `characters` 1 : N `replies`

---

## 5. 회고

### 5.1 `reflections` — 일일 회고

| 컬럼                 | 타입        | 제약                     | 기본값              | 설명           |
| -------------------- | ----------- | ------------------------ | ------------------- | -------------- |
| `reflection_id`               | VARCHAR(36) | **PK**, NOT NULL                  | `(UUID())`          |                            |
| `user_id`                     | VARCHAR(36) | **FK** → `users.user_id`, CASCADE |                     |                            |
| `reflection_date`             | DATE        |                                   |                     | 회고 대상 날짜             |
| `good_points`                 | TEXT        | NULL 허용                         | `NULL`              | 잘한 점                    |
| `improvement_points`          | TEXT        | NULL 허용                         | `NULL`              | 못한 점/개선점             |
| `good_token_rewarded`         | TINYINT(1)  |                                   | `0`                 | 잘한 점 작성 토큰 지급 여부 |
| `improvement_token_rewarded`  | TINYINT(1)  |                                   | `0`                 | 개선점 작성 토큰 지급 여부 |
| `created_at`                  | DATETIME    |                                   | `CURRENT_TIMESTAMP` |                            |
| `updated_at`                  | DATETIME    |                                   | `CURRENT_TIMESTAMP` |                            |

- 유일성: `(user_id, reflection_date)` UNIQUE 제약 적용 (하루 1회, `unique_user_reflection_date`)
- 토큰 보상은 항목(good/improvement)별로 1회만 지급되며 `*_token_rewarded` 플래그로 중복 방지
- 관련 요구사항: REQ-RETRO-001

---

## 6. 토큰 / 운영

### 6.1 `token_transactions` — 토큰 거래 내역

| 컬럼                   | 타입         | 제약                     | 기본값              | 설명                                                                        |
| ---------------------- | ------------ | ------------------------ | ------------------- | --------------------------------------------------------------------------- |
| `token_transaction_id` | VARCHAR(36)  | **PK**, NOT NULL                  | `(UUID())`          |                                                                             |
| `user_id`              | VARCHAR(36)  | **FK** → `users.user_id`, CASCADE |                     |                                                                             |
| `amount`               | INT          |                                   |                     | 양수 = 지급, 음수 = 소모                                                    |
| `type`                 | VARCHAR(30)  |                                   |                     | `TODO_COMPLETE` / `QUEST_BONUS` / `REFLECTION` / `COMMENT` / `CUSTOMIZE` 등 |
| `reference_id`         | VARCHAR(255) |                                   |                     | 관련 엔티티 ID (todo_id, quest_id 등)                                       |
| `created_at`           | DATETIME     |                                   | `CURRENT_TIMESTAMP` |                                                                             |

- `users.token_balance` 와의 정합성은 트랜잭션으로 보장
- 하루 토큰 지급 상한선(20개)은 애플리케이션에서 일자별 합산 검증
- 관련 요구사항: REQ-TOKEN-001

### 6.2 `notifications` — 인앱 알림

| 컬럼              | 타입         | 제약                             | 기본값              | 설명                                            |
| ----------------- | ------------ | -------------------------------- | ------------------- | ----------------------------------------------- |
| `notification_id` | INT          | **PK**, NOT NULL, AUTO_INCREMENT  |                     | 알림 식별자 (로그성 테이블이므로 INT 사용)      |
| `user_id`         | VARCHAR(36)  | **FK** → `users.user_id`, CASCADE |                     |                                                 |
| `type`            | VARCHAR(20)  |                                   |                     | `FEED_NEW` / `QUEST_DEADLINE` / `RETROSPECT` 등 |
| `title`           | VARCHAR(100) |                                   |                     |                                                 |
| `content`         | TEXT         |                                   |                     |                                                 |
| `data`            | JSON         |                                   | `{}`                | 알림 페이로드 (딥링크 등, Django `JSONField`)   |
| `is_read`         | TINYINT(1)   |                                   | `0`                 |                                                 |
| `created_at`      | DATETIME     |                                   | `CURRENT_TIMESTAMP` |                                                 |
| `updated_at`      | DATETIME     |                                   | `CURRENT_TIMESTAMP` |                                                 |

- 관련 요구사항: REQ-NOTI-002

> `img_gen_logs` 는 캐릭터 도메인 앱(`apps/characters`)에 속하므로 §2.4 에 기술한다.

---

## 7. 관계도 요약

```
users ─┬─ social_accounts            (1:N)
       ├─ refresh_tokens             (1:N)
       ├─ source_images              (1:N) ─── character_generation_jobs (1:N)
       ├─ character_generation_jobs  (1:N) ─── characters   (1:1, SET NULL)
       ├─ characters                 (1:N) ─┬─ quests       (1:N) ─── posts (1:N)
       │                                    ├─ posts        (1:N)
       │                                    └─ replies      (1:N)
       ├─ todos                      (1:N) ─── quests       (1:N)
       ├─ schedules                  (1:N)
       ├─ reflections                (1:N)
       ├─ comments                   (1:N) ─── replies      (1:N)
       ├─ tags                       (1:N)
       ├─ token_transactions         (1:N)
       ├─ notifications              (1:N)
       └─ img_gen_logs               (1:N)

tags ─┬─ todos                       (1:N)
      └─ schedules                   (1:N)

posts ─── comments                   (1:N)
```

> 위 FK 다중도는 모델 정의 그대로다. `replies`/`posts` 는 모델상 `1:N` 이지만 비즈니스 규칙상 댓글당 답글 1개·퀘스트당 게시물 1개로 운영된다(애플리케이션 레벨).

---

## 8. 인덱스 권장 (운영 성능)

| 테이블               | 인덱스                                                     | 용도                              |
| -------------------- | ---------------------------------------------------------- | --------------------------------- |
| `users`              | `UNIQUE(email)`                                            | 로그인 조회                       |
| `social_accounts`    | `UNIQUE(provider_id)`                                      | 소셜 로그인 매칭                  |
| `refresh_tokens`     | `INDEX(user_id, expires_at)`                               | 만료 토큰 정리                    |
| `characters`         | `INDEX(user_id, is_active)`                                | 마을 캐릭터 조회                  |
| `todos`              | `INDEX(user_id, todo_date, status)`                        | 오늘의 TODO HUD, 캘린더           |
| `quests`             | `INDEX(character_id, status)`, `INDEX(todo_id)`            | 캐릭터 말풍선, 완료 처리          |
| `schedules`          | `INDEX(user_id, start_date)`                               | 캘린더 월 조회                    |
| `tags`               | `UNIQUE(user_id, content)`, `INDEX(user_id)`               | 사용자별 태그 조회, 중복 방지     |
| `posts`              | `INDEX(character_id, created_at DESC)`                     | 타임라인/피드                     |
| `comments`           | `INDEX(post_id, created_at)`, `INDEX(user_id, created_at)` | 댓글 조회, 일일 한도              |
| `reflections`        | `UNIQUE(user_id, reflection_date)`                         | 하루 1회 보장                     |
| `token_transactions` | `INDEX(user_id, created_at)`                               | 일일 상한선 합산                  |
| `notifications`      | `INDEX(user_id, is_read, created_at DESC)`                 | 미확인 알림 배지                  |
| `img_gen_logs`       | `INDEX(user_id, created_at)`                               | 일일 3회 제한 합산                |
| `refresh_tokens`     | `UNIQUE(token_hash)`                                       | 토큰 매칭                         |
| `character_generation_jobs` | `INDEX(user_id, status)`                            | 진행 중 Job 폴링                  |

---

## 9. 스키마 이슈 및 논의 필요 사항

### as-built 반영 시 변경된 주요 사항 (초기 ERD/요구사항정의서 대비)

| 테이블                      | 변경 내용                                                                                                    |
| --------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `users`                     | `nickname` → `user_name`, `job` 50→20, `birth` NOT NULL, `login_type`/`personalization`/`is_staff` 추가      |
| `refresh_tokens`            | `token_hash` UNIQUE, `persistent` 추가                                                                       |
| `source_images`             | **신규** — presigned 업로드 원본 이미지                                                                      |
| `character_generation_jobs` | **신규** — 비동기 캐릭터 생성 Job                                                                            |
| `characters`                | `character_name` 50→8, `origin_img_url`/`gen_img_url` TEXT, `visual` VARCHAR(255), `generation_job` 1:1 추가 |
| `img_gen_logs`              | `gen_date` 및 `UNIQUE(user_id, gen_date)` 제거 → `gen_cnt`/`updated_at` 관리                                 |
| `todos`                     | `PENDING` 상태·`is_extended` 컬럼 제거, 기본 상태 `IN_PROGRESS`                                              |
| `quests`                    | `character_reaction`/`created_at` 추가, 상태 기본값 `IN_PROGRESS`                                            |
| `reflections`               | `good_token_rewarded`/`improvement_token_rewarded` 추가, points 컬럼 NULL 허용                               |
| `posts`                     | `content` 140→150, `updated_at` 추가                                                                         |
| `notifications`             | `data`(JSON) 추가, `type` 50→20                                                                              |

### 백로그 (추후 정의)

다음 항목은 요구사항에 정의되어 있으나 현 Phase에서는 데이터 모델에 포함하지 않으며, 추후 확장 시 재설계한다.

| #   | 항목                                                       | 관련 요구사항                            | 예상 추가 테이블/컬럼                              |
| --- | ---------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------- |
| 4   | 챗봇 대화 로그 (멀티턴 컨텍스트)                           | REQ-PLAN-003                             | `chat_sessions`, `chat_messages` 등                |
| 5   | 사용자 설정 (캘린더 온/오프, 포모도로 시간, 디스코드 알림) | REQ-AUTH-005, REQ-MAIN-006, REQ-NOTI-001 | `user_settings` 단일 테이블 또는 `users` 컬럼 확장 |
| 6   | 집 커스터마이징 (외형 이력, 현재 적용 이미지)              | REQ-CUST-001                             | `character_homes` 또는 `characters.home_img_url`   |
