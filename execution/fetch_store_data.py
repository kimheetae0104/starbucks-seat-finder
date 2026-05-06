#!/usr/bin/env python3
"""
스타벅스 매장 가용성 데이터를 가져온다.
데이터 소스: Naver Map 검색 API (영업 상태) + 시간대별 혼잡도 추정

Usage: python execution/fetch_store_data.py
Output: JSON to stdout
Exit: 0=success, 1=error
"""

import sys
import json
import argparse
import requests
import re
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://map.naver.com/",
}

NAVER_SEARCH_API = "https://map.naver.com/p/api/search/allSearch"


# ── Naver Map 영업 상태 조회 ───────────────────────────────────────────────────

def _fetch_naver_all_stores(stores: list[dict]) -> dict[str, dict]:
    """Playwright로 Naver Map 검색 → 모든 매장 영업 상태 반환. {store_name: item}"""
    from playwright.sync_api import sync_playwright

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ko-KR",
        )
        page = context.new_page()

        def handle_response(response):
            if "allSearch" in response.url and response.status == 200:
                try:
                    data = response.json()
                    items = (data.get("result") or {}).get("place") or {}
                    item_list = items.get("list", [])
                    for item in item_list:
                        name = item.get("name", "")
                        naver_id = item.get("id", "")
                        if naver_id:
                            results[name] = item
                except Exception:
                    pass

        page.on("response", handle_response)

        # 각 매장 검색 (페이지 내에서 검색 트리거)
        for store in stores:
            query = f"스타벅스 {store['name']}점"
            try:
                page.goto(
                    f"https://map.naver.com/v5/search/{requests.utils.quote(query)}",
                    timeout=15000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[WARN] Naver 검색 실패 ({store['name']}): {e}", file=sys.stderr)

        browser.close()

    return results


def _extract_business_status(item: dict) -> dict:
    """Naver 응답에서 영업 상태 추출."""
    bs = item.get("businessStatus", {})
    status = bs.get("status", {})
    code = status.get("code", -1)
    # code: 1=영업준비중, 2=영업중, 3=영업종료, 4=임시휴업
    is_open = code == 2
    text = status.get("text", "알수없음")
    detail = status.get("detailInfo", "")
    return {
        "is_open": is_open,
        "status_code": code,
        "status_text": text,
        "detail": detail,
    }


# ── 시간대별 혼잡도 추정 ──────────────────────────────────────────────────────

PEAK_HOURS = {
    # 요일별 (0=월, 6=일), 시간대별 혼잡도 점수 (0=여유, 1=보통, 2=혼잡)
    "weekday": {  # 월-금
        6: 0, 7: 1, 8: 2, 9: 2,       # 아침 러시
        10: 1, 11: 1,
        12: 2, 13: 2,                   # 점심 러시
        14: 1, 15: 1, 16: 1,
        17: 2, 18: 2, 19: 1,            # 저녁 러시
        20: 1, 21: 0, 22: 0,
    },
    "weekend": {  # 토-일
        9: 0, 10: 1, 11: 2, 12: 2,
        13: 2, 14: 2, 15: 1, 16: 1,
        17: 1, 18: 1, 19: 0, 20: 0,
    },
}

CONGESTION_LABELS = {0: "여유", 1: "보통", 2: "혼잡"}


def _estimate_congestion() -> tuple[str, str]:
    """현재 시각 기반 혼잡도 추정. (congestion_level, congestion_code)"""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=월요일

    table = PEAK_HOURS["weekend"] if weekday >= 5 else PEAK_HOURS["weekday"]
    score = table.get(hour, 0)
    label = CONGESTION_LABELS[score]
    return label, str(score)


# ── Mock 데이터 ───────────────────────────────────────────────────────────────

def _fetch_mock(stores: list[dict]) -> list[dict]:
    import random
    levels = ["여유", "보통", "혼잡"]
    results = []
    for store in stores:
        level = random.choice(levels)
        code = {"여유": "0", "보통": "1", "혼잡": "2"}[level]
        results.append({
            "store_id": str(store["id"]),
            "name": store.get("name", ""),
            "address": store.get("address", ""),
            "congestion_code": code,
            "congestion_level": level,
            "is_open": True,
            "status_text": "영업 중",
            "source": "mock",
        })
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_all(stores: list[dict], use_mock: bool = False) -> list[dict]:
    if use_mock:
        return _fetch_mock(stores)

    congestion_level, congestion_code = _estimate_congestion()

    # Playwright로 Naver Map에서 영업 상태 조회
    naver_map = _fetch_naver_all_stores(stores)

    results = []
    for store in stores:
        store_name = store.get("name", "")

        # 이름 매칭
        naver_item = None
        for key, item in naver_map.items():
            item_short = key.replace("스타벅스 ", "").replace("스타벅스", "").replace("점", "").replace(" ", "")
            store_short = store_name.replace(" ", "")
            if store_short in item_short or item_short in store_short:
                naver_item = item
                break

        if naver_item:
            biz = _extract_business_status(naver_item)
            naver_id = naver_item.get("id", "")
            address = naver_item.get("roadAddress") or naver_item.get("address") or store.get("address", "")
        else:
            biz = {"is_open": True, "status_code": -1, "status_text": "알수없음", "detail": ""}
            naver_id = ""
            address = store.get("address", "")

        results.append({
            "store_id": str(store["id"]),
            "naver_id": naver_id,
            "name": store_name,
            "address": address,
            "is_open": biz["is_open"],
            "status_text": biz["status_text"],
            "status_detail": biz["detail"],
            "congestion_level": congestion_level if biz["is_open"] else "영업 외",
            "congestion_code": congestion_code if biz["is_open"] else "-1",
            "source": "naver_map+heuristic",
        })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-id", help="단일 매장 ID")
    parser.add_argument("--config", default="config/stores.json")
    parser.add_argument("--mock", action="store_true", help="Mock 데이터 사용")
    args = parser.parse_args()

    try:
        with open(BASE_DIR / args.config, encoding="utf-8") as f:
            stores = json.load(f)
    except FileNotFoundError:
        print(f"[ERROR] {args.config} not found", file=sys.stderr)
        sys.exit(1)

    if args.store_id:
        stores = [s for s in stores if str(s["id"]) == args.store_id]
        if not stores:
            stores = [{"id": args.store_id, "name": args.store_id, "address": ""}]

    results = fetch_all(stores, use_mock=args.mock)

    if not results:
        print("[ERROR] 데이터 수집 실패", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
