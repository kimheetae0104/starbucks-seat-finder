# Directive: 매장 모니터링

## Goal
여러 스타벅스 매장의 혼잡도를 주기적으로 확인하고, 자리가 생기면 Telegram으로 알림을 보낸다.

## Inputs
- `config/stores.json` — 모니터링할 매장 목록
- `.env` — Telegram 봇 토큰, 폴링 주기 설정

## Script
```bash
python execution/monitor.py          # 지속 실행 (Ctrl+C로 중단)
python execution/monitor.py --once   # 단회 실행 (cron용)
```

## Output
- Telegram 메시지: 자리가 난 매장 정보
- `.tmp/store_state.json`: 마지막 혼잡도 상태 저장

## 정상 흐름
1. `fetch_store_data.py` → 모든 매장 혼잡도 조회
2. `check_availability.py` → 이전 상태 대비 변화 감지
3. `notify_telegram.py` → 알림 대상 매장 전송
4. `POLL_INTERVAL_SECONDS` 대기 후 반복

## Edge Cases
- **API 타임아웃**: 재시도 3회. 전체 실패시 해당 사이클 건너뜀
- **매장 목록 변경**: `config/stores.json` 직접 편집 후 재시작
- **Telegram 실패**: 로그 출력 후 다음 사이클에 재시도 (상태는 저장됨)
- **첫 실행**: 상태 파일 없으면 현재 상태로 초기화 (여유 매장 즉시 알림)

## Known Issues
- 스타벅스 API(`getStore.do`)가 주기적으로 점검/차단됨 → 자동으로 Playwright 폴백 전환됨
- Playwright 폴백은 느림 (브라우저 실행) → 실패 시 최종적으로 mock 데이터 사용
- 실제 매장 IDs 확인: 스타벅스 코리아 웹사이트 지도에서 Network 탭으로 확인
- API 점검 중일 때 테스트: `--mock` 플래그 사용
