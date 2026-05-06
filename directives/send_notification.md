# Directive: Telegram 알림 발송

## Goal
매장 목록을 받아서 @pro_A1_bot으로 Telegram 알림을 보낸다.

## Script
```bash
python execution/notify_telegram.py --alerts alerts.json
echo '[...]' | python execution/notify_telegram.py --alerts -
```

## Required Env
- `TELEGRAM_BOT_TOKEN` — 봇 토큰 (.env)
- `TELEGRAM_CHAT_ID` — 기본값: 7643816839

## 메시지 형식
```
🟢 자리 났어요!

📍 스타벅스 강남R점
🏃 현재 상태: 여유
📊 변화: 혼잡 → 여유
🕐 확인 시각: 14:32
📫 주소: 서울 강남구 강남대로 390

🗺️ https://maps.google.com/?q=...
```

## Edge Cases
- alerts 배열이 비어있으면 아무것도 하지 않음 (정상 종료)
- 전송 실패 시 exit code 1, stderr에 로그
