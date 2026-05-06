#!/usr/bin/env python3
"""
주변 스타벅스 매장을 탐색해서 config/stores.json 후보를 생성한다.
Playwright로 스타벅스 코리아 지도 페이지에서 매장 목록 수집.

Usage: python execution/find_stores.py [--area 강남]
Output: 발견된 매장 목록 출력 + config/stores.json 업데이트 여부 확인
"""

import sys
import json
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).parent.parent


def find_stores_near(area: str = "강남") -> list[dict]:
    """스타벅스 코리아 지도에서 지역 내 매장 목록 수집."""
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="ko-KR",
        )
        page = context.new_page()

        def handle_response(response):
            if "getStore" in response.url and response.status == 200:
                try:
                    body = response.json()
                    store_list = body.get("list", [])
                    for s in store_list:
                        s_code = str(s.get("s_code", ""))
                        s_name = s.get("s_name", "")
                        addr = s.get("doro_address") or s.get("addr", "")
                        if s_code and s_name:
                            results.append({
                                "id": s_code,
                                "name": s_name,
                                "address": addr,
                            })
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"[INFO] 스타벅스 코리아 지도 로드 중... (검색: {area})")
        page.goto(
            "https://www.starbucks.co.kr/store/store_map.do",
            timeout=30000,
            wait_until="networkidle",
        )
        page.wait_for_timeout(5000)

        browser.close()

    # 중복 제거
    seen = set()
    unique = []
    for s in results:
        if s["id"] not in seen:
            seen.add(s["id"])
            unique.append(s)

    return unique


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--area", default="강남", help="검색할 지역명 (기본: 강남)")
    parser.add_argument("--update", action="store_true", help="config/stores.json 자동 업데이트")
    args = parser.parse_args()

    stores = find_stores_near(args.area)

    print(f"\n발견된 매장 ({len(stores)}개):")
    for s in stores:
        print(f"  id={s['id']:>6}  {s['name']:<20}  {s['address'][:40]}")

    if not stores:
        print("[ERROR] 매장을 찾지 못했습니다.")
        sys.exit(1)

    if args.update:
        config_path = BASE_DIR / "config" / "stores.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(stores, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] {config_path} 업데이트 완료 ({len(stores)}개 매장)")
    else:
        print("\n--update 플래그를 추가하면 config/stores.json을 자동 업데이트합니다.")
        print("예: python execution/find_stores.py --area 강남 --update")


if __name__ == "__main__":
    main()
