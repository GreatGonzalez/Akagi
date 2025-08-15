# akagi/auto_next_game_sync.py
import threading
import time
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any
from playwright.sync_api import Page, WebSocket, TimeoutError as PWTimeout

LOG_DIR = Path("logs")
SCREEN_DIR = LOG_DIR / "screens"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SCREEN_DIR.mkdir(parents=True, exist_ok=True)

def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[auto_next][sync] {ts} | {msg}"
    print(line, flush=True)
    try:
        with open(LOG_DIR / "auto_next_game.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

@dataclass
class PostGameButtons:
    # 1600x900前提の相対座標（必要に応じて微調整）
    confirm_rel_x: float = 0.905
    confirm_rel_y: float = 0.922
    play_again_rel_x: float = 0.690
    play_again_rel_y: float = 0.865

# UIテキストの候補（言語差分を吸収：日/英/中の頻出ワード）
NAMES_CONFIRM = [r"確認", r"Confirm", r"确\s*认", r"確認する"]
NAMES_PLAY_AGAIN = [r"もう一局", r"再戦", r"もう一回", r"もう一度", r"Play\s*Again", r"再\s*来\s*一\s*局"]

class PostGameAutomatorSync:
    """
    WSの 'end_game' / 'start_game' が来なくても、
    DOM探索＋相対座標クリック＋定期スクショで
    「確認→確認→もう一局→開始確認」まで押し進める堅牢版。
    """

    def __init__(self, page: Page, buttons: Optional[PostGameButtons] = None) -> None:
        self.page = page
        self.buttons = buttons or PostGameButtons()
        self._evt_lock = threading.Lock()
        self._evt_end_game = False
        self._evt_start_game = False
        self._stop = False

        self._last_ws_seen = time.time()

        # WebSocketログ（テキストで来たら使う）
        self.page.on("websocket", self._on_websocket)

        _log("PostGameAutomatorSync initialized (hardened)")

    # -------------------- WebSocket --------------------
    def _on_websocket(self, ws: WebSocket) -> None:
        _log("WebSocket attached")

        def _recv_text(frame: str) -> None:
            try:
                self._last_ws_seen = time.time()
                if not isinstance(frame, str):
                    return
                if '"type":"end_game"' in frame or "'type': 'end_game'" in frame:
                    _log("WS detected end_game (text)")
                    with self._evt_lock:
                        self._evt_end_game = True
                if '"type":"start_game"' in frame or "'type': 'start_game'" in frame:
                    _log("WS detected start_game (text)")
                    with self._evt_lock:
                        self._evt_start_game = True
            except Exception as e:
                _log(f"WS text parse error: {e}")

        def _recv_data(data: Any) -> None:
            # バイナリ多めなので長さだけログ
            try:
                length = len(data) if hasattr(data, "__len__") else -1
                _log(f"WS binary frame received: {length} bytes")
                self._last_ws_seen = time.time()
            except Exception as e:
                _log(f"WS bin parse error: {e}")

        ws.on("framereceived", _recv_text)
        try:
            ws.on("framedata", _recv_data)
        except Exception:
            pass

    # -------------------- Helpers --------------------
    def _shot(self, name: str) -> None:
        try:
            p = SCREEN_DIR / f"{name}_{int(time.time())}.png"
            self.page.screenshot(path=str(p))
            _log(f"screenshot: {p.name}")
        except Exception as e:
            _log(f"screenshot error: {e}")

    def _click_rel(self, rx: float, ry: float, delay_ms: int = 50) -> None:
        try:
            vp = self.page.viewport_size or {"width": 1600, "height": 900}
            x = int(vp["width"] * rx)
            y = int(vp["height"] * ry)
            self.page.mouse.click(x, y)
            _log(f"click(rel): ({rx:.3f},{ry:.3f}) -> ({x},{y})")
            if delay_ms > 0:
                self.page.wait_for_timeout(delay_ms)
        except Exception as e:
            _log(f"click(rel) error: {e}")

    def _click_dom_button(self, names: list[str], delay_ms: int = 100) -> bool:
        try:
            for nm in names:
                # role=button
                try:
                    btn = self.page.get_by_role("button", name=re.compile(nm))
                    btn.first.click(timeout=500)
                    _log(f"click(dom by role): {nm}")
                    if delay_ms > 0:
                        self.page.wait_for_timeout(delay_ms)
                    return True
                except PWTimeout:
                    pass
                except Exception as e:
                    _log(f"role button click err: {e}")

                # テキスト（div等）
                try:
                    locator = self.page.get_by_text(re.compile(nm), exact=False)
                    locator.first.click(timeout=500)
                    _log(f"click(dom by text): {nm}")
                    if delay_ms > 0:
                        self.page.wait_for_timeout(delay_ms)
                    return True
                except PWTimeout:
                    pass
                except Exception as e:
                    _log(f"text click err: {e}")
        except Exception as e:
            _log(f"_click_dom_button error: {e}")
        return False

    def _wait_flag(self, name: str, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end and not self._stop:
            with self._evt_lock:
                if name == "end_game" and self._evt_end_game:
                    return True
                if name == "start_game" and self._evt_start_game:
                    return True
            time.sleep(0.05)
        return False

    # -------------------- Main: WS + DOM 併用 --------------------
    def run_once(self) -> None:
        _log("run_once: waiting end_game (or DOM) ...")

        # 1) WS待ち（15分）＋並行でDOMも毎秒チェック
        end = time.time() + 15 * 60
        seen_dom = False
        while time.time() < end and not self._stop:
            # WSフラグ判定
            with self._evt_lock:
                if self._evt_end_game:
                    _log("end_game flag set by WS")
                    break

            # DOMで「確認」「もう一局」が見えていたら終局とみなす
            if self._peek_any(NAMES_CONFIRM) or self._peek_any(NAMES_PLAY_AGAIN):
                if not seen_dom:
                    seen_dom = True
                    _log("DOM indicates post-game screen")
                    self._shot("dom_post_game_seen")
                break

            time.sleep(1.0)

        # 見つからなければ諦めて戻る（ループ継続）
        if not (self._evt_end_game or seen_dom):
            _log("timeout/no post-game: continue loop")
            return

        # 2) リザルト→確認1
        self.page.wait_for_timeout(800)
        self._shot("end_result_shown")
        if not self._click_dom_button(NAMES_CONFIRM, 200):
            self._click_rel(self.buttons.confirm_rel_x, self.buttons.confirm_rel_y, 150)
        self.page.wait_for_timeout(800)
        self._shot("after_confirm1")

        # 3) 確認2
        self.page.wait_for_timeout(800)
        if not self._click_dom_button(NAMES_CONFIRM, 200):
            self._click_rel(self.buttons.confirm_rel_x, self.buttons.confirm_rel_y, 150)
        self.page.wait_for_timeout(800)
        self._shot("after_confirm2")

        # 4) もう一局 → start_game待ち（WS or DOM）
        deadline = time.time() + 40.0
        started = False
        tries = 0
        while time.time() < deadline and not started and not self._stop:
            tries += 1
            clicked = self._click_dom_button(NAMES_PLAY_AGAIN, 120)
            if not clicked:
                self._click_rel(self.buttons.play_again_rel_x, self.buttons.play_again_rel_y, 120)

            # WSで開始検知
            if self._wait_flag("start_game", timeout=0.9):
                started = True
                break

            # DOMで開始っぽさを推定（「もう一局」「確認」が消えた / 盤面クリックが通る等は難しいので、ここは軽め）
            if not self._peek_any(NAMES_PLAY_AGAIN) and not self._peek_any(NAMES_CONFIRM):
                # ボタンが消えた＝遷移中/対局開始の可能性が高い
                self.page.wait_for_timeout(600)
                if not self._peek_any(NAMES_PLAY_AGAIN) and not self._peek_any(NAMES_CONFIRM):
                    started = True
                    break

            if tries % 3 == 1:
                self._shot(f"after_play_again_try{tries}")

        if started:
            _log("next game likely started")
            self._shot("next_game_started")
        else:
            _log("failed to detect start -> extra clicks & final shot")
            for _ in range(5):
                self._click_dom_button(NAMES_PLAY_AGAIN, 120)
                self._click_rel(self.buttons.play_again_rel_x, self.buttons.play_again_rel_y, 120)
                if self._wait_flag("start_game", timeout=0.9):
                    _log("late start detected by WS")
                    break
            self._shot("next_game_start_timeout")

        # 次回へ向けてWSフラグをクリア
        with self._evt_lock:
            self._evt_end_game = False
            self._evt_start_game = False

    def run_forever(self) -> None:
        _log("run_forever: started")
        # 補助の定期スクショ（30秒に1枚）
        threading.Thread(target=self._heartbeat_screens, daemon=True).start()
        while not self._stop:
            try:
                self.run_once()
            except Exception as e:
                _log(f"loop error: {e}")
                time.sleep(1.0)

    def stop(self) -> None:
        self._stop = True

    # -------------------- Utilities --------------------
    def _peek_any(self, names: list[str]) -> bool:
        try:
            for nm in names:
                loc = self.page.get_by_text(re.compile(nm), exact=False)
                if loc.count() > 0:
                    return True
        except Exception:
            pass
        return False

    def _heartbeat_screens(self):
        while not self._stop:
            try:
                self._shot("hb")
            except Exception:
                pass
            time.sleep(30)
