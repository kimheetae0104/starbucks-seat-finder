# 스타벅스자리찾기

여러 스타벅스 매장의 영업 상태와 시간대별 혼잡도를 모니터링하고, 자리가 날 것 같을 때 Telegram으로 알림을 보내는 자동화 시스템.

## 아키텍처

Agent.md의 3-Layer 구조를 따릅니다:

- **Layer 1 (Directive)**: `directives/` — SOP 문서
- **Layer 2 (Orchestration)**: Claude — 판단 및 라우팅
- **Layer 3 (Execution)**: `execution/` — 실행 스크립트

## 데이터 소스

| 소스 | 제공 데이터 |
|------|-----------|
| Naver Map API (Playwright) | 실시간 영업 상태, 영업 시간 |
| 시간대별 휴리스틱 | 혼잡도 추정 (여유/보통/혼잡) |

> 실시간 좌석 수 데이터는 공개 API가 없어 시간대별 패턴으로 추정합니다.

## 빠른 시작

```bash
# 1. 의존성 설치
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# 2. 환경 변수 설정
cp .env.example .env
# .env 파일에 TELEGRAM_BOT_TOKEN 입력

# 3. 테스트 실행 (Mock 데이터)
python execution/monitor.py --once --mock

# 4. 실제 모니터링 시작
python execution/monitor.py
```

## 스크립트 설명

| 스크립트 | 역할 |
|---------|------|
| `execution/find_stores.py` | 지역 내 스타벅스 매장 탐색 (stores.json 생성) |
| `execution/fetch_store_data.py` | 매장 영업 상태 + 혼잡도 추정 |
| `execution/check_availability.py` | 이전 상태 대비 변화 감지 |
| `execution/notify_telegram.py` | Telegram 알림 발송 |
| `execution/monitor.py` | 메인 폴링 루프 |

## 매장 목록 설정

```bash
# 강남 지역 매장 자동 탐색
python execution/find_stores.py --area 강남

# stores.json 자동 업데이트
python execution/find_stores.py --area 강남 --update
```

`config/stores.json`을 직접 편집해서 원하는 매장만 선택할 수도 있습니다.

## 알림 조건

- 혼잡 → 보통/여유 전환 시 즉시 알림
- 첫 실행 시 이미 여유인 매장도 알림
- `NOTIFY_ON_MODERATE=true` 로 "보통" 상태도 알림 받기

## 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `TELEGRAM_BOT_TOKEN` | 필수 | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 7643816839 | 알림 받을 채팅 ID |
| `POLL_INTERVAL_SECONDS` | 300 | 폴링 주기 (초) |
| `NOTIFY_ON_MODERATE` | false | "보통" 상태도 알림 여부 |
