# akagi/auto_next_game.py
import asyncio
import time
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

from playwright.async_api import Page, WebSocket, TimeoutError as PWTimeout

LOG_DIR = Path("logs")
SCREEN_DIR = LOG_DIR / "screens"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SCREEN_DIR.mkdir(parents=True, exist_ok=True)

def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[auto_next] {ts} | {msg}"
    print(line, flush=True)
    try:
        with open(LOG_DIR / "auto_next_game.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

@dataclass
class PostGameButtons:
    # 相対座標（1600x900想定）。ズレる場合は後で微調整してください。
    confirm_rel_x: float = 0.905
    confirm_rel_y: float = 0.922
    play_again_rel_x: float = 0.690
    play_again_rel_y: float = 0.865

class PostGameAutomator:
    """
    WSの 'end_game' / 'start_game' を見つつ、
    DOMでも「確認」「もう一局」を探索して押下。各段階でスクショ・ログを残す。
    """
    def __init__(self, page: Page, buttons: Optional[PostGameButtons] = None) -> None:
        self.page = page
        self.buttons = buttons or PostGameButtons()
        self._evt_q: asyncio.Queue[str] = asyncio.Queue()
        self._started_flag = False

        # WS監視
        self.page.on("websocket", self._on_websocket)
        # コンソール/エラーログも拾う
        self.page.on("console", lambda m: _log(f"[console] {m.type().upper()}: {m.text()}"))
        self.page.on("pageerror", lambda e: _log(f"[pageerror] {e}"))

        _log("PostGameAutomator initialized")

    # -------------------- WebSocket --------------------
    def _on_websocket(self, ws: WebSocket) -> None:
        _log("WebSocket attached")
        def _recv_text(frame: str) -> None:
            try:
                if not isinstance(frame, str):
                    return
                if '"type":"end_game"' in frame or "'type': 'end_game'" in frame:
                    _log("WS detected end_game (text)")
                    self._evt_q.put_nowait("end_game")
                if '"type":"start_game"' in frame or "'type': 'start_game'" in frame:
                    _log("WS detected start_game (text)")
                    self._evt_q.put_nowait("start_game")
            except Exception as e:
                _log(f"WS text parse error: {e}")

        def _recv_data(data: Any) -> None:
            # バイナリも来る可能性があるので、長さだけログ
            try:
                length = len(data) if hasattr(data, "__len__") else -1
                _log(f"WS binary frame received: {length} bytes")
                # ここではデコードまでしない（重いので）。将来のためプレースホルダ。
            except Exception as e:
                _log(f"WS bin parse error: {e}")

        ws.on("framereceived", _recv_text)
        # Playwrightはbinaryは framedata になる
        try:
            ws.on("framedata", _recv_data)   # 型によっては無い環境もある
        except Exception:
            pass

    async def _wait_event(self, want: str, timeout: float) -> bool:
        try:
            while True:
                got = await asyncio.wait_for(self._evt_q.get(), timeout=timeout)
                if got == want:
                    return True
        except asyncio.TimeoutError:
            return False

    # -------------------- Helpers --------------------
    async def _shot(self, name: str) -> None:
        try:
            p = SCREEN_DIR / f"{name}_{int(time.time())}.png"
            await self.page.screenshot(path=str(p))
            _log(f"screenshot: {p.name}")
        except Exception as e:
            _log(f"screenshot error: {e}")

    async def _click_rel(self, rx: float, ry: float, delay: float = 0.05) -> None:
        try:
            vp = self.page.viewport_size or {"width": 1600, "height": 900}
            x = int(vp["width"] * rx)
            y = int(vp["height"] * ry)
            await self.page.mouse.click(x, y)
            _log(f"click(rel): ({rx:.3f},{ry:.3f}) -> ({x},{y})")
            await asyncio.sleep(delay)
        except Exception as e:
            _log(f"click(rel) error: {e}")

    # DOMでボタン探索してクリック（見つかったらTrue）
    async def _click_dom_button(self, names: list[str], delay: float = 0.1) -> bool:
        # 複数パターン（「確認」「もう一局」「Confirm」「Play Again」など）に対応
        try:
            for nm in names:
                # 1) role=button から
                btn = self.page.get_by_role("button", name=re.compile(nm))
                try:
                    await btn.first.click(timeout=500)
                    _log(f"click(dom by role): {nm}")
                    await asyncio.sleep(delay)
                    return True
                except PWTimeout:
                    pass
                except Exception as e:
                    _log(f"role button click err: {e}")

                # 2) テキスト一致（divなどの擬似ボタン想定）
                locator = self.page.get_by_text(re.compile(nm), exact=False)
                try:
                    await locator.first.click(timeout=500)
                    _log(f"click(dom by text): {nm}")
                    await asyncio.sleep(delay)
                    return True
                except PWTimeout:
                    pass
                except Exception as e:
                    _log(f"text click err: {e}")
        except Exception as e:
            _log(f"_click_dom_button error: {e}")
        return False

    # -------------------- Main Flow --------------------
    async def wait_and_queue_next(self) -> None:
        _log("wait_and_queue_next: waiting end_game ...")
        got = await self._wait_event("end_game", timeout=60*60)
        if not got:
            _log("timeout: no end_game event")
            return

        _log("end_game detected. waiting result screen 1s")
        await asyncio.sleep(1.0)
        await self._shot("end_result_shown")

        # === 確認(1) ===
        _log("try confirm #1 (DOM first)")
        clicked = await self._click_dom_button(
            names=[r"確認", r"Confirm"]
        )
        if not clicked:
            _log("DOM not found -> click by relative coord")
            await self._click_rel(self.buttons.confirm_rel_x, self.buttons.confirm_rel_y)
        await asyncio.sleep(1.0)
        await self._shot("after_confirm1")

        # === 確認(2)（画面遷移待ち）===
        _log("wait 1.0s then confirm #2")
        await asyncio.sleep(1.0)
        clicked = await self._click_dom_button(names=[r"確認", r"Confirm"])
        if not clicked:
            await self._click_rel(self.buttons.confirm_rel_x, self.buttons.confirm_rel_y)
        await asyncio.sleep(1.0)
        await self._shot("after_confirm2")

        # === もう一局 ===
        _log("try play-again (DOM preferred) and wait start_game")
        # 取りこぼし回避で数回トライ
        names_play_again = [r"もう一局", r"もう一回", r"Play\s*Again", r"再戦", r"もう一度"]
        deadline = time.monotonic() + 40.0
        started = False
        attempts = 0
        while time.monotonic() < deadline and not started:
            attempts += 1
            # 1) DOMトライ
            clicked = await self._click_dom_button(names_play_again, delay=0.2)
            if not clicked:
                # 2) 座標クリック連打
                await self._click_rel(self.buttons.play_again_rel_x, self.buttons.play_again_rel_y, delay=0.1)
                await asyncio.sleep(0.4)

            started = await self._wait_event("start_game", timeout=0.8)
            if attempts % 3 == 1:
                await self._shot(f"after_play_again_try{attempts}")

        if started:
            _log("start_game detected.")
            await self._shot("next_game_started")
        else:
            _log("start_game not detected -> final shots & extra clicks")
            # 最後の保険クリック
            for _ in range(5):
                await self._click_dom_button(names_play_again, delay=0.2)
                await self._click_rel(self.buttons.play_again_rel_x, self.buttons.play_again_rel_y, delay=0.1)
                if await self._wait_event("start_game", timeout=0.8):
                    _log("start_game detected (late).")
                    break
            await self._shot("next_game_start_timeout")

    async def auto_queue_forever(self) -> None:
        _log("auto_queue_forever: started")
        # WSイベントが拾えないケースに備えて、定期的にDOMを覗いて押す安全網も用意
        asyncio.create_task(self._dom_watchdog())
        while True:
            try:
                await self.wait_and_queue_next()
            except Exception as e:
                _log(f"loop error: {e}")
                await asyncio.sleep(1.0)

    async def _dom_watchdog(self) -> None:
        """常時、終局後っぽい画面をDOMで検知し、スクショも落とす"""
        # watchdogは1〜1.5秒周期
        while True:
            try:
                # 「確認」「もう一局」が見えていたらスクショ + 軽くクリックしてみる
                found_confirm = await self._try_peek([r"確認", r"Confirm"])
                found_again = await self._try_peek([r"もう一局", r"再戦", r"Play\s*Again"])
                if found_confirm or found_again:
                    await self._shot("watchdog_seen_buttons")
                    # クリックは強すぎると誤爆するので、watchdog側は1回だけ
                    if found_again:
                        await self._click_dom_button([r"もう一局", r"再戦", r"Play\s*Again"])
                await asyncio.sleep(1.2)
            except Exception as e:
                _log(f"watchdog error: {e}")
                await asyncio.sleep(1.5)

    async def _try_peek(self, names: list[str]) -> bool:
        try:
            for nm in names:
                loc = self.page.get_by_text(re.compile(nm), exact=False)
                if await loc.count() > 0:
                    return True
        except Exception:
            pass
        return False
