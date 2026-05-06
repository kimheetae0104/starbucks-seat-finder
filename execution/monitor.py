#!/usr/bin/env python3
"""
메인 모니터링 루프. 주기적으로 매장 혼잡도를 확인하고 알림을 보낸다.
Usage: python execution/monitor.py
       python execution/monitor.py --once   (단일 실행 후 종료)
"""

import sys
import json
import time
import signal
import argparse
import subprocess
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
TMP_DIR = BASE_DIR / ".tmp"
TMP_DIR.mkdir(exist_ok=True)

CURRENT_FILE = str(TMP_DIR / "current.json")
ALERTS_FILE = str(TMP_DIR / "alerts.json")
STATE_FILE = str(TMP_DIR / "store_state.json")

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
NOTIFY_ON_MODERATE = os.getenv("NOTIFY_ON_MODERATE", "false").lower() == "true"
USE_MOCK = os.getenv("MOCK_MODE", "false").lower() == "true"

running = True


def handle_signal(sig, frame):
    global running
    print("\n[INFO] 종료 신호 수신, 루프 중단 중...")
    running = False


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


def run_step(cmd: list[str], stdin_data: str | None = None) -> tuple[int, str]:
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        cwd=str(BASE_DIR),
    )
    if result.returncode != 0:
        print(f"[ERROR] {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
    return result.returncode, result.stdout


def run_cycle() -> bool:
    print("[1/3] 매장 데이터 수집 중...")
    mock_flag = ["--mock"] if USE_MOCK else []
    code, current_json = run_step(["python", "execution/fetch_store_data.py"] + mock_flag)
    if code != 0:
        print("[WARN] 데이터 수집 실패, 이번 사이클 건너뜀")
        return False

    with open(CURRENT_FILE, "w") as f:
        f.write(current_json)

    print("[2/3] 가용성 확인 중...")
    moderate_flag = ["--notify-on-moderate"] if NOTIFY_ON_MODERATE else []
    code, alerts_json = run_step(
        ["python", "execution/check_availability.py", "--current", CURRENT_FILE, "--state", STATE_FILE] + moderate_flag
    )
    if code != 0:
        return False

    alerts = json.loads(alerts_json)
    print(f"[2/3] 알림 대상: {len(alerts)}개 매장")

    if not alerts:
        return True

    with open(ALERTS_FILE, "w") as f:
        json.dump(alerts, f, ensure_ascii=False)

    print("[3/3] Telegram 알림 발송 중...")
    code, _ = run_step(["python", "execution/notify_telegram.py", "--alerts", ALERTS_FILE])
    return code == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="단일 실행 후 종료")
    parser.add_argument("--mock", action="store_true", help="Mock 데이터 사용 (테스트용)")
    args = parser.parse_args()

    global USE_MOCK
    if args.mock:
        USE_MOCK = True

    print(f"스타벅스자리찾기 모니터 시작 (주기: {POLL_INTERVAL}초)")
    print(f"Ctrl+C로 중단\n")

    if args.once:
        success = run_cycle()
        sys.exit(0 if success else 1)

    while running:
        run_cycle()
        if running:
            print(f"\n[대기] 다음 확인까지 {POLL_INTERVAL}초...\n")
            for _ in range(POLL_INTERVAL):
                if not running:
                    break
                time.sleep(1)

    print("[INFO] 모니터 종료")


if __name__ == "__main__":
    main()
