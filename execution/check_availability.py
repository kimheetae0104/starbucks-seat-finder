#!/usr/bin/env python3
"""
현재 혼잡도와 이전 상태를 비교해서 알림 대상 매장을 반환한다.
Usage: python check_availability.py --current current.json [--state .tmp/store_state.json]
Output: JSON (알림 대상 매장 목록) to stdout
Exit: 0=success, 1=error
"""

import sys
import json
import argparse
import os
from datetime import datetime


NOTIFY_LEVELS = {"여유"}
NOTIFY_ON_MODERATE_LEVELS = {"여유", "보통"}

STATE_FILE = ".tmp/store_state.json"


def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(path: str, state: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def should_notify(prev_level: str | None, current_level: str, notify_on_moderate: bool) -> bool:
    target_levels = NOTIFY_ON_MODERATE_LEVELS if notify_on_moderate else NOTIFY_LEVELS
    if current_level not in target_levels:
        return False
    # 첫 조회이거나 이전 상태에서 변화가 있을 때만 알림
    if prev_level is None:
        return True
    return prev_level not in target_levels


def check(current_data: list[dict], state_path: str, notify_on_moderate: bool) -> list[dict]:
    prev_state = load_state(state_path)
    alerts = []
    new_state = {}

    for store in current_data:
        store_id = store["store_id"]
        current_level = store["congestion_level"]
        prev_level = prev_state.get(store_id)
        new_state[store_id] = current_level

        if should_notify(prev_level, current_level, notify_on_moderate):
            alerts.append({
                **store,
                "prev_level": prev_level,
                "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })

    save_state(state_path, new_state)
    return alerts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True, help="fetch_store_data.py 출력 JSON 파일 또는 '-' for stdin")
    parser.add_argument("--state", default=STATE_FILE)
    parser.add_argument("--notify-on-moderate", action="store_true")
    args = parser.parse_args()

    notify_on_moderate = args.notify_on_moderate or os.getenv("NOTIFY_ON_MODERATE", "false").lower() == "true"

    if args.current == "-":
        current_data = json.load(sys.stdin)
    else:
        try:
            with open(args.current, encoding="utf-8") as f:
                current_data = json.load(f)
        except FileNotFoundError:
            print(f"[ERROR] {args.current} not found", file=sys.stderr)
            sys.exit(1)

    alerts = check(current_data, args.state, notify_on_moderate)
    print(json.dumps(alerts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
