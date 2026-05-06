# 스타벅스자리찾기 — Design Spec
**Date:** 2026-05-06  
**Status:** Approved

---

## Overview

여러 스타벅스 매장의 혼잡도를 주기적으로 폴링해서, 자리가 생기면 Telegram으로 즉시 알림을 보내는 자동화 시스템.

---

## Architecture

Agent.md의 3-Layer 아키텍처를 따른다.

| Layer | 역할 | 구현 |
|-------|------|------|
| Layer 1 (Directive) | SOP 정의 | `directives/*.md` |
| Layer 2 (Orchestration) | 판단 및 라우팅 | Claude |
| Layer 3 (Execution) | 실제 작업 | `execution/*.py` |

---

## Data Source

**스타벅스 코리아 공식 웹 API** (앱/웹사이트 공통 엔드포인트)

- 매장 검색: `https://www.starbucks.co.kr/store/getStore.do`
- 혼잡도 정보: 매장별 `congestionLevel` 필드 (여유/보통/혼잡)
- 인증: 불필요 (공개 API)
- 응답 형식: JSON

---

## Components

### execution/fetch_store_data.py
- 입력: 매장 ID 목록 (`config/stores.json`)
- 출력: `{store_id, name, congestion_level, timestamp}` JSON
- 오류처리: 타임아웃 10초, 재시도 3회, 실패시 exit code 1

### execution/check_availability.py
- 입력: 현재 상태 JSON, 이전 상태 (`.tmp/store_state.json`)
- 출력: 알림 대상 매장 목록 (상태 변화 감지)
- 알림 조건: `혼잡/보통 → 여유` 전환 시 / 첫 조회에서 이미 `여유`인 경우

### execution/notify_telegram.py
- 입력: 알림 대상 매장 목록
- 출력: Telegram 메시지 발송
- 봇: `@pro_A1_bot` (TELEGRAM_BOT_TOKEN in .env)
- 채팅: 7643816839

### execution/monitor.py
- 메인 루프: fetch → check → notify → sleep(300)
- 실행: `python execution/monitor.py`
- 중단: Ctrl+C 또는 SIGTERM

---

## Config

### config/stores.json
```json
[
  {"id": "1000001", "name": "강남점", "address": "서울 강남구..."},
  {"id": "1000002", "name": "역삼점", "address": "서울 강남구..."}
]
```

### .env
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=7643816839
POLL_INTERVAL_SECONDS=300
NOTIFY_ON_MODERATE=false
```

---

## State Management

- `.tmp/store_state.json`: 마지막 확인 결과 저장
- 형식: `{store_id: congestion_level}` 딕셔너리
- gitignore에 포함

---

## Notification Format

```
🟢 자리 났어요!

📍 스타벅스 강남점
🏃 현재 상태: 여유
🕐 확인 시각: 14:32

구글맵: https://maps.google.com/?q=...
```

---

## Error Handling (Self-Annealing)

| 상황 | 처리 |
|------|------|
| API 타임아웃 | 재시도 3회 후 다음 폴링까지 skip |
| 매장 ID 변경 | directive 업데이트 + store.json 수정 |
| Telegram 실패 | 로그 기록, 다음 사이클에 재시도 |
| 혼잡도 필드 없음 | 해당 매장 skip, 로그 기록 |

---

## File Structure

```
스타벅스자리찾기/
├── Agent.md
├── .env
├── .gitignore
├── requirements.txt
├── config/
│   └── stores.json
├── directives/
│   ├── monitor_stores.md
│   ├── find_available_seats.md
│   └── send_notification.md
├── execution/
│   ├── fetch_store_data.py
│   ├── check_availability.py
│   ├── notify_telegram.py
│   └── monitor.py
└── .tmp/
    └── store_state.json  (gitignore)
```
