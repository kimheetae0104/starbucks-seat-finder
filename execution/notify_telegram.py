#!/usr/bin/env python3
"""
알림 대상 매장 목록을 받아서 Telegram으로 발송한다.
Usage: python notify_telegram.py --alerts alerts.json
       echo '[...]' | python notify_telegram.py --alerts -
Exit: 0=success, 1=error
"""

import sys
import json
import argparse
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

LEVEL_EMOJI = {
    "여유": "🟢",
    "보통": "🟡",
    "혼잡": "🔴",
    "매우혼잡": "🔴",
    "알수없음": "⚪",
}


def format_message(store: dict) -> str:
    level = store.get("congestion_level", "알수없음")
    emoji = LEVEL_EMOJI.get(level, "⚪")
    name = store.get("name", store.get("store_id", "?"))
    address = store.get("address", "")
    checked_at = store.get("checked_at", "")
    prev = store.get("prev_level")

    change = f"\n📊 변화: {prev} → {level}" if prev else ""

    maps_url = f"https://maps.google.com/?q={requests.utils.quote(f'스타벅스 {name}')}"

    return (
        f"{emoji} 자리 났어요!\n\n"
        f"📍 스타벅스 {name}\n"
        f"🏃 현재 상태: {level}{change}\n"
        f"🕐 확인 시각: {checked_at}\n"
        f"📫 주소: {address}\n\n"
        f"🗺️ {maps_url}"
    )


def send_message(token: str, chat_id: str, text: str) -> bool:
    url = TELEGRAM_API.format(token=token)
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR] Telegram 전송 실패: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alerts", required=True, help="alerts JSON 파일 또는 '-' for stdin")
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "7643816839")

    if not token:
        print("[ERROR] TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if args.alerts == "-":
        alerts = json.load(sys.stdin)
    else:
        with open(args.alerts, encoding="utf-8") as f:
            alerts = json.load(f)

    if not alerts:
        print("[INFO] 알림 대상 없음")
        return

    success = 0
    for store in alerts:
        msg = format_message(store)
        if send_message(token, chat_id, msg):
            print(f"[OK] 알림 전송: {store.get('name', store.get('store_id'))}")
            success += 1
        else:
            print(f"[FAIL] 알림 실패: {store.get('name', store.get('store_id'))}", file=sys.stderr)

    if success == 0 and alerts:
        sys.exit(1)


if __name__ == "__main__":
    main()
