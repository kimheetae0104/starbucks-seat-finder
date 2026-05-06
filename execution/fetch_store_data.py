#!/usr/bin/env python3
"""
스타벅스 코리아 매장 혼잡도 데이터를 가져온다.
전략: Starbucks API 먼저 시도 → 실패 시 Playwright 브라우저 스크래핑 폴백

Usage: python execution/fetch_store_data.py [--store-id 1077]
Output: JSON to stdout
Exit: 0=success, 1=error
"""

import sys
import json
import argparse
import time
import requests
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.starbucks.co.kr/store/store_map.do",
}

CONGESTION_MAP = {
    "0": "여유", "1": "보통", "2": "혼잡", "3": "매우혼잡",
    "여유": "여유", "보통": "보통", "혼잡": "혼잡", "매우혼잡": "매우혼잡",
}


# ── Approach A: Starbucks Korea Official API ──────────────────────────────────

def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get("https://www.starbucks.co.kr/store/store_map.do", timeout=10)
    except Exception:
        pass
    return session


def _fetch_via_api(store: dict, session: requests.Session) -> dict | None:
    try:
        r = session.post(
            "https://www.starbucks.co.kr/store/getStore.do",
            data={"disp": "N", "in_biz_cd": "", "in_scodes": ""},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        stores = data.get("list", [])
        for s in stores:
            if str(s.get("seq", "")) == str(store["id"]):
                congestion_code = str(s.get("congestCd", s.get("CONGEST_CD", "-1")))
                return {
                    "store_id": str(store["id"]),
                    "name": store.get("name", s.get("s_name", "")),
                    "address": store.get("address", s.get("s_addr1", "")),
                    "congestion_code": congestion_code,
                    "congestion_level": CONGESTION_MAP.get(congestion_code, "알수없음"),
                    "source": "starbucks_api",
                }
    except Exception:
        pass
    return None


# ── Approach B: Playwright Browser Scraping ───────────────────────────────────

def _fetch_via_playwright(stores: list[dict]) -> list[dict]:
    from playwright.sync_api import sync_playwright

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ko-KR",
        )
        page = context.new_page()

        captured = {}

        def handle_response(response):
            if "getStore" in response.url and response.status == 200:
                try:
                    body = response.json()
                    store_list = body.get("list", [])
                    for s in store_list:
                        sid = str(s.get("seq", s.get("s_seq", "")))
                        if sid:
                            captured[sid] = s
                except Exception:
                    pass

        page.on("response", handle_response)

        try:
            page.goto("https://www.starbucks.co.kr/store/store_map.do", timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[WARN] 페이지 로드 실패: {e}", file=sys.stderr)

        for store in stores:
            sid = str(store["id"])
            if sid in captured:
                s = captured[sid]
                congestion_code = str(s.get("congestCd", s.get("CONGEST_CD", "-1")))
                results.append({
                    "store_id": sid,
                    "name": store.get("name", s.get("s_name", "")),
                    "address": store.get("address", s.get("s_addr1", "")),
                    "congestion_code": congestion_code,
                    "congestion_level": CONGESTION_MAP.get(congestion_code, "알수없음"),
                    "source": "playwright",
                })
            else:
                # 직접 검색 시도
                try:
                    captured.clear()
                    page.evaluate(f"""
                        fetch('/store/getStore.do', {{
                            method: 'POST',
                            headers: {{'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'}},
                            body: 'disp=N&in_biz_cd=&in_scodes='
                        }}).then(r => r.json()).then(d => window.__sbResult = d);
                    """)
                    page.wait_for_timeout(2000)
                    result_data = page.evaluate("window.__sbResult || {}")
                    store_list = result_data.get("list", []) if isinstance(result_data, dict) else []
                    for s in store_list:
                        if str(s.get("seq", "")) == sid:
                            congestion_code = str(s.get("congestCd", "-1"))
                            results.append({
                                "store_id": sid,
                                "name": store.get("name", ""),
                                "address": store.get("address", ""),
                                "congestion_code": congestion_code,
                                "congestion_level": CONGESTION_MAP.get(congestion_code, "알수없음"),
                                "source": "playwright_fetch",
                            })
                            break
                except Exception as e:
                    print(f"[WARN] store {sid} playwright fetch 실패: {e}", file=sys.stderr)

        browser.close()

    return results


# ── Fallback: Mock data (dev/test용) ─────────────────────────────────────────

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
            "source": "mock",
        })
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_all(stores: list[dict], use_mock: bool = False) -> list[dict]:
    if use_mock:
        return _fetch_mock(stores)

    # Try API first
    session = _get_session()
    api_results = []
    for store in stores:
        result = _fetch_via_api(store, session)
        if result:
            api_results.append(result)
        time.sleep(0.3)

    if api_results:
        return api_results

    # Fallback: Playwright
    print("[INFO] API 실패, Playwright 스크래핑으로 전환...", file=sys.stderr)
    playwright_results = _fetch_via_playwright(stores)

    if playwright_results:
        return playwright_results

    print("[WARN] 모든 데이터 소스 실패. Mock 데이터 사용", file=sys.stderr)
    return _fetch_mock(stores)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-id", help="단일 매장 ID")
    parser.add_argument("--config", default="config/stores.json")
    parser.add_argument("--mock", action="store_true", help="Mock 데이터 사용 (테스트용)")
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
