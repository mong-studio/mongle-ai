# DATA_MODEL.md

> **몽글마을 (Monggeul Village) — 데이터베이스 스키마 정의서**

---

## 0. 개요

본 문서는 몽글마을 서비스의 데이터베이스 스키마를 정의한다. ERD 파일에 정의된 15개 테이블을 도메인별로 그룹화하여 기술하며, 요구사항정의서(v1.2)와의 차이/논의 필요 사항을 마지막 섹션에 정리한다.

### 도메인 그룹

| 도메인                   | 테이블                                                |
| ------------------------ | ----------------------------------------------------- |
| **회원 / 인증**          | `users`, `social_accounts`, `refresh_tokens`          |
| **캐릭터**               | `characters`                                          |
| **TODO / 일정 / 퀘스트** | `todos`, `quests`, `schedules`, `tags`                |
| **피드 (SNS)**           | `posts`, `comments`, `replies`                        |
| **회고**                 | `reflections`                                         |
| **토큰 / 운영**          | `token_transactions`, `notifications`, `img_gen_logs` |

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
| `user_id`       | VARCHAR(36)  | **PK**, NOT NULL | `(UUID())`          | 사용자 고유 식별자                                                          |
| `email`         | VARCHAR(255) | UNIQUE           |                     | 로그인 이메일 (RFC 5321 형식 검증)                                          |
| `password`      | VARCHAR(255) | NULL 허용        |                     | 해시된 비밀번호. **소셜 로그인 전용 사용자를 위해 NULL 허용 (의도된 설계)** |
| `nickname`      | VARCHAR(8)   |                  |                     | 닉네임 (한글/영문/숫자, 2~8자, 중복 허용)                                   |
| `job`           | VARCHAR(50)  |                  |                     | 직업 (선택 입력)                                                            |
| `birth`         | DATE         |                  |                     | 생년월일 (선택 입력)                                                        |
| `token_balance` | INT          |                  | `5`                 | 보유 토큰(사과) 잔액                                                        |
| `is_active`     | TINYINT(1)   |                  | `1`                 | 활성 계정 여부 (탈퇴 시 0)                                                  |
| `is_aiconsent`  | TINYINT(1)   |                  | `0`                 | AI 학습 데이터 활용 동의 여부 (REQ-PRIV-001)                                |
| `created_at`    | DATETIME     |                  | `CURRENT_TIMESTAMP` | 가입일시                                                                    |
| `updated_at`    | DATETIME     |                  | `CURRENT_TIMESTAMP` | 마지막 수정일시                                                             |

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
| `refresh_token_id` | INT          | **PK**, AUTO_INCREMENT   |                     |                      |
| `user_id`          | VARCHAR(36)  | **FK** → `users.user_id` |                     |                      |
| `token_hash`       | VARCHAR(255) |                          |                     | 해시된 리프레시 토큰 |
| `device_info`      | VARCHAR(255) |                          |                     | 기기 식별 정보       |
| `expires_at`       | DATETIME     |                          |                     | 만료일시 (2주)       |
| `created_at`       | DATETIME     |                          | `CURRENT_TIMESTAMP` |                      |

- 관계: `users` 1 : N `refresh_tokens`
- 관련 요구사항: REQ-AUTH-002 [자동 로그인]
- 비밀번호 변경/로그아웃/2주 미접속 시 무효화 처리 필요

---

## 2. 캐릭터

### 2.1 `characters` — 캐릭터

| 컬럼             | 타입         | 제약                     | 기본값              | 설명                                      |
| ---------------- | ------------ | ------------------------ | ------------------- | ----------------------------------------- |
| `character_id`   | VARCHAR(36)  | **PK**, NOT NULL         | `(UUID())`          |                                           |
| `user_id`        | VARCHAR(36)  | **FK** → `users.user_id` |                     | 소유자                                    |
| `character_name` | VARCHAR(50)  |                          |                     | 캐릭터 이름                               |
| `origin_img_url` | VARCHAR(500) |                          |                     | 사용자 업로드 원본 이미지                 |
| `gen_img_url`    | VARCHAR(500) |                          |                     | 생성된 8비트 픽셀 이미지                  |
| `persona`        | TEXT         |                          |                     | 캐릭터 페르소나 (성격 키워드 + 설명 종합) |
| `appearance_description` | TEXT |                          | `NULL`              | VLM 외형 묘사 (이미지 입력 시에만, 재생성 일관성·퀘스트/피드 참조용) |
| `is_active`      | TINYINT(1)   |                          | `1`                 | 활성화 여부 (삭제 시 0, "이사" 컨셉)      |
| `created_at`     | DATETIME     |                          | `CURRENT_TIMESTAMP` |                                           |
| `updated_at`     | DATETIME     |                          | `CURRENT_TIMESTAMP` |                                           |

- 관계: `users` 1 : N `characters` (계정당 최대 10명 — 애플리케이션 레벨 제약)
- **삭제 시 처리 (확정)**: 캐릭터 삭제(`is_active = 0`, "이사" 컨셉) 시 해당 캐릭터에 할당된 미완료 `quests`는 **다른 활성 캐릭터에 재할당**한다 (애플리케이션 레벨에서 `quests.character_id` UPDATE). 단, 해당 캐릭터의 기존 `posts`/`replies`는 보존된다.
- 관련 요구사항: REQ-CHAR-001, REQ-CHAR-004

---

## 3. TODO / 일정 / 퀘스트

### 3.1 `todos` — TODO 항목

| 컬럼          | 타입                                               | 제약                     | 기본값     | 설명                          |
| ------------- | -------------------------------------------------- | ------------------------ | ---------- | ----------------------------- |
| `todo_id`     | VARCHAR(36)                                        | **PK**, NOT NULL         | `(UUID())` |                               |
| `user_id`     | VARCHAR(36)                                        | **FK** → `users.user_id` |            |                               |
| `tag_id`      | INT                                                | **FK** → `tags.tag_id`   |            |                               |
| `content`     | VARCHAR(20)                                        |                          |            | TODO 내용                     |
| `status`      | ENUM(`PENDING`,`IN_PROGRESS`,`COMPLETED`,`FAILED`) |                          | `PENDING`  |                               |
| `is_extended` | TINYINT(1)                                         |                          | `0`        | 24시간 연장 여부 (항목당 1회) |
| `todo_date`   | DATE                                               |                          |            | 해당 TODO의 날짜              |
| `created_at`  | DATETIME                                           |                          |            |                               |
| `updated_at`  | DATETIME                                           |                          |            |                               |

- 관계: `users` 1 : N `todos`, `tags` 1 : N `todos`
- 매일 자정 미완료 시 `FAILED` 처리 배치 필요
- 관련 요구사항: REQ-PLAN-001, REQ-PLAN-002

### 3.2 `quests` — 캐릭터 퀘스트

| 컬럼           | 타입        | 제약                               | 기본값     | 설명                                                          |
| -------------- | ----------- | ---------------------------------- | ---------- | ------------------------------------------------------------- |
| `quest_id`     | VARCHAR(36) | **PK**, NOT NULL                   | `(UUID())` |                                                               |
| `character_id` | VARCHAR(36) | **FK** → `characters.character_id` |            |                                                               |
| `todo_id`      | VARCHAR(36) | **FK** → `todos.todo_id`           |            |                                                               |
| `content`      | TEXT        |                                    |            | 퀘스트 내용 (캐릭터 페르소나·외형 관련, 사용자 TODO와는 독립) |
| `status`       | VARCHAR(20) |                                    | `pending`  | `PENDING`/`IN_PROGRESS`/`COMPLETED`/`FAILED`                  |
| `updated_at`   | DATETIME    |                                    |            |                                                               |

- 관계: `todos` 1 : 1 `quests`, `characters` 1 : N `quests`
- TODO 확정 시 랜덤 캐릭터에 할당 (REQ-PLAN-001 [캐릭터 퀘스트])
- 캐릭터 삭제 시 다른 캐릭터에게 재할당 (REQ-CHAR-004)
- 관련 요구사항: REQ-PLAN-001, REQ-PLAN-002

### 3.3 `schedules` — 캘린더 일정

| 컬럼          | 타입         | 제약                     | 기본값     | 설명           |
| ------------- | ------------ | ------------------------ | ---------- | -------------- |
| `schedule_id` | VARCHAR(36)  | **PK**, NOT NULL         | `(UUID())` |                |
| `user_id`     | VARCHAR(36)  | **FK** → `users.user_id` |            |                |
| `tag_id`      | INT          | **FK** → `tags.tag_id`   |            |                |
| `title`       | VARCHAR(20)  |                          |            | 일정 제목      |
| `start_date`  | DATE         |                          |            |                |
| `end_date`    | DATE         |                          |            | 연속 일정 표현 |
| `description` | VARCHAR(200) |                          |            |                |

- 관계: `users` 1 : N `schedules`, `tags` 1 : N `schedules`
- 관련 요구사항: REQ-PLAN-003 (챗봇 수락 시 자동 생성), REQ-PLAN-004~007

### 3.4 `tags` — 태그 (사용자별)

| 컬럼      | 타입        | 제약                               | 기본값 | 설명        |
| --------- | ----------- | ---------------------------------- | ------ | ----------- |
| `tag_id`  | INT         | **PK**, NOT NULL, AUTO_INCREMENT   |        |             |
| `user_id` | VARCHAR(36) | **FK** → `users.user_id`, NOT NULL |        | 태그 소유자 |
| `content` | VARCHAR(20) |                                    |        | 태그 이름   |
| `color`   | VARCHAR(7)  |                                    | `#eee` | HEX 색상    |

- **확정 정책**: 태그는 **사용자 단위로 관리**된다. 사용자마다 본인의 프로젝트/카테고리별 태그를 자유롭게 생성·관리할 수 있다.
- 권장 인덱스: `UNIQUE(user_id, content)` — 동일 사용자가 중복 태그명 생성 방지
- `todos`, `schedules` 모두에서 참조 (태그 생성자와 TODO/일정 소유자는 동일 사용자여야 함 — 애플리케이션 레벨 검증)
- 관계: `users` 1 : N `tags`

> ⚠ **ERD 수정 필요**: 현재 ERD `tags` 테이블에는 `user_id` 컬럼이 없음. ERD 파일에 `user_id` FK 추가 및 `users → tags` 관계 추가 필요.

---

## 4. 피드 (SNS)

### 4.1 `posts` — 캐릭터 게시물

| 컬럼           | 타입         | 제약                               | 기본값              | 설명                                                         |
| -------------- | ------------ | ---------------------------------- | ------------------- | ------------------------------------------------------------ |
| `post_id`      | VARCHAR(36)  | **PK**, NOT NULL                   | `(UUID())`          |                                                              |
| `character_id` | VARCHAR(36)  | **FK** → `characters.character_id` |                     | 작성 캐릭터                                                  |
| `quest_id`     | VARCHAR(36)  | **FK** → `quests.quest_id`         |                     | 트리거된 퀘스트                                              |
| `content`      | VARCHAR(140) |                                    |                     | 게시글 본문 (140자 제한, REQ-FEED-001)                       |
| `img_url`      | VARCHAR(500) |                                    |                     | 게시물 이미지 (선택, 하루 5개 제한)                          |
| `is_liked`     | TINYINT(1)   |                                    | `0`                 | 좋아요 여부 (사용자가 본인 캐릭터 피드에 토글, REQ-FEED-002) |
| `created_at`   | DATETIME     |                                    | `CURRENT_TIMESTAMP` |                                                              |

- 관계: `characters` 1 : N `posts`, `quests` 1 : 1 `posts` (퀘스트 완료 시 1개 생성)
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
| `reflection_id`      | VARCHAR(36) | **PK**, NOT NULL         | `(UUID())`          |                |
| `user_id`            | VARCHAR(36) | **FK** → `users.user_id` |                     |                |
| `reflection_date`    | DATE        |                          |                     | 회고 대상 날짜 |
| `good_points`        | TEXT        |                          |                     | 잘한 점        |
| `improvement_points` | TEXT        |                          |                     | 못한 점/개선점 |
| `created_at`         | DATETIME    |                          | `CURRENT_TIMESTAMP` |                |
| `updated_at`         | DATETIME    |                          | `CURRENT_TIMESTAMP` |                |

- 유일성: `(user_id, reflection_date)` UNIQUE 권장 (하루 1회)
- 관련 요구사항: REQ-RETRO-001

---

## 6. 토큰 / 운영

### 6.1 `token_transactions` — 토큰 거래 내역

| 컬럼                   | 타입         | 제약                     | 기본값              | 설명                                                                        |
| ---------------------- | ------------ | ------------------------ | ------------------- | --------------------------------------------------------------------------- |
| `token_transaction_id` | VARCHAR(36)  | **PK**, NOT NULL         | `(UUID())`          |                                                                             |
| `user_id`              | VARCHAR(36)  | **FK** → `users.user_id` |                     |                                                                             |
| `amount`               | INT          |                          |                     | 양수 = 지급, 음수 = 소모                                                    |
| `type`                 | VARCHAR(50)  |                          |                     | `TODO_COMPLETE` / `QUEST_BONUS` / `REFLECTION` / `COMMENT` / `CUSTOMIZE` 등 |
| `reference_id`         | VARCHAR(255) |                          |                     | 관련 엔티티 ID (todo_id, quest_id 등)                                       |
| `created_at`           | DATETIME     |                          | `CURRENT_TIMESTAMP` |                                                                             |

- `users.token_balance` 와의 정합성은 트랜잭션으로 보장
- 하루 토큰 지급 상한선(20개)은 애플리케이션에서 일자별 합산 검증
- 관련 요구사항: REQ-TOKEN-001

### 6.2 `notifications` — 인앱 알림

| 컬럼              | 타입         | 제약                             | 기본값              | 설명                                            |
| ----------------- | ------------ | -------------------------------- | ------------------- | ----------------------------------------------- |
| `notification_id` | INT          | **PK**, NOT NULL, AUTO_INCREMENT |                     | 알림 식별자 (로그성 테이블이므로 INT 사용)      |
| `user_id`         | VARCHAR(36)  | **FK** → `users.user_id`         |                     |                                                 |
| `type`            | VARCHAR(50)  |                                  |                     | `FEED_NEW` / `QUEST_DEADLINE` / `RETROSPECT` 등 |
| `title`           | VARCHAR(100) |                                  |                     |                                                 |
| `content`         | TEXT         |                                  |                     |                                                 |
| `is_read`         | TINYINT(1)   |                                  | `0`                 |                                                 |
| `created_at`      | DATETIME     |                                  | `CURRENT_TIMESTAMP` |                                                 |
| `updated_at`      | DATETIME     |                                  |                     |                                                 |

- 관련 요구사항: REQ-NOTI-002

### 6.3 `img_gen_logs` — 이미지 재생성 이력

| 컬럼             | 타입        | 제약                     | 기본값 | 설명                          |
| ---------------- | ----------- | ------------------------ | ------ | ----------------------------- |
| `img_gen_log_id` | INT         | **PK**, AUTO_INCREMENT   |        |                               |
| `user_id`        | VARCHAR(36) | **FK** → `users.user_id` |        |                               |
| `gen_date`       | DATE        | NOT NULL                 |        | 생성 일자 (1일 3회 제한 기준) |
| `gen_cnt`        | INT         |                          |        | 해당 일자 누적 재생성 횟수    |

- 정책: 1일 3회 제한 (REQ-CHAR-001 [캐릭터 생성])
- 권장 인덱스: `UNIQUE(user_id, gen_date)` — 일자별 1개 행으로 관리하여 `gen_cnt` UPSERT 방식 권장

---

## 7. 관계도 요약

```
users ─┬─ social_accounts        (1:1)
       ├─ refresh_tokens         (1:N)
       ├─ characters             (1:N) ─┬─ quests       (1:N) ─── posts (1:1)
       │                                ├─ posts        (1:N)
       │                                └─ replies      (1:N)
       ├─ todos                  (1:N) ─── quests       (1:1)
       ├─ schedules              (1:N)
       ├─ reflections            (1:N)
       ├─ comments               (1:N) ─── replies      (1:1)
       ├─ tags                   (1:N)
       ├─ token_transactions     (1:N)
       ├─ notifications          (1:N)
       └─ img_gen_logs           (1:1)

tags ─┬─ todos                   (1:N)
      └─ schedules               (1:N)

posts ─── comments               (1:N)
```

---

## 8. 인덱스 권장 (운영 성능)

| 테이블               | 인덱스                                                     | 용도                              |
| -------------------- | ---------------------------------------------------------- | --------------------------------- |
| `users`              | `UNIQUE(email)`                                            | 로그인 조회                       |
| `social_accounts`    | `UNIQUE(provider, provider_id)`                            | 소셜 로그인 매칭                  |
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
| `img_gen_logs`       | `UNIQUE(user_id, gen_date)`                                | 일일 3회 제한 (일자별 1행 UPSERT) |

---

## 9. 스키마 이슈 및 논의 필요 사항

### 백로그 (추후 정의)

다음 항목은 요구사항에 정의되어 있으나 현 Phase에서는 데이터 모델에 포함하지 않으며, 추후 확장 시 재설계한다.

| #   | 항목                                                       | 관련 요구사항                            | 예상 추가 테이블/컬럼                              |
| --- | ---------------------------------------------------------- | ---------------------------------------- | -------------------------------------------------- |
| 4   | 챗봇 대화 로그 (멀티턴 컨텍스트)                           | REQ-PLAN-003                             | `chat_sessions`, `chat_messages` 등                |
| 5   | 사용자 설정 (캘린더 온/오프, 포모도로 시간, 디스코드 알림) | REQ-AUTH-005, REQ-MAIN-006, REQ-NOTI-001 | `user_settings` 단일 테이블 또는 `users` 컬럼 확장 |
| 6   | 집 커스터마이징 (외형 이력, 현재 적용 이미지)              | REQ-CUST-001                             | `character_homes` 또는 `characters.home_img_url`   |
