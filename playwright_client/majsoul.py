import threading
import traceback
import queue
import time
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any
from playwright.sync_api import Page
from playwright.sync_api import (
    sync_playwright, Playwright, Browser, Page, WebSocket,
    TimeoutError as PWTimeout,
)

from .bridge import MajsoulBridge
from .logger import logger
from akagi.hooks import register_page
import os
from datetime import datetime
import requests
import os, json, ssl, smtplib
from email.mime.text import MIMEText
from typing import Optional, Tuple
import logging

notify_log = logging.getLogger("akagi.notify")
AKAGI_DEBUG_NOTIFY        = os.getenv("AKAGI_DEBUG_NOTIFY", "0") == "1"
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID              = os.getenv("LINE_USER_ID", "")
_PROOF_DIR = Path("logs/click_proof"); _PROOF_DIR.mkdir(parents=True, exist_ok=True)

def _mask(s: str, show: int = 6) -> str:
    if not s: return ""
    return s[:show] + "..." if len(s) > show else "***"


def send_line_message_api(message: str) -> bool:
    """LINE Messaging API で push 通知を送る（詳細ログ付き）"""
    if not (LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID):
        notify_log.error("[LINE] token or user_id missing")
        return False
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }

    # ログ（トークンは伏せる）
    if AKAGI_DEBUG_NOTIFY:
        notify_log.info(f"[LINE] push -> user={_mask(LINE_USER_ID, 6)} payload={json.dumps(payload, ensure_ascii=False)}")
    else:
        notify_log.info(f"[LINE] push -> user={_mask(LINE_USER_ID, 6)}")

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        ok = (resp.status_code == 200)
        if ok:
            notify_log.info("[LINE] sent OK (200)")
        else:
            notify_log.error(f"[LINE] API error: {resp.status_code} {resp.text[:500]}")
        return ok
    except requests.Timeout:
        notify_log.error("[LINE] timeout")
        return False
    except Exception as e:
        notify_log.exception(f"[LINE] exception: {e}")
        return False

def try_extract_end_result_from_text_frame(payload: str) -> Tuple[Optional[int], Optional[int]]:
    """WS文字列(JSON想定)から (rank, point) を抽出。結果をログ。"""
    try:
        data = json.loads(payload)
    except Exception:
        notify_log.debug("[extract:text] not json")
        return (None, None)

    rank = None; point = None
    rank_keys  = ["rank", "place", "final_rank", "result_rank"]
    point_keys = ["point", "points", "finalPoint", "grade_score", "rating_score", "delta"]

    def walk(obj):
        nonlocal rank, point
        if isinstance(obj, dict):
            t = str(obj.get("type") or obj.get("event") or "").lower()
            if "end" in t or "result" in t:
                for k, v in obj.items():
                    lk = str(k).lower()
                    if rank is None and any(rk in lk for rk in rank_keys):
                        try:
                            r = int(v)
                            if 1 <= r <= 4: rank = r
                        except: pass
                    if point is None and any(pk in lk for pk in point_keys):
                        try:
                            point = int(v)
                        except:
                            try: point = int(float(v))
                            except: pass
            for v in obj.values():
                if rank is not None and point is not None: break
                walk(v)
        elif isinstance(obj, list):
            for it in obj:
                if rank is not None and point is not None: break
                walk(it)

    walk(data)
    notify_log.info(f"[extract:text] rank={rank} point={point}")
    return (rank, point)


def try_extract_end_result_from_parsed_msg(m: dict) -> Tuple[Optional[int], Optional[int]]:
    """bridge.parse() の1要素(dict想定)から (rank, point) を抽出。結果をログ。"""
    if not isinstance(m, dict):
        notify_log.debug("[extract:parsed] not dict")
        return (None, None)
    rank = None; point = None
    for k in ["rank", "place", "final_rank", "result_rank"]:
        if k in m:
            try:
                r = int(m[k])
                if 1 <= r <= 4: rank = r; break
            except: pass
    for k in ["point", "points", "finalPoint", "grade_score", "rating_score", "delta"]:
        if k in m:
            try:
                point = int(m[k])
            except:
                try: point = int(float(m[k]))
                except: pass
            break
    notify_log.info(f"[extract:parsed] rank={rank} point={point}")
    return (rank, point)


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def _snap(page: Page, label: str) -> str:
    """素のスクショ保存"""
    path = _PROOF_DIR / f"{_ts()}_{label}.png"
    page.screenshot(path=str(path))
    logger.info(f"[Proof] screenshot: {path}")
    return str(path)

def _snap_with_marker(page: Page, x: int, y: int, label: str) -> str:
    """
    クリック位置に一時的なマーカー(div)を重ねてスクショ → 即削除。
    これで“どこを押したか”が画像で一目瞭然。
    """
    page.evaluate("""
        ([x, y]) => {
          const id = "__akagi_click_marker__";
          let el = document.getElementById(id);
          if (!el) {
            el = document.createElement('div');
            el.id = id;
            el.style.position = 'fixed';
            el.style.zIndex = 999999;
            el.style.width = '18px';
            el.style.height = '18px';
            el.style.borderRadius = '50%';
            el.style.border = '2px solid red';
            el.style.background = 'rgba(255,0,0,0.25)';
            el.style.pointerEvents = 'none';
            document.body.appendChild(el);
          }
          el.style.left = (x - 9) + 'px';
          el.style.top  = (y - 9) + 'px';
        }
    """, [x, y])
    page.wait_for_timeout(50)
    path = _snap(page, label)
    # 後片付け
    page.evaluate("""
        () => {
          const el = document.getElementById('__akagi_click_marker__');
          if (el && el.parentNode) el.parentNode.removeChild(el);
        }
    """)
    return path


# =========================
# Post-game helpers (module-level)
# =========================

@dataclass
class PostGameButtons:
    # 1600x900 前提の相対座標（Canvas用）。確認は実測ベースでやや下寄せ。
    confirm_rel_x: float = 0.905
    confirm_rel_y: float = 0.928
    play_again_rel_x: float = 0.690
    play_again_rel_y: float = 0.865

# UIテキスト候補（DOMが取れる環境向け。Canvas時は無視される）
NAMES_CONFIRM = [r"確認", r"Confirm", r"确\s*认", r"確認する"]
NAMES_PLAY_AGAIN = [r"もう一局", r"再戦", r"もう一回", r"もう一度", r"Play\s*Again", r"再\s*来\s*一\s*局"]


def _click_rel(page: Page, rx: float, ry: float, delay_ms: int = 80) -> None:
    vp = page.viewport_size or {"width": 1600, "height": 900}
    x = int(vp["width"] * rx)
    y = int(vp["height"] * ry)
    page.mouse.click(x, y)
    page.wait_for_timeout(delay_ms)


def _find_any(page: Page, names: list[str]) -> bool:
    """DOM上にボタンっぽい要素が見えているか（Canvasだと基本 False）"""
    try:
        for nm in names:
            if page.get_by_text(re.compile(nm), exact=False).count() > 0:
                return True
            if page.get_by_role("button", name=re.compile(nm)).count() > 0:
                return True
    except Exception:
        pass
    return False


def _click_dom_button(page: Page, names: list[str], delay_ms: int = 120) -> bool:
    """DOMターゲットを押す（見つからなければ False）"""
    for nm in names:
        try:
            btn = page.get_by_role("button", name=re.compile(nm))
            if btn.count() > 0:
                btn.first.click(timeout=600)
                page.wait_for_timeout(delay_ms)
                return True
        except Exception:
            pass
        try:
            loc = page.get_by_text(re.compile(nm), exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=600)
                page.wait_for_timeout(delay_ms)
                return True
        except Exception:
            pass
    return False


def is_post_game_screen(page: Page) -> bool:
    """“本当に”リザルト～待機画面か（DOMで見えている場合のみ True／Canvasは基本 False）"""
    return _find_any(page, NAMES_CONFIRM) or _find_any(page, NAMES_PLAY_AGAIN)


def _click_cloud(page: Page, rx: float, ry: float, step_px: int = 8, max_px: int = 32, delay_ms: int = 80) -> bool:
    """
    相対座標 (rx, ry) を中心に微小スキャン（Canvas対策）。押せたら True。
    """
    vp = page.viewport_size or {"width": 1600, "height": 900}
    cx, cy = int(vp["width"] * rx), int(vp["height"] * ry)
    offsets = [(0, 0)]
    for r in range(step_px, max_px + 1, step_px):
        offsets.extend([
            ( r, 0), (-r, 0), (0,  r), (0, -r),
            ( r,  r), ( r, -r), (-r,  r), (-r, -r),
        ])
    for dx, dy in offsets:
        page.mouse.click(cx + dx, cy + dy)
        page.wait_for_timeout(delay_ms)
        # 押せた時は画面から確認/もう一局が消えることが多い
        if not is_post_game_screen(page):
            return True
    return False


def click_confirm_strong(page: Page, buttons: PostGameButtons) -> bool:
    """
    確認ボタンを“なんとしても”押す。
    1) DOM, 2) Enter, 3) Canvas微小スキャン, 4) Space
    """
    if _click_dom_button(page, NAMES_CONFIRM, delay_ms=150):
        return True
    try:
        page.keyboard.press("Enter")
        page.wait_for_timeout(250)
        if not is_post_game_screen(page):
            return True
    except Exception:
        pass
    if _click_cloud(page, buttons.confirm_rel_x, buttons.confirm_rel_y, step_px=8, max_px=32, delay_ms=90):
        return True
    try:
        page.keyboard.press("Space")
        page.wait_for_timeout(200)
        if not is_post_game_screen(page):
            return True
    except Exception:
        pass
    return False


def handle_post_game_safe(page: Page, buttons: PostGameButtons = PostGameButtons()) -> bool:
    """
    終局後の 確認→確認→もう一局 を“安全に”押す。
    - DOMが取れれば DOM
    - Canvasなら微小スキャン
    """
    # 1) 確認1
    if not click_confirm_strong(page, buttons):
        return False
    page.wait_for_timeout(600)

    # 2) 確認2（遷移済みならスキップ）
    if is_post_game_screen(page):
        if not click_confirm_strong(page, buttons):
            return False
        page.wait_for_timeout(600)

    # 3) もう一局（DOM優先、無ければ軽い相対クリック補助）
    tries = 0
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if _click_dom_button(page, NAMES_PLAY_AGAIN, delay_ms=120):
            break
        tries += 1
        if tries <= 2:
            _click_rel(page, buttons.play_again_rel_x, buttons.play_again_rel_y, 120)
        page.wait_for_timeout(400)

        # ボタンが消えたら遷移中/開始とみなす
        if not is_post_game_screen(page):
            return True

    # 最終確認：ボタンが見えなければ開始済みとみなす
    return not is_post_game_screen(page)


class PostGameGuard:
    """直近アクティビティ時刻を管理して、一定時間“静止”している時だけ後片付けを許可"""
    def __init__(self) -> None:
        self._last_activity = time.time()

    def bump(self) -> None:
        self._last_activity = time.time()

    def idle_for(self, sec: float) -> bool:
        return (time.time() - self._last_activity) >= sec


# =========================
# PlaywrightController
# =========================

# フロー管理（bridge は既存実装に準拠）
activated_flows: list[str] = []  # store all flow.id ([-1] is the recently opened)
majsoul_bridges: dict[WebSocket, MajsoulBridge] = {}  # store all flow.id -> MajsoulBridge
mjai_messages: queue.Queue[dict] = queue.Queue()  # store all messages


class PlaywrightController:
    """
    A controller for a Playwright browser instance that runs in the main thread.
    It manages a single page, processes commands from a queue, monitors WebSockets,
    and handles clicking based on a normalized 16x9 grid.
    """

    def __init__(self, url: str, width: int = 1600, height: int = 960) -> None:
        """
        Initializes the controller.
        Args:
            url (str): The fixed URL the browser page will navigate to.
        """
        self.url = url
        self.width = width
        self.height = height
        self.command_queue: queue.Queue[dict] = queue.Queue()
        self.running = False

        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.page: Page | None = None

        self.bridge_lock = threading.Lock()
        self._postgame_guard = PostGameGuard()
        self._ended = False  # ← 終局フラグ（WS/解析で True）
        self._started = False  # ← 追加：次の対戦が始まったか
        self._last_end_rank: Optional[int] = None
        self._last_end_point: Optional[int] = None
    # -------------- WebSocket -------------

    def _on_web_socket(self, ws: WebSocket) -> None:
        """Callback for new WebSocket connections."""
        global majsoul_bridges
        logger.info(f"[WebSocket] Connection opened: {ws.url}")

        # Create and store a bridge for this new WebSocket flow
        majsoul_bridges[ws] = MajsoulBridge()

        # Set up listeners for messages and closure on this specific WebSocket instance
        ws.on("framesent", lambda payload: self._on_frame(ws, payload, from_client=True))
        ws.on("framereceived", lambda payload: self._on_frame(ws, payload, from_client=False))
        ws.on("close", lambda: self._on_socket_close(ws))

    def _on_frame(self, ws: WebSocket, payload: str | bytes, from_client: bool) -> None:
        """Callback for WebSocket messages."""
        global mjai_messages, majsoul_bridges

        # アクティビティ更新（ゲームが動いている）
        self._postgame_guard.bump()

        bridge = majsoul_bridges.get(ws)
        if not bridge:
            logger.error(f"[WebSocket] Message from untracked WebSocket: {ws.url}")
            return

        # 文字列フレームに 'end_game' が含まれていれば即フラグ
        try:
            if isinstance(payload, str):
                if ('"type":"end_game"' in payload) or ("'type': 'end_game'" in payload):
                    self._ended = True
                    r, p = try_extract_end_result_from_text_frame(payload)
                    if r is not None: self._last_end_rank = r
                    if p is not None: self._last_end_point = p
                    notify_log.info(f"[ws:text] end_game detected rank={self._last_end_rank} point={self._last_end_point}")
                if ('"type":"start_game"' in payload) or ("'type': 'start_game'" in payload):
                    self._started = True
                    notify_log.info("[ws:text] start_game detected")
        except Exception:
            pass

        try:
            with self.bridge_lock:
                msgs = bridge.parse(payload)
            if msgs:
                for m in msgs:
                    try:
                        if isinstance(m, dict):
                            t = m.get("type")
                            if t == "end_game":
                                self._ended = True
                                r, p = try_extract_end_result_from_parsed_msg(m)
                                if r is not None: self._last_end_rank = r
                                if p is not None: self._last_end_point = p
                                notify_log.info(f"[ws:parsed] end_game detected rank={self._last_end_rank} point={self._last_end_point}")
                            elif t == "start_game":
                                self._started = True
                                notify_log.info("[ws:parsed] start_game detected")
                        mjai_messages.put(m)
                    except Exception:
                        pass
        except Exception:
            logger.error(f"[WebSocket] Error during message parsing: {traceback.format_exc()}")

    def _on_socket_close(self, ws: WebSocket) -> None:
        """Callback for WebSocket closures."""
        global majsoul_bridges
        if ws in majsoul_bridges:
            logger.info(f"[WebSocket] Connection closed: {ws.url}")
            del majsoul_bridges[ws]
        else:
            logger.warning(f"[WebSocket] Untracked WebSocket connection closed: {ws.url}")

    # -------------- Coordinates -------------

    def _get_clickxy(self, x: float, y: float) -> tuple[float | None, float | None]:
        """
        Converts normalized grid coordinates (0-16 for x, 0-9 for y)
        to pixel coordinates based on the current viewport size.
        """
        if not self.page:
            logger.error("Page is not available to get click coordinates.")
            return (None, None)

        viewport_size = self.page.viewport_size
        if not viewport_size:
            logger.error("Could not get viewport size.")
            return (None, None)

        viewport_width = viewport_size["width"]
        viewport_height = viewport_size["height"]

        target_aspect_ratio = 16 / 9
        viewport_aspect_ratio = viewport_width / viewport_height

        rect_width = viewport_width
        rect_height = viewport_height
        offset_x = 0
        offset_y = 0

        # Determine the dimensions of the 16:9 inscribed rectangle
        if viewport_aspect_ratio > target_aspect_ratio:
            # Viewport is wider than 16:9 (letterboxed)
            rect_width = int(viewport_height * target_aspect_ratio)
            offset_x = (viewport_width - rect_width) / 2
        else:
            # Viewport is taller than 16:9 (pillarboxed)
            rect_height = int(viewport_width / target_aspect_ratio)
            offset_y = (viewport_height - rect_height) / 2

        # Normalize grid coordinates (0-16 for x, 0-9 for y)
        if not (0 <= x <= 16 and 0 <= y <= 9):
            logger.warning(f"Click coordinates ({x}, {y}) are outside the 0-16, 0-9 grid.")
            return (None, None)

        # Calculate the absolute pixel coordinates
        click_x = offset_x + (x / 16) * rect_width
        click_y = offset_y + (y / 9) * rect_height
        return (click_x, click_y)

    def _move_mouse(self, click_x: float, click_y: float) -> None:
        """Moves the mouse to the specified pixel coordinates."""
        if not self.page:
            logger.error("Page is not available to move mouse.")
            return
        try:
            logger.info(f"Moving mouse to pixel ({click_x:.2f}, {click_y:.2f})")
            self.page.mouse.move(click_x, click_y)
        except Exception as e:
            logger.error(f"Failed to move mouse: {e}")

    def _click(self, click_x: float, click_y: float) -> None:
        """Clicks at the specified pixel coordinates."""
        if not self.page:
            logger.error("Page is not available to click.")
            return
        try:
            logger.info(f"Clicking at pixel ({click_x:.2f}, {click_y:.2f})")
            self.page.mouse.click(click_x, click_y)
        except Exception as e:
            logger.error(f"Failed to perform click: {e}")
    
    def _wait_started(self, timeout_sec: float = 30.0) -> bool:
        end = time.time() + timeout_sec
        while time.time() < end:
            if self._started:
                return True
            if self.page:
                self.page.wait_for_timeout(200)
        return False


    # -------------- Main loop -------------

    def _process_commands(self) -> None:
        """The main loop to process commands from the queue."""
        while True:
            try:
                command_data = self.command_queue.get_nowait()
                command = command_data.get("command")

                if command == "click":
                    point = command_data.get("point")
                    if point and len(point) == 2:
                        click_x, click_y = self._get_clickxy(point[0], point[1])
                        if click_x is None or click_y is None:
                            logger.error(f"Invalid click coordinates: {point}")
                            continue
                        self._move_mouse(click_x, click_y)
                        if self.page:
                            self.page.wait_for_timeout(100)
                        logger.info(f"Clicking at normalized grid point {point} -> pixel ({click_x:.2f}, {click_y:.2f})")
                        self._click(click_x, click_y)
                    else:
                        logger.error(f"Invalid 'click' command data: {command_data}")

                elif command == "delay":
                    delay = command_data.get("delay", 0)
                    if isinstance(delay, (int, float)) and delay >= 0:
                        logger.info(f"Delaying for {delay} seconds.")
                        if self.page:
                            self.page.wait_for_timeout(int(delay * 1000))
                    else:
                        logger.error(f"Invalid 'delay' command data: {command_data}")

                elif command == "stop":
                    # Clear queue and exit loop
                    while not self.command_queue.empty():
                        self.command_queue.get_nowait()
                    break

                else:
                    logger.warning(f"Unknown command received: {command}")

            except queue.Empty:
                if self.page:
                    self.page.wait_for_timeout(20)
                    try:
                        # 終局フラグが立っており、直近2秒アイドルなら後片付け実行
                        if self._ended and self._postgame_guard.idle_for(2.0):
                            logger.info("[PostGame] handling post-game flow...")
                            # ← どちらか一方を使用
                            # ok = handle_post_game_safe(self.page)
                            # ok = run_fixed_postgame_sequence(self.page)


                            # 本文の作成（rank/point が無ければ“不明”）
                            rank_txt  = f"{self._last_end_rank}位" if self._last_end_rank is not None else "順位: 不明"
                            point_txt = f"{self._last_end_point}pt" if self._last_end_point is not None else "ポイント: 不明"
                            body = (
                                "雀魂 終局\n"
                                f"結果: {rank_txt}\n"
                                f"現在ポイント: {point_txt}\n"
                                f"時刻: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                            )

                            sent = send_line_message_api(body)
                            notify_log.info(f"[notify] sent={sent}")

                            self._started = False
                            run_fixed_postgame_sequence(self.page)

                            # フラグ整理
                            self._ended = False
                            self._postgame_guard.bump()
                        
                    except Exception as e:
                        logger.error(f"[post-game] error: {e}")
                continue

    # -------------- Lifecycle -------------

    def start(self) -> None:
        """
        Starts the Playwright instance, opens the browser, and begins
        the command processing loop.
        """
        logger.info("Controller Starting...")
        self.running = True

        try:
            with sync_playwright() as p:
                self.playwright = p
                self.browser = self.playwright.chromium.launch_persistent_context(
                    user_data_dir=Path().cwd() / "playwright_data",
                    headless=False,
                    viewport={"width": self.width, "height": self.height},
                    ignore_default_args=['--enable-automation'],
                    args=["--noerrdialogs"],
                )

                pages: list[Page] = self.browser.pages
                if not pages:
                    logger.error("No pages found in the browser context.")
                    return
                if len(pages) > 1:
                    for page in pages[1:]:
                        logger.info(f"Closing extra page: {page.url}")
                        page.close()

                self.page = pages[0]
                self.page.on("websocket", self._on_web_socket)

                logger.info(f"Navigating to {self.url}...")
                register_page(self.page)  # hooks: 外部オート等が必要な場合の受け渡し
                self.page.goto(self.url)
                logger.info("Page loaded. Ready for commands.")

                # メインループ開始
                self._process_commands()

        except Exception as e:
            logger.error(f"A critical error occurred during Playwright startup or operation: {e}")
        finally:
            logger.info("Shutting down...")
            self.running = False
            logger.info("Controller Stopped.")

    def stop(self) -> None:
        """Signals the controller to stop and cleans up resources."""
        if self.running:
            logger.info("Sending stop signal...")
            self.command_queue.put({"command": "stop"})
        else:
            logger.info("Controller already stopped.")

    # -------------- Public API -------------

    def click(self, x: float, y: float) -> None:
        """
        Queue a click command on normalized grid (0..16, 0..9).
        """
        if self.running:
            self.command_queue.put({"command": "click", "point": [x, y]})
        else:
            logger.warning("Controller is not running. Cannot queue click command.")

def _ensure_viewport(page: Page, need_w: int, need_h: int) -> None:
    """クリック座標がビューポート外なら、その場で広げる（落下防止）。"""
    vp = page.viewport_size or {"width": 1600, "height": 900}
    cur_w, cur_h = vp["width"], vp["height"]
    new_w = max(cur_w, need_w)
    new_h = max(cur_h, need_h)
    if new_w != cur_w or new_h != cur_h:
        page.set_viewport_size({"width": new_w, "height": new_h})

def run_fixed_postgame_sequence(page: Page) -> None:
    """
    終局 → 10秒 → (1456,929) → 5秒 → (1456,929) → 5秒 → (1223,937) → 5秒 → (666,775)
    それぞれの押下をスクショで証跡化。最後に start_game を WS で検証。
    """
    # 事前スクショ
    # _snap(page, "before_sequence")

    # 30秒待機
    page.wait_for_timeout(30_000)

    # 1回目 確認
    _ensure_viewport(page, need_w=1500+10, need_h=870+10)
    _snap_with_marker(page, 1500, 870, "tap1_marker")
    page.mouse.click(1500, 870)
    page.wait_for_timeout(5_000)
    # _snap(page, "after_tap1")
    # page.wait_for_timeout(5_000)

    # 2回目 確認
    _ensure_viewport(page, need_w=1500+10, need_h=870+10)
    _snap_with_marker(page, 1500, 870, "tap2_marker")
    page.mouse.click(1500, 870)
    page.wait_for_timeout(5_000)
    # _snap(page, "after_tap2")
    # page.wait_for_timeout(5_000)

    # もう一局
    _ensure_viewport(page, need_w=1300+10, need_h=350+10)
    _snap_with_marker(page, 1300, 350, "tap3_marker")
    page.mouse.click(1300, 350)
    page.wait_for_timeout(5_000)
    # _snap(page, "after_tap3")
    # page.wait_for_timeout(5_000)
    # もう一局
    _ensure_viewport(page, need_w=1300+10, need_h=850+10)
    _snap_with_marker(page, 1300, 850, "tap3_marker")
    page.mouse.click(1300, 850)
    page.wait_for_timeout(5_000)
    # _snap(page, "after_tap3")
    # page.wait_for_timeout(5_000)

    # 最後のクリック
    _ensure_viewport(page, need_w=666+10, need_h=700+10)
    _snap_with_marker(page, 666, 700, "tap4_marker")
    page.mouse.click(666, 700)
    # page.wait_for_timeout(5_000)
    # _snap(page, "after_tap4")

    # ここで「対戦開始」を WS で検証（start_game フラグ）
    logger.info("[Proof] waiting for start_game via WS...")
