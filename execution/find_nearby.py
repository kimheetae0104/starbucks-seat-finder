#!/usr/bin/env python3
"""
사용자 좌표 기준 주변 스타벅스 탐색 + 혼잡도 추정.

Usage: python execution/find_nearby.py --lat 37.497912 --lng 127.027619 [--radius 500]
Output: JSON to stdout
"""

import sys
import json
import argparse
import requests
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}


def find_nearby_starbucks(lat: float, lng: float, radius_m: int = 500) -> list[dict]:
    """좌표 기반 주변 스타벅스 탐색. 거리순 정렬."""
    from playwright.sync_api import sync_playwright

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ko-KR",
            geolocation={"latitude": lat, "longitude": lng},
            permissions=["geolocation"],
        )
        page = context.new_page()

        def handle_response(response):
            if "allSearch" in response.url and response.status == 200:
                try:
                    data = response.json()
                    items = (data.get("result") or {}).get("place") or {}
                    for item in items.get("list", []):
                        name = item.get("name", "")
                        if "스타벅스" not in name:
                            continue
                        dist = float(item.get("distance") or 9999)
                        if dist > radius_m:
                            continue
                        bs = item.get("businessStatus", {})
                        status = bs.get("status", {})
                        results.append({
                            "naver_id": item.get("id", ""),
                            "name": name.replace("스타벅스 ", "").replace("점", ""),
                            "full_name": name,
                            "address": item.get("roadAddress") or item.get("address", ""),
                            "distance_m": int(dist),
                            "is_open": status.get("code") == 2,
                            "status_text": status.get("text", "알수없음"),
                            "status_detail": status.get("detailInfo", ""),
                        })
                except Exception:
                    pass

        page.on("response", handle_response)

        url = f"https://map.naver.com/v5/search/스타벅스?c={lng},{lat},15,0,0,0,dh"
        try:
            with page.expect_response(
                lambda r: "allSearch" in r.url and r.status == 200,
                timeout=10000,
            ):
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[WARN] Naver 검색 실패: {e}", file=sys.stderr)

        browser.close()

    results.sort(key=lambda x: x["distance_m"])
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lng", type=float, required=True)
    parser.add_argument("--radius", type=int, default=500, help="탐색 반경 (미터, 기본 500)")
    args = parser.parse_args()

    stores = find_nearby_starbucks(args.lat, args.lng, args.radius)
    print(json.dumps(stores, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
