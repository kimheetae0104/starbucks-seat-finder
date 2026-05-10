#!/usr/bin/env python3
"""
위치 기반 스타벅스 자리 찾기 Telegram 봇.

사용법:
  1. 봇에게 위치 공유 → 주변 스타벅스 혼잡도 즉시 응답
  2. /nearby [주소] → 특정 장소 주변 탐색
  3. /help → 사용법

Usage: python execution/telegram_bot.py
"""

import sys
import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "execution"))

load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"

LEVEL_EMOJI = {"여유": "🟢", "보통": "🟡", "혼잡": "🔴", "영업 외": "⚫"}
DEFAULT_RADIUS = int(os.getenv("NEARBY_RADIUS_M", "500"))
MAX_RADIUS = 2000
RADIUS_STEPS = [500, 1000, 2000]

# 날씨 캐시 (5분 TTL)
_weather_cache: dict = {"ts": 0, "mod": 0, "desc": ""}


# ── Telegram API helpers ──────────────────────────────────────────────────────

def send_message(chat_id: str | int, text: str, parse_mode: str = "HTML",
                 reply_markup: dict | None = None) -> bool:
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = requests.post(f"{API}/sendMessage", json=payload, timeout=10)
        return resp.ok
    except Exception as e:
        print(f"[ERROR] 메시지 전송 실패: {e}", file=sys.stderr)
        return False


def send_typing(chat_id: str | int) -> None:
    try:
        requests.post(f"{API}/sendChatAction",
                      json={"chat_id": chat_id, "action": "typing"}, timeout=5)
    except Exception:
        pass


def get_updates(offset: int = 0) -> list[dict]:
    try:
        resp = requests.get(f"{API}/getUpdates",
                            params={"timeout": 30, "offset": offset}, timeout=35)
        return resp.json().get("result", [])
    except Exception:
        return []


def location_keyboard() -> dict:
    """위치 공유 버튼이 있는 Reply Keyboard."""
    return {
        "keyboard": [[{"text": "📍 현재 위치 공유", "request_location": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def remove_keyboard() -> dict:
    return {"remove_keyboard": True}


# ── 위치 + 스타벅스 통합 검색 (Playwright 1회) ───────────────────────────────

def search_starbucks(lat: float | None, lng: float | None,
                     address: str | None, radius_m: int) -> tuple[list[dict], float | None, float | None]:
    """
    좌표 또는 주소로 주변 스타벅스 탐색.
    주소가 주어지면 geocode 후 탐색 — Playwright 1번만 사용.
    반환: (stores, lat, lng)
    """
    from playwright.sync_api import sync_playwright

    results = []
    found_coords: dict = {}

    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        ctx_kwargs = {"user_agent": USER_AGENT, "locale": "ko-KR"}
        if lat and lng:
            ctx_kwargs["geolocation"] = {"latitude": lat, "longitude": lng}
            ctx_kwargs["permissions"] = ["geolocation"]

        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        def handle_response(response):
            if "allSearch" not in response.url or response.status != 200:
                return
            try:
                data = response.json()
                place = (data.get("result") or {}).get("place") or {}
                items = place.get("list", [])

                # 주소 geocode 단계: 좌표가 없으면 첫 결과에서 추출
                if not found_coords and address:
                    if items:
                        x = float(items[0].get("x") or 0)
                        y = float(items[0].get("y") or 0)
                        if x and y:
                            found_coords["lat"] = y
                            found_coords["lng"] = x

                # 스타벅스 필터링
                for item in items:
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

        if address:
            # 1단계: 주소 검색 → 좌표 획득
            url = f"https://map.naver.com/v5/search/{requests.utils.quote(address)}"
            try:
                with page.expect_response(
                    lambda r: "allSearch" in r.url and r.status == 200, timeout=8000
                ):
                    page.goto(url, timeout=12000, wait_until="domcontentloaded")
            except Exception:
                pass

            if found_coords:
                lat = found_coords["lat"]
                lng = found_coords["lng"]

        if lat and lng:
            # 2단계: 좌표 기반 스타벅스 탐색
            url = f"https://map.naver.com/v5/search/스타벅스?c={lng},{lat},15,0,0,0,dh"
            try:
                with page.expect_response(
                    lambda r: "allSearch" in r.url and r.status == 200, timeout=8000
                ):
                    page.goto(url, timeout=12000, wait_until="domcontentloaded")
            except Exception:
                pass

        browser.close()

    results.sort(key=lambda x: x["distance_m"])
    return results, lat, lng


# ── 날씨 캐시 (5분 TTL) ───────────────────────────────────────────────────────

def _get_weather_mod() -> tuple[int, str]:
    global _weather_cache
    if time.time() - _weather_cache["ts"] < 300:
        return _weather_cache["mod"], _weather_cache["desc"]
    try:
        from fetch_store_data import _fetch_weather, _weather_modifier, AREA_LCODE
        weather = _fetch_weather(AREA_LCODE["default"])
        mod = _weather_modifier(weather)
        desc = weather.get("description", "")
        _weather_cache = {"ts": time.time(), "mod": mod, "desc": desc}
        return mod, desc
    except Exception:
        return 0, ""


# ── 혼잡도 추정 ───────────────────────────────────────────────────────────────

def _congestion(store: dict) -> str:
    if not store["is_open"]:
        return "영업 외"
    from fetch_store_data import _estimate_congestion
    weather_mod, _ = _get_weather_mod()
    level, _ = _estimate_congestion(store["name"], weather_mod)
    return level


# ── 메시지 포맷 ───────────────────────────────────────────────────────────────

def format_result(stores: list[dict], origin: str, radius_m: int) -> str:
    _, weather_desc = _get_weather_mod()
    weather_line = f" · {weather_desc}" if weather_desc else ""

    if not stores:
        return (
            f"😔 <b>{origin}</b> 주변 {radius_m}m 내 스타벅스가 없어요.\n\n"
            f"더 넓은 범위로 검색하려면:\n<code>/nearby {origin}</code>"
        )

    header = f"☕ <b>{origin}</b> 주변 스타벅스{weather_line}\n\n"
    lines = []
    for s in stores[:8]:
        level = _congestion(s)
        emoji = LEVEL_EMOJI.get(level, "⚪")
        dist = s["distance_m"]
        dist_str = f"{dist}m" if dist < 1000 else f"{dist/1000:.1f}km"
        note = f" · {s['status_detail']}" if s.get("status_detail") else ""
        lines.append(
            f"{emoji} <b>{s['name']}</b> <i>({dist_str})</i>\n"
            f"   {level}{note}"
        )

    footer = "\n\n🔄 <i>시간대·날씨 기반 예측 (실시간 좌석 수 아님)</i>"
    return header + "\n\n".join(lines) + footer


# ── 업데이트 핸들러 ───────────────────────────────────────────────────────────

def handle_nearby(chat_id: int, lat: float | None, lng: float | None,
                  address: str | None, origin_label: str) -> None:
    """위치 또는 주소로 주변 스타벅스 탐색 → 자동 반경 확장."""
    radius = DEFAULT_RADIUS
    stores = []

    for radius in RADIUS_STEPS:
        stores, lat, lng = search_starbucks(lat, lng, address, radius)
        address = None  # 두 번째 시도부터는 좌표 재사용
        if stores:
            break

    radius_label = f"{radius}m" if radius < 1000 else f"{radius//1000}km"
    origin = f"{origin_label} ({radius_label})"
    reply = format_result(stores, origin, radius)
    send_message(chat_id, reply, reply_markup=location_keyboard())


def handle_update(update: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    location = msg.get("location")

    # 위치 공유
    if location:
        lat, lng = location["latitude"], location["longitude"]
        send_typing(chat_id)
        handle_nearby(chat_id, lat, lng, None, "현재 위치")
        return

    if not text:
        return

    cmd = text.split()[0].split("@")[0].lower()

    if cmd == "/start":
        send_message(chat_id,
            "☕ <b>스타벅스 자리 찾기</b>\n\n"
            "아래 버튼으로 현재 위치를 공유하거나,\n"
            "<b>/nearby 강남역</b> 처럼 장소명으로 검색하세요.\n\n"
            "🟢 여유  🟡 보통  🔴 혼잡  ⚫ 영업종료",
            reply_markup=location_keyboard(),
        )
        return

    if cmd == "/help":
        send_message(chat_id,
            "📖 <b>사용법</b>\n\n"
            "📍 <b>위치 공유</b> — 버튼 한 번으로 주변 탐색\n"
            "🔍 <b>/nearby [장소명]</b> — 특정 장소 주변 탐색\n"
            "   예: <code>/nearby 홍대입구역</code>\n\n"
            "반경 500m → 1km → 2km 순서로 자동 확장합니다.\n\n"
            "<i>혼잡도는 시간대·날씨 기반 예측입니다.</i>",
            reply_markup=location_keyboard(),
        )
        return

    if cmd == "/nearby":
        parts = text.split(maxsplit=1)
        address = parts[1].strip() if len(parts) > 1 else ""
        if not address:
            send_message(chat_id,
                "📍 장소명을 입력해주세요.\n예: <code>/nearby 홍대입구역</code>")
            return
        send_typing(chat_id)
        send_message(chat_id, f"🔍 <b>{address}</b> 근처 스타벅스 찾는 중...")
        handle_nearby(chat_id, None, None, address, address)
        return

    # 일반 텍스트
    send_message(chat_id,
        "📍 위치를 공유하거나 <code>/nearby 장소명</code> 으로 검색해보세요.",
        reply_markup=location_keyboard(),
    )


# ── 메인 루프 ─────────────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    me = requests.get(f"{API}/getMe", timeout=10).json()
    bot_name = me.get("result", {}).get("username", "unknown")
    print(f"[OK] @{bot_name} 시작 (반경 자동확장: {RADIUS_STEPS}m)")
    print("Ctrl+C로 중단\n")

    offset = 0
    while True:
        try:
            updates = get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception as e:
                    print(f"[ERROR] {e}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\n[INFO] 봇 종료")
            break
        except Exception as e:
            print(f"[ERROR] getUpdates: {e}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
