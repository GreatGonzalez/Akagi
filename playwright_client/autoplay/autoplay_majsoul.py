import os
import time
import json
import random
import math
from .logger import logger
from .util import Point
from settings.settings import settings

from functools import cmp_to_key
from mjai_bot.bot import AkagiBot


# ---- Tuning knobs (env overridable) ----
def _getf(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None else default
    except Exception:
        return default

def _geti(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v is not None else default
    except Exception:
        return default


# --- Waits ---
NAKI_PREWAIT = _getf("AKAGI_NAKI_PREWAIT", 2.00)
AKAGI_REACH_WAIT = _getf("AKAGI_REACH_WAIT", 1.00)
AKAGI_RON_WAIT = _getf("AKAGI_RON_WAIT", 1.00)
AKAGI_TSUMO_WAIT = _getf("AKAGI_TSUMO_WAIT", 1.00)
NAKI_BUTTON_WAIT = _getf("AKAGI_NAKI_BUTTON_WAIT", 0.50)
NAKI_CAND_WAIT = _getf("AKAGI_NAKI_CAND_WAIT", 0.25)
NAKI_DOUBLE_CLICK = _geti("AKAGI_NAKI_DOUBLE_CLICK", 0)
NAKI_SINGLE_WAIT = _getf("AKAGI_NAKI_SINGLE_WAIT", NAKI_CAND_WAIT)
NAKI_NONE_PREWAIT = _getf("AKAGI_NAKI_NONE_PREWAIT", 0.15)
AKAGI_OYA_FIRST_DAHAI_EXTRA = _getf("AKAGI_OYA_FIRST_DAHAI_EXTRA", 2.00)

# --- Tenpai bias ---
AKAGI_TENPAI_BIAS_ENABLE = _geti("AKAGI_TENPAI_BIAS_ENABLE", 1)
AKAGI_TENPAI_BIAS_OYA_SHANTEN2 = _geti("AKAGI_TENPAI_BIAS_OYA_SHANTEN2", 1)

# --- Naki safety (simple & strong) ---
AKAGI_NAKI_SAFETY_ENABLE = _geti("AKAGI_NAKI_SAFETY_ENABLE", 1)
AKAGI_NAKI_SAFETY_JUNME_TIGHT = _geti("AKAGI_NAKI_SAFETY_JUNME_TIGHT", 9)  # earlier endgame
AKAGI_NAKI_SAFETY_MIN_ANPAI = _geti("AKAGI_NAKI_SAFETY_MIN_ANPAI", 3)      # need >=3 safe tiles late

# --- Fold mode (simplified) ---
AKAGI_FOLD_ENABLE = _geti("AKAGI_FOLD_ENABLE", 1)
AKAGI_FOLD_SHANTEN_THRESH = _geti("AKAGI_FOLD_SHANTEN_THRESH", 3)
AKAGI_FOLD_BADNESS_SCORE_THRESH = _geti("AKAGI_FOLD_BADNESS_SCORE_THRESH", 7)
AKAGI_FOLD_EARLY_JUNME = _geti("AKAGI_FOLD_EARLY_JUNME", 7)
AKAGI_FOLD_RELEASE_SHANTEN = _geti("AKAGI_FOLD_RELEASE_SHANTEN", 1)
AKAGI_FOLD_FORCE_ON_RIICHI = _geti("AKAGI_FOLD_FORCE_ON_RIICHI", 1)

# --- Oya endgame push (no KAN paths at all) ---
AKAGI_OYA_ENDGAME_PUSH_ENABLE = _geti("AKAGI_OYA_ENDGAME_PUSH_ENABLE", 1)
AKAGI_OYA_ENDGAME_JUNME = _geti("AKAGI_OYA_ENDGAME_JUNME", 11)
AKAGI_OYA_ENDGAME_ALLOW_SHANTEN2 = _geti("AKAGI_OYA_ENDGAME_ALLOW_SHANTEN2", 1)
AKAGI_OYA_ENDGAME_MIN_ANPAI = _geti("AKAGI_OYA_ENDGAME_MIN_ANPAI", 1)
AKAGI_OYA_ENDGAME_ALLOW_CHI_PON = _geti("AKAGI_OYA_ENDGAME_ALLOW_CHI_PON", 1)

# --- Anti-Last (no KAN paths at all) ---
AKAGI_ANTI_LAST_ENABLE = _geti("AKAGI_ANTI_LAST_ENABLE", 1)
AKAGI_ANTI_LAST_JUNME = _geti("AKAGI_ANTI_LAST_JUNME", 12)
AKAGI_ANTI_LAST_GAP_MIN = _geti("AKAGI_ANTI_LAST_GAP_MIN", 5000)
AKAGI_ANTI_LAST_AT_RISK_LEAD = _geti("AKAGI_ANTI_LAST_AT_RISK_LEAD", 3000)
AKAGI_ANTI_LAST_ALLOW_REACH = _geti("AKAGI_ANTI_LAST_ALLOW_REACH", 1)
AKAGI_ANTI_LAST_ALLOW_CHI_PON = _geti("AKAGI_ANTI_LAST_ALLOW_CHI_PON", 1)
AKAGI_ANTI_LAST_ALLOW_CHILD_SHANTEN2 = _geti("AKAGI_ANTI_LAST_ALLOW_CHILD_SHANTEN2", 1)

# --- Score policy ---
AKAGI_SCOREPOLICY_ENABLE = _geti("AKAGI_SCOREPOLICY_ENABLE", 1)
AKAGI_TOP_EXTRA_ANPAI = _geti("AKAGI_TOP_EXTRA_ANPAI", 1)
AKAGI_TOP_NAKI_SHANTEN_MAX = _geti("AKAGI_TOP_NAKI_SHANTEN_MAX", 1)
AKAGI_LAST_ALLOW_SHANTEN2 = _geti("AKAGI_LAST_ALLOW_SHANTEN2", 1)
AKAGI_NEAR_GAP_SMALL = _geti("AKAGI_NEAR_GAP_SMALL", 2000)

# --- Riichi gate ---
RIICHI_BASE_RISK = _getf("AKAGI_RIICHI_BASE_RISK", 0.10)
RIICHI_DEALER_BONUS = _getf("AKAGI_RIICHI_DEALER_BONUS", 0.22)
RIICHI_THREAT_PENALTY = _getf("AKAGI_RIICHI_THREAT_PENALTY", 0.32)
RIICHI_PLACE_PENALTY = _getf("AKAGI_RIICHI_PLACE_PENALTY", 0.45)

# --- Placement utility ---
U1 = _getf("AKAGI_UTILITY_1ST", 30.0)
U2 = _getf("AKAGI_UTILITY_2ND", 10.0)
U3 = _getf("AKAGI_UTILITY_3RD", -15.0)
U4 = _getf("AKAGI_UTILITY_4TH", -40.0)

# --- Dora aggression ---
AKAGI_MYDORA_RISK_PER_TILE = _getf("AKAGI_MYDORA_RISK_PER_TILE", 0.08)
AKAGI_MYDORA_MAX_RISK_BONUS = _getf("AKAGI_MYDORA_MAX_RISK_BONUS", 0.22)

# --- Somete (self) relax switches ---
AKAGI_SOMETE_ENABLE = _geti("AKAGI_SOMETE_ENABLE", 1)
AKAGI_SOMETE_RATIO = _getf("AKAGI_SOMETE_RATIO", 0.80)
AKAGI_SOMETE_SHANTEN_MAX = _geti("AKAGI_SOMETE_SHANTEN_MAX", 3)
AKAGI_SOMETE_SAFETY_RELAX = _geti("AKAGI_SOMETE_SAFETY_RELAX", 1)

# --- Somete CARE (opponent) switches ---
AKAGI_SOMETE_CARE_ENABLE = _geti("AKAGI_SOMETE_CARE_ENABLE", 1)
AKAGI_SOMETE_CARE_THREAT_GATE = _getf("AKAGI_SOMETE_CARE_THREAT_GATE", 0.50)
AKAGI_SOMETE_CARE_OTHER_SUIT_DISCARDS = _geti("AKAGI_SOMETE_CARE_OTHER_SUIT_DISCARDS", 6)
AKAGI_SOMETE_CARE_TARGET_SUIT_MAX = _geti("AKAGI_SOMETE_CARE_TARGET_SUIT_MAX", 1)

# --- Oya yakuhai force-pon ---
AKAGI_OYA_YAKUHAI_FORCE_PON = _geti("AKAGI_OYA_YAKUHAI_FORCE_PON", 1)

# --- Naki progress override (取りこぼし救済) ---
AKAGI_NAKI_PROGRESS_OVERRIDE_ENABLE = _geti("AKAGI_NAKI_PROGRESS_OVERRIDE_ENABLE", 1)
AKAGI_NAKI_PROGRESS_MAX_JUNME = _geti("AKAGI_NAKI_PROGRESS_MAX_JUNME", 12)
AKAGI_NAKI_PROGRESS_THREAT_MAX = _getf("AKAGI_NAKI_PROGRESS_THREAT_MAX", 0.70)

# --- Somete progress override (自分の染め手で“鳴けば前進”を救う) ---
AKAGI_SOMETE_PROGRESS_OVERRIDE_ENABLE = _geti("AKAGI_SOMETE_PROGRESS_OVERRIDE_ENABLE", 1)
AKAGI_SOMETE_PROGRESS_MAX_JUNME = _geti("AKAGI_SOMETE_PROGRESS_MAX_JUNME", 12)
AKAGI_SOMETE_PROGRESS_THREAT_MAX = _getf("AKAGI_SOMETE_PROGRESS_THREAT_MAX", 0.60)
AKAGI_SOMETE_PROGRESS_RELAX_ANPAI = _geti("AKAGI_SOMETE_PROGRESS_RELAX_ANPAI", 1)

# --- Naki Chain (連鎖鳴き) overrides ---
AKAGI_NAKI_CHAIN_ENABLE = _geti("AKAGI_NAKI_CHAIN_ENABLE", 1)
AKAGI_NAKI_CHAIN_MAX = _geti("AKAGI_NAKI_CHAIN_MAX", 2)
AKAGI_NAKI_CHAIN_WINDOW_JUNME = _geti("AKAGI_NAKI_CHAIN_WINDOW_JUNME", 2)
AKAGI_NAKI_CHAIN_THREAT_MAX = _getf("AKAGI_NAKI_CHAIN_THREAT_MAX", 0.65)
AKAGI_NAKI_CHAIN_RELAX_ANPAI = _geti("AKAGI_NAKI_CHAIN_RELAX_ANPAI", 1)

# --- KAN policy switches ---
AKAGI_KAN_ENABLE = _geti("AKAGI_KAN_ENABLE", 1)
AKAGI_ANKAN_ENABLE     = _geti("AKAGI_ANKAN_ENABLE", 1)
AKAGI_KAKAN_ENABLE     = _geti("AKAGI_KAKAN_ENABLE", 1)
AKAGI_DAIMINKAN_ENABLE = _geti("AKAGI_DAIMINKAN_ENABLE", 0)
AKAGI_KAN_THREAT_MAX        = _getf("AKAGI_KAN_THREAT_MAX", 0.50)
AKAGI_KAN_LATE_JUNME_BLOCK  = _geti("AKAGI_KAN_LATE_JUNME_BLOCK", 12)
AKAGI_KAN_MIN_ANPAI_VS_RIICHI = _geti("AKAGI_KAN_MIN_ANPAI_VS_RIICHI", 2)
AKAGI_KAN_ALLOW_IF_ANTI_LAST   = _geti("AKAGI_KAN_ALLOW_IF_ANTI_LAST", 1)
AKAGI_KAN_ALLOW_IF_SOMETE      = _geti("AKAGI_KAN_ALLOW_IF_SOMETE", 1)
AKAGI_KAN_ALLOW_IF_NEED_BIG    = _geti("AKAGI_KAN_ALLOW_IF_NEED_BIG", 1)
AKAGI_ANKAN_MIN_SHANTEN   = _geti("AKAGI_ANKAN_MIN_SHANTEN", 1)
AKAGI_KAKAN_REQUIRE_TENPAI = _geti("AKAGI_KAKAN_REQUIRE_TENPAI", 1)
AKAGI_KAKAN_MIN_SHAPE_GOOD = _getf("AKAGI_KAKAN_MIN_SHAPE_GOOD", 0.60)
AKAGI_DMK_EARLY_JUNME     = _geti("AKAGI_DMK_EARLY_JUNME", 6)

# --- OYA-TENPAI 強化用 knobs（追加） ---
AKAGI_OYA_TENPAI_FORCE_ENABLE = _geti("AKAGI_OYA_TENPAI_FORCE_ENABLE", 1)
AKAGI_OYA_TENPAI_FORCE_THREAT = _getf("AKAGI_OYA_TENPAI_FORCE_THREAT", 0.55)
AKAGI_OYA_TENPAI_FORCE_GAIN   = _getf("AKAGI_OYA_TENPAI_FORCE_GAIN", 0.0)  # 受け入れ増などの閾値補助（0で無効）


# Coordinates here is on the resolution of 16x9
LOCATION = {
    "tiles": [
        (2.23125  , 8.3625),
        (3.021875 , 8.3625),
        (3.8125   , 8.3625),
        (4.603125 , 8.3625),
        (5.39375  , 8.3625),
        (6.184375 , 8.3625),
        (6.975    , 8.3625),
        (7.765625 , 8.3625),
        (8.55625  , 8.3625),
        (9.346875 , 8.3625),
        (10.1375  , 8.3625),
        (10.928125, 8.3625),
        (11.71875 , 8.3625),
        (12.509375, 8.3625),
    ],
    "tsumo_space": 0.246875,
    "actions": [
        (10.875, 7), # none
        (8.6375, 7), # discard etc
        (6.4   , 7),
        (10.875, 5.9),
        (8.6375, 5.9),
        (6.4   , 5.9),
        (10.875, 4.8),
        (8.6375, 4.8),
        (6.4   , 4.8),
    ],
    "candidates": [
        (3.6625  , 6.3),
        (4.49625 , 6.3),
        (5.33    , 6.3),
        (6.16375 , 6.3),
        (6.9975  , 6.3),
        (7.83125 , 6.3),
        (8.665   , 6.3),
        (9.49875 , 6.3),
        (10.3325 , 6.3),
        (11.16625, 6.3),
        (12      , 6.3),
    ],
}

# Priority of actions
ACTION_PIORITY = [
    0,  # none
    99, # Discard (no button)
    4,  # Chi
    3,  # Pon
    3,  # Ankan
    2,  # Daiminkan
    3,  # Kakan
    2,  # Reach
    1,  # Tsumo
    1,  # Ron
    5,  # Ryukyoku
    4,  # Nukidora
]

ACTION2TYPE = {
    "none": 0,
    "chi": 2,
    "pon": 3,
    "daiminkan": 5,
    "hora": 9,
    "ryukyoku": 10,
    "nukidora": 11,
    "ankan": 4,
    "kakan": 6,
    "reach": 7,
    "zimo": 8,
}

TILES = [
    "1m","2m","3m","4m","5m","6m","7m","8m","9m",
    "1p","2p","3p","4p","5p","6p","7p","8p","9p",
    "1s","2s","3s","4s","5s","6s","7s","8s","9s",
    "E","S","W","N","P","F","C",
]


# ---- small utils ----
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


class AutoPlayMajsoul(object):
    def __init__(self):
        self.bot: AkagiBot = None
        # 親番フラグ／「この局の最初の自分の打牌が終わったか」フラグ
        self._is_oya: bool = False
        self._first_discard_done: bool = True
        # フォールド状態
        self._fold_mode: bool = False
        self._fold_locked_by_riichi: bool = False  # リーチ入りで強制フォールド

        # 進行情報（推定）
        self._bakaze: str | None = None  # 'E'/'S' など
        self._kyoku_number: int | None = None  # 1..4

        # 連鎖鳴きの状態
        self._naki_chain_active: bool = False
        self._naki_chain_anchor_junme: int | None = None
        self._naki_chain_count: int = 0

        # === 新規学習系・推定器の内部キャッシュ ===
        self._ev_cache = {}
        self._opp_cache = {}

    # ---- helpers: 状態参照 ----
    def _is_oya_now(self) -> bool:
        try:
            dealer = getattr(self.bot, "_AkagiBot__dealer", None)
            myid   = getattr(self.bot, "player_id", None)
            return dealer is not None and myid is not None and int(dealer) == int(myid)
        except Exception:
            return False

    def _is_my_first_discard_this_hand(self) -> bool:
        try:
            rivers = getattr(self.bot, "_AkagiBot__rivers", None)
            myid   = getattr(self.bot, "player_id", None)
            if not isinstance(rivers, dict) or myid is None:
                return False
            my_river = rivers.get(myid, [])
            return len(my_river) == 0
        except Exception:
            return False

    def _rivers(self):
        try:
            rivers = getattr(self.bot, "_AkagiBot__rivers", None)
            if isinstance(rivers, dict):
                return rivers
        except Exception:
            pass
        return {}

    def _furos(self):
        try:
            furos = getattr(self.bot, "_AkagiBot__furos", None)
            if isinstance(furos, dict):
                return furos
        except Exception:
            pass
        return {}

    def _junme(self) -> int | None:
        for cand in ["junme", "_AkagiBot__junme", "kyoku_junme"]:
            if hasattr(self.bot, cand):
                try:
                    return int(getattr(self.bot, cand))
                except Exception:
                    pass
        return None

    def _riichi_seat_ids(self) -> list[int]:
        try:
            for cand in ["players_riichi", "_AkagiBot__players_riichi", "riichi_players"]:
                if hasattr(self.bot, cand):
                    d = getattr(self.bot, cand)
                    if isinstance(d, dict):
                        return [int(k) for k, v in d.items() if v]
            for cand in ["riichi_list", "_AkagiBot__riichi_list"]:
                if hasattr(self.bot, cand):
                    lst = getattr(self.bot, cand)
                    if isinstance(lst, (list, tuple)):
                        return [int(x) for x in lst]
        except Exception:
            pass
        return []

    def _scores(self) -> list[int] | None:
        for cand in ["scores", "_AkagiBot__scores", "player_scores"]:
            if hasattr(self.bot, cand):
                s = getattr(self.bot, cand)
                if isinstance(s, (list, tuple)) and len(s) >= 4:
                    try:
                        return [int(x) for x in s[:4]]
                    except Exception:
                        pass
        return None

    def _my_seat(self) -> int | None:
        try:
            return int(getattr(self.bot, "player_id", None))
        except Exception:
            return None

    def _rank_and_gaps(self):
        """
        自分の現在順位と、3位との差/4位との差（自分が3位なら下へのリード、4位なら上へのビハインド）。
        戻り値: (rank:1..4, gap_to_third_if_4th:int|None, lead_over_4th_if_3rd:int|None)
        """
        scores = self._scores()
        me = self._my_seat()
        if scores is None or me is None:
            return None, None, None
        my_score = scores[me]
        sorted_scores = sorted(scores, reverse=True)
        rank = 1 + sorted_scores.index(my_score)
        gap_to_third = None
        lead_over_4th = None
        if rank == 4:
            third = sorted_scores[2]
            gap_to_third = max(0, third - my_score)
        if rank == 3:
            fourth = sorted_scores[3]
            lead_over_4th = max(0, my_score - fourth)
        return rank, gap_to_third, lead_over_4th

    def _capture_round_info_from_start(self, msg: dict):
        try:
            self._bakaze = msg.get("bakaze") or msg.get("bakaze_str") or None
            kyoku = msg.get("kyoku")
            if kyoku is not None:
                self._kyoku_number = int(kyoku) + 1 if kyoku in (0,1,2,3) else int(kyoku)
        except Exception:
            pass

    def _is_all_last_like(self) -> bool:
        try:
            if self._kyoku_number is None:
                return False
            if self._bakaze in ("E", "east", "East"):
                return self._kyoku_number >= 4
            if self._bakaze in ("S", "south", "South"):
                return self._kyoku_number >= 4
        except Exception:
            pass
        return False

    @staticmethod
    def _normalize_pai(p: str) -> str:
        if not isinstance(p, str): return p
        return p[:2] if len(p) >= 3 and p[2] == 'r' else p

    @staticmethod
    def _suit_of(p: str) -> str | None:
        q = AutoPlayMajsoul._normalize_pai(p)
        if isinstance(q, str) and len(q) == 2 and q[1] in ("m","p","s"):
            return q[1]
        return None

    def _is_genbutsu_to(self, seat_id: int, pai: str) -> bool:
        try:
            norm = self._normalize_pai(pai)
            r = self._rivers().get(se_id := seat_id, [])
            rn = [self._normalize_pai(x) for x in r]
            return norm in rn
        except Exception:
            return False

    def _get_shanten_safe(self) -> int | None:
        try:
            if hasattr(self.bot, "shanten"):
                return int(getattr(self.bot, "shanten"))
            if hasattr(self.bot, "current_shanten"):
                return int(getattr(self.bot, "current_shanten"))
            if hasattr(self.bot, "calc_shanten") and callable(getattr(self.bot, "calc_shanten")):
                return int(self.bot.calc_shanten())
        except Exception as _e:
            logger.debug(f"[TENPAI-BIAS] shanten get failed: {_e}")
        return None

    # --- Dora helpers ----
    @staticmethod
    def _next_suit_tile(tile: str) -> str:
        n, s = int(tile[0]), tile[1]
        n2 = 1 if n == 9 else n + 1
        return f"{n2}{s}"

    @staticmethod
    def _next_honor(tile: str) -> str:
        order = ["E","S","W","N","P","F","C"]
        i = order.index(tile)
        return order[(i+1) % len(order)]

    def _current_dora_tiles(self) -> set[str]:
        dora_tiles = set()
        try:
            indicators = None
            for cand in ["dora_indicators", "dora_indicator", "dora_list", "_AkagiBot__dora_indicators"]:
                if hasattr(self.bot, cand):
                    indicators = getattr(self.bot, cand)
                    break
            if not indicators:
                return dora_tiles

            for ind in indicators:
                t = self._normalize_pai(ind)
                if t in ("E","S","W","N","P","F","C"):
                    dora_tiles.add(self._next_honor(t))
                elif len(t) == 2 and t[1] in ("m","p","s"):
                    dora_tiles.add(self._next_suit_tile(t))
        except Exception:
            pass
        return dora_tiles

    def _my_dora_count(self) -> int:
        try:
            hand = list(getattr(self.bot, "tehai_mjai", []))
            if not hand:
                return 0
            red_cnt = sum(1 for p in hand if isinstance(p, str) and p.endswith("r"))
            dora_tiles = self._current_dora_tiles()
            norm_hand = [self._normalize_pai(p) for p in hand]
            dora_cnt = sum(1 for p in norm_hand if p in dora_tiles)
            return int(red_cnt + dora_cnt)
        except Exception:
            return 0

    # --- hand badness ---
    def _badness_score(self) -> int:
        try:
            hand = list(getattr(self.bot, "tehai_mjai", []))
            if not hand:
                return 0
            suits = {"m":[], "p":[], "s":[]}
            honors = []
            for p in hand:
                q = self._normalize_pai(p)
                if q in ("E","S","W","N","P","F","C"):
                    honors.append(q)
                else:
                    num, suit = int(q[0]), q[1]
                    suits[suit].append(num)

            score = 0
            score += len(honors)
            for suit in ("m","p","s"):
                ones = [x for x in suits[suit] if x in (1,9)]
                score += len(ones)
            for suit in ("m","p","s"):
                arr = sorted(suits[suit])
                for v in arr:
                    if (v-1 not in arr) and (v+1 not in arr):
                        score += 1
            terminals = sum(1 for p in hand if p in ("1m","9m","1p","9p","1s","9s"))
            if terminals + len(honors) >= max(5, len(hand)//3):
                score += 1
            return score
        except Exception as _e:
            logger.debug(f"[FOLD] badness calc failed: {_e}")
            return 0

    # --- oya endgame push? ---
    def _oya_endgame_push_active(self) -> bool:
        if not AKAGI_OYA_ENDGAME_PUSH_ENABLE:
            return False
        if not self._is_oya:
            return False
        junme = self._junme()
        if junme is None:
            return False
        return junme >= AKAGI_OYA_ENDGAME_JUNME

    # --- anti-last active? ---
    def _anti_last_active(self) -> bool:
        if not AKAGI_ANTI_LAST_ENABLE:
            return False
        junme = self._junme()
        if junme is None:
            junme_ok = False
        else:
            junme_ok = junme >= AKAGI_ANTI_LAST_JUNME
        if self._is_all_last_like():
            junme_ok = True

        rank, gap_to_third, lead_over_4th = self._rank_and_gaps()
        if rank is None:
            return False
        if rank == 4 and (gap_to_third is not None and gap_to_third >= AKAGI_ANTI_LAST_GAP_MIN) and junme_ok:
            return True
        if rank == 3 and (lead_over_4th is not None and lead_over_4th <= AKAGI_ANTI_LAST_AT_RISK_LEAD) and junme_ok:
            return True
        return False

    # --- my wind ---
    def _my_jikaze(self) -> str | None:
        try:
            for cand in ["jikaze", "seat_wind", "my_wind", "_AkagiBot__jikaze", "_AkagiBot__seat_wind"]:
                if hasattr(self.bot, cand):
                    v = getattr(self.bot, cand)
                    if isinstance(v, str) and v in ("E","S","W","N"):
                        return v
            for cand in ["players_wind", "player_winds", "_AkagiBot__players_wind"]:
                if hasattr(self.bot, cand):
                    d = getattr(self.bot, cand)
                    me = self._my_seat()
                    if isinstance(d, dict) and me is not None:
                        v = d.get(me)
                        if isinstance(v, str) and v in ("E","S","W","N"):
                            return v
        except Exception:
            pass
        return None

    # --- yakuhai? ---
    def _is_yakuhai_tile(self, pai: str) -> bool:
        p = self._normalize_pai(pai)
        if p in ("P","F","C"):
            return True
        if p in ("E","S","W","N"):
            if self._bakaze and p == self._bakaze:
                return True
            my_jikaze = self._my_jikaze()
            if my_jikaze and p == my_jikaze:
                return True
        return False

    # ---- Somete判定（清一・混一の狙い目）----
    def _is染め手_like(self) -> bool:
        """
        自分の手牌が染め手寄りかの簡易判定
        """
        if not AKAGI_SOMETE_ENABLE:
            return False
        try:
            hand = list(getattr(self.bot, "tehai_mjai", []))
            if not hand:
                return False
            norm = [self._normalize_pai(p) for p in hand]
            suits = [p[1] for p in norm if isinstance(p, str) and len(p) == 2 and p[1] in ("m","p","s")]
            honors = [p for p in norm if p in ("E","S","W","N","P","F","C")]
            if not suits:
                return False
            most_suit = max(set(suits), key=suits.count)
            suited = [s for s in suits if s == most_suit]
            ratio = float(len(suited) + len(honors)) / float(len(hand))
            return ratio >= AKAGI_SOMETE_RATIO
        except Exception:
            return False

    # ---- 相手の“染め手っぽさ”推定（スーツ返却 or None）----
    def _opp_suspected_somete_suit(self, seat_id: int) -> str | None:
        try:
            if seat_id == self._my_seat():
                return None
            rivers = self._rivers().get(seat_id, []) or []
            furos = self._furos().get(seat_id, []) or []

            cnt = {"m":0,"p":0,"s":0,"honor":0}
            for t in rivers:
                q = self._normalize_pai(t)
                if len(q) == 2 and q[1] in ("m","p","s"):
                    cnt[q[1]] += 1
                elif q in ("E","S","W","N","P","F","C"):
                    cnt["honor"] += 1

            suits = ["m","p","s"]
            min_suit = min(suits, key=lambda s: cnt[s])
            other_discards = sum(cnt[s] for s in suits if s != min_suit)
            min_discards = cnt[min_suit]

            furo_suits = []
            for meld in furos:
                for p in (meld or []):
                    s = self._suit_of(p)
                    if s: furo_suits.append(s)
            furo_bias = furo_suits and (max(set(furo_suits), key=furo_suits.count) == min_suit)

            if other_discards >= AKAGI_SOMETE_CARE_OTHER_SUIT_DISCARDS and min_discards <= AKAGI_SOMETE_CARE_TARGET_SUIT_MAX:
                if furo_bias or self._junme() and self._junme() >= 6:
                    return min_suit
        except Exception as _e:
            logger.debug(f"[SOMETE-CARE] detect error for seat {seat_id}: {_e}")
        return None

    def _detect_somete_danger_suits(self) -> set[str]:
        danger = set()
        try:
            for seat in range(4):
                if seat == self._my_seat(): 
                    continue
                s = self._opp_suspected_somete_suit(seat)
                if s:
                    danger.add(s)
        except Exception as _e:
            logger.debug(f"[SOMETE-CARE] detect all error: {_e}")
        return danger

    # --- update fold mode ---
    def _update_fold_mode(self, mjai_msg: dict):
        if not AKAGI_FOLD_ENABLE:
            self._fold_mode = False
        if mjai_msg.get("type") == "start_kyoku":
            self._capture_round_info_from_start(mjai_msg)

        if AKAGI_FOLD_FORCE_ON_RIICHI and self._riichi_seat_ids():
            if not self._fold_locked_by_riichi:
                logger.debug("[FOLD] lock by riichi")
            self._fold_locked_by_riichi = True

        shanten = self._get_shanten_safe()
        junme = self._junme()
        badness = self._badness_score()

        try:
            if (shanten is not None) and (junme is not None):
                bad_opening = (shanten >= AKAGI_FOLD_SHANTEN_THRESH and badness >= AKAGI_FOLD_BADNESS_SCORE_THRESH)

                myd = self._my_dora_count()
                if myd >= 2:
                    if junme <= AKAGI_FOLD_EARLY_JUNME:
                        bad_opening = False

                if bad_opening and junme <= AKAGI_FOLD_EARLY_JUNME:
                    if not self._fold_mode:
                        logger.debug(f"[FOLD] enter (opening bad) shanten={shanten}, badness={badness}, junme={junme}")
                    self._fold_mode = True

                if (shanten <= AKAGI_FOLD_RELEASE_SHANTEN) or (myd >= 2):
                    if not self._fold_locked_by_riichi:
                        if self._fold_mode:
                            logger.debug(f"[FOLD] release (improved/myd) shanten={shanten}, junme={junme}, myd={myd}")
                        self._fold_mode = False
        except Exception as _e:
            logger.debug(f"[FOLD] update error: {_e}")

        if self._oya_endgame_push_active():
            if self._fold_mode:
                logger.debug("[FOLD] softened by OYA_ENDGAME_PUSH")

        if self._anti_last_active():
            if self._fold_mode:
                logger.debug("[FOLD] overridden by ANTI_LAST (pursue tempai/points)")

    # ---- naki for tempai (with S3 non-dealer guard + somete relax) ----
    def _should_accept_naki_for_tenpai(self, naki_type: str) -> bool:
        if not AKAGI_TENPAI_BIAS_ENABLE:
            return True
        if naki_type not in ("chi", "pon"):
            return True  # KANは別途ポリシー

        # South-3, non-dealer, big deficit & low EV -> don't open
        try:
            if (self._bakaze in ("S","south","South")) and (self._kyoku_number == 3) and (not self._is_oya):
                rank, gap_to_third, _ = self._rank_and_gaps()
                if rank in (3,4) and (gap_to_third or 0) >= 15000:
                    if self._estimate_hand_value() < 6000:
                        return False
        except Exception:
            pass

        shanten = self._get_shanten_safe()
        if shanten is None:
            return True

        # --- 染め手なら緩和（速度優先） ---
        if self._is染め手_like():
            if shanten <= AKAGI_SOMETE_SHANTEN_MAX:
                return True

        # ラス回避・親終盤の特例
        if self._anti_last_active() and AKAGI_ANTI_LAST_ALLOW_CHILD_SHANTEN2:
            if shanten <= 2:
                return True
        if self._oya_endgame_push_active() and AKAGI_OYA_ENDGAME_ALLOW_SHANTEN2:
            if shanten <= 2:
                return True

        # 点数状況補正
        if AKAGI_SCOREPOLICY_ENABLE:
            rank, gap_to_third, lead_over_4th = self._rank_and_gaps()
            if rank == 1:
                return shanten <= AKAGI_TOP_NAKI_SHANTEN_MAX
            elif rank == 4:
                if AKAGI_LAST_ALLOW_SHANTEN2 and shanten <= 2:
                    return True
            elif rank == 3 and lead_over_4th is not None and lead_over_4th <= AKAGI_NEAR_GAP_SMALL:
                if shanten <= 2:
                    return True

        # --- ドラによる緩和/抑制（2段階） ---
        myd = self._my_dora_count()
        if myd >= 2:
            if shanten <= 2:
                return True
        elif myd == 0:
            if not self._is_oya and shanten >= 2:
                return False

        # 通常（親はやや緩い）
        if not self._is_oya:
            return shanten == 1
        if shanten == 1:
            return True
        if shanten == 2 and AKAGI_TENPAI_BIAS_OYA_SHANTEN2:
            return True
        return False

    # ---- naki safety (simple + somete relax) ----
    def _naki_safety_ok(self, mjai_msg: dict) -> bool:
        if not AKAGI_NAKI_SAFETY_ENABLE:
            return True
        try:
            ntype = mjai_msg.get("type", "")
            pai = self._normalize_pai(mjai_msg.get("pai", ""))
            riichi_ids = self._riichi_seat_ids()
            junme = self._junme()

            min_anpai = AKAGI_NAKI_SAFETY_MIN_ANPAI

            # 親終盤 or Anti-Last はやや緩和
            if (self._oya_endgame_push_active()) or (self._anti_last_active()):
                min_anpai = min(min_anpai, AKAGI_OYA_ENDGAME_MIN_ANPAI)

            # 染め手なら安牌要求を少し緩和
            if self._is染め手_like() and AKAGI_SOMETE_SAFETY_RELAX:
                min_anpai = max(0, min_anpai - 1)

            # 1) リーチ者がいる場合、鳴き牌は「誰かの現物」であること（any）
            if riichi_ids:
                ok_any = any(self._is_genbutsu_to(rid, pai) for rid in riichi_ids)
                if not ok_any:
                    logger.debug(f"[NAKI-SAFETY] decline: not genbutsu to any riichi seat, pai={pai}")
                    return False

            # 2) 終盤×安牌ストック＋候補危険度
            if junme is not None and junme >= AKAGI_NAKI_SAFETY_JUNME_TIGHT:
                anpai_cnt = self._count_anpai_against_riichi()
                dang = self.tile_danger(pai)
                if anpai_cnt < min_anpai and ntype in ("chi", "pon"):
                    logger.debug(f"[NAKI-SAFETY] decline: late junme={junme}, anpai={anpai_cnt} < {min_anpai}")
                    return False
                if dang >= 0.30 and ntype in ("chi","pon"):
                    logger.debug(f"[NAKI-SAFETY] decline: danger high={dang:.2f} pai={pai}")
                    return False

            # KAN はここでは扱わない（KANは別ポリシー）
        except Exception as _e:
            logger.debug(f"[NAKI-SAFETY] check error: {_e}")
            return True

        return True

    def _count_anpai_against_riichi(self) -> int:
        try:
            riichi_ids = self._riichi_seat_ids()
            if not riichi_ids:
                return 99
            tehai = list(getattr(self.bot, "tehai_mjai", []))
            safe = set()
            for t in tehai:
                tnorm = self._normalize_pai(t)
                ok = True
                for rid in riichi_ids:
                    if not self._is_genbutsu_to(rid, tnorm):
                        ok = False
                        break
                if ok:
                    safe.add(tnorm)
            return len(safe)
        except Exception as _e:
            logger.debug(f"[SOMETE-CARE] anpai count failed: {_e}")
            return 0

    # ===== Riichi/Dama/Fold gate =====
    def _threat_level(self) -> float:
        try:
            riichi_n = len(self._riichi_seat_ids())
            junme = self._junme() or 0
            melds_total = 0
            if hasattr(self.bot, "_AkagiBot__furos"):
                furos = getattr(self.bot, "_AkagiBot__furos") or {}
                for seat, arr in furos.items():
                    if seat != self._my_seat():
                        melds_total += len(arr or [])
            v = 0.7*min(1.0, riichi_n/2.0) + 0.25*min(1.0, melds_total/4.0) + 0.15*min(1.0, max(0, junme-8)/6.0)
            return clamp(v, 0.0, 1.0)
        except Exception:
            return 0.0

    def _placement_pressure(self) -> float:
        try:
            rank, gap_to_third, lead_over_4th = self._rank_and_gaps()
            junme = self._junme() or 0
            is_oras = 1.0 if self._is_all_last_like() else 0.0
            base = 0.0
            if rank == 4:
                base = 0.6 + 0.3*sigmoid((6000 - (gap_to_third or 0))/2000.0)
            elif rank == 3:
                base = 0.3 + 0.3*sigmoid(((AKAGI_NEAR_GAP_SMALL) - (lead_over_4th or 99999))/1500.0)
            elif rank == 2:
                base = 0.2
            else:
                base = 0.1
            late = clamp((junme-8)/6.0, 0.0, 0.5)
            return clamp(base + late + 0.2*is_oras, 0.0, 1.0)
        except Exception:
            return 0.3

    def _risk_budget(self) -> float:
        try:
            base = (
                RIICHI_BASE_RISK
                + (RIICHI_DEALER_BONUS if self._is_oya else 0.0)
                - RIICHI_THREAT_PENALTY*self._threat_level()
                - RIICHI_PLACE_PENALTY*self._placement_pressure()
            )
            myd = self._my_dora_count()
            bonus = clamp(AKAGI_MYDORA_RISK_PER_TILE * float(myd), 0.0, AKAGI_MYDORA_MAX_RISK_BONUS)
            return clamp(base + bonus, -0.4, 0.8)
        except Exception:
            return 0.0

    def _estimate_hand_value(self) -> float:
        try:
            if hasattr(self.bot, "expected_points"):
                return float(getattr(self.bot, "expected_points"))

            tehai = list(getattr(self.bot, "tehai_mjai", []))
            red_n = sum(1 for p in tehai if p.endswith("r"))
            myd = self._my_dora_count()

            shanten = self._get_shanten_safe() or 3
            base = 1300 if shanten >= 2 else 2000
            bonus = 900*myd + 200*red_n
            return float(base + bonus)
        except Exception:
            return 2200.0

    def _good_shape_rate(self) -> float:
        """
        置換：受け入れ総数＋好形比を推定し、[0..1] の好形レートに射影
        """
        try:
            ukeire, good_ratio = self.calc_ukeire_and_quality()
            u = clamp((ukeire / 40.0), 0.0, 1.0)
            g = clamp(good_ratio, 0.0, 1.0)
            return clamp(0.35*u + 0.65*g, 0.0, 1.0)
        except Exception:
            return 0.5

    def _need_big_hand_for_rankup(self) -> bool:
        try:
            scores = self._scores()
            me = self._my_seat()
            if not scores or me is None: return False
            rank, gap_to_third, _ = self._rank_and_gaps()
            if rank is None: return False
            sorted_scores = sorted(scores, reverse=True)
            if rank >= 2:
                target = sorted_scores[rank-2]
                need = max(0, target - scores[me] + 1000)
                return need >= 8000
            if rank == 3 and (gap_to_third or 0) > 0:
                return gap_to_third >= 8000
        except Exception:
            pass
        return False

    def estimate_hand_point_dist(self) -> dict:
        """
        平均点と満貫以上の確率（粗）
        """
        e = self._estimate_hand_value()
        myd = self._my_dora_count()
        sh = self._get_shanten_safe() or 2
        p_mangan = clamp(0.06 + 0.04*myd + (0.03 if sh <= 1 else 0.0), 0.0, 0.35)
        return {"avg": e, "p_mangan": p_mangan}

    def estimate_opponent_tenpai_prob(self, seat_id: int) -> float:
        """
        河・副露数・巡目からざっくり推定（簡易）
        """
        try:
            if seat_id == self._my_seat():
                return 0.0
            furos = (self._furos().get(seat_id, []) or [])
            rivers = (self._rivers().get(seat_id, []) or [])
            j = self._junme() or 0
            base = 0.10 + 0.08*len(furos) + 0.02*max(0, j-6)
            return clamp(base, 0.0, 0.75)
        except Exception:
            return 0.25

    def estimate_meld_ev_gain(self, mjai_msg: dict) -> float:
        """
        鳴き EV 差分（簡易）：速度の上昇 − 打点低下 − 情報露出による失点増
        """
        try:
            ntype = mjai_msg.get("type")
            if ntype not in ("chi","pon"):
                return 0.0
            sh = self._get_shanten_safe()
            if sh is None:
                return 0.0
            point = self._estimate_hand_value()
            if sh >= 2:
                win_up = 0.06
            elif sh == 1:
                win_up = 0.12
            else:
                win_up = 0.02
            down = 0.15 * point
            danger = 120.0 * (1.0 + 0.4*len(self._riichi_seat_ids()))
            delta = win_up*point - down - danger
            logger.debug(f"[EV] meld delta≈{delta:.0f} (win_up={win_up:.2f}, point={point:.0f}, danger={danger:.0f})")
            return delta
        except Exception as _e:
            logger.debug(f"[EV] meld gain est error: {_e}")
            return 0.0

    def estimate_kan_ev_delta(self, ktype: str) -> float:
        """
        カンの EV 差分（簡易）：裏ドラ期待 − 脅威依存のペナルティ
        """
        try:
            ura = 350.0 if ktype in ("ankan","kakan") else 200.0
            threat = self._threat_level()
            penalty = 500.0 * threat
            return ura - penalty
        except Exception:
            return -100.0

    def simulate_ev_for_action(self, action: str) -> float:
        """
        将来的なモンテカルロ用の入口（現状は軽量ダミー）
        """
        base = 0.0
        if action == "riichi":
            base += 50.0
        elif action == "dama":
            base += 20.0
        return base

    def tile_danger(self, tile: str) -> float:
        """
        牌ごとの簡易危険度 0..1
        """
        try:
            t = self._normalize_pai(tile)
            riichi_ids = self._riichi_seat_ids()
            if riichi_ids:
                if any(self._is_genbutsu_to(rid, t) for rid in riichi_ids):
                    base = 0.02
                else:
                    base = 0.18
            else:
                base = 0.12
            if t in ("E","S","W","N","P","F","C"):
                base += 0.06
            j = self._junme() or 0
            late_pen = max(0, j-10) * 0.01
            return clamp(base + late_pen, 0.01, 0.45)
        except Exception:
            return 0.18

    def _should_riichi_decision(self) -> str:
        try:
            tenpai = bool(getattr(self.bot, "tenpai", False)) if hasattr(self.bot, "tenpai") else (self._get_shanten_safe() == 0)
            if not tenpai:
                return "fold" if self._threat_level() > 0.7 and (self._get_shanten_safe() or 9) >= 2 else "dama"

            # 新版：好形率・打点分布・危険度を反映
            e_points = self._estimate_hand_value()
            good = self._good_shape_rate()
            threat = self._threat_level()
            place_p = self._placement_pressure()
            risk = self._risk_budget()
            junme = self._junme() or 0
            dist = self.estimate_hand_point_dist()
            mangan_boost = 1.0 + 0.25*dist.get("p_mangan", 0.0)

            # 宣言後の被弾上昇
            deal_in_rate = clamp(0.08 + 0.10*threat - 0.02*good + 0.02*max(0, junme-10), 0.02, 0.27)
            deal_in_rate_riichi = clamp(deal_in_rate + 0.03*threat, 0.02, 0.33)

            # 和了率
            win_rate_riichi = clamp(0.17 + 0.18*good + (0.06 if self._is_oya else 0.0) - 0.08*threat + 0.02*max(0, 10-junme), 0.06, 0.70)
            win_rate_dama   = clamp(win_rate_riichi - 0.06, 0.03, 0.55)

            # 期待打点
            point_dama   = e_points * mangan_boost
            point_riichi = e_points * 1.22 * mangan_boost

            EV_riichi = win_rate_riichi*point_riichi + (-deal_in_rate_riichi)*(-4000.0)
            EV_dama   = win_rate_dama*point_dama     + (-deal_in_rate)*(-3500.0)
            EV_fold   = -500.0 * place_p

            # 将来拡張フック
            EV_riichi += 0.2 * self.simulate_ev_for_action("riichi")
            EV_dama   += 0.2 * self.simulate_ev_for_action("dama")

            gate = 0.1 - 0.6* clamp(risk, -0.4, 0.8)
            myd = self._my_dora_count()
            gate -= 0.02 * max(0, myd - 1)

            if self._is_all_last_like():
                need_big = self._need_big_hand_for_rankup()
                if need_big and point_riichi >= point_dama*1.15:
                    EV_riichi += 1000.0

            logger.debug(f"[RIICHI] EV_r={EV_riichi:.0f}, EV_d={EV_dama:.0f}, EV_f={EV_fold:.0f}, "
                         f"risk={risk:.2f}, threat={threat:.2f}, placeP={place_p:.2f}, gate={gate:.2f}, myd={myd}, "
                         f"good={good:.2f}, dist_pman={dist.get('p_mangan',0):.2f}")

            best = max(EV_riichi, EV_dama, EV_fold)
            if best == EV_riichi and (EV_riichi - max(EV_dama, EV_fold)) > gate:
                return "riichi"
            if best == EV_dama and (EV_dama - EV_fold) > -0.1:
                return "dama"
            return "fold"
        except Exception as _e:
            logger.debug(f"[RIICHI] decision error: {_e}")
            return "dama"

    # ---- 進行系ヘルパー ----
    def _naki_advances_hand(self, mjai_msg: dict) -> bool:
        """
        鳴くと「手が進む」と期待できるかの緩い判定
        """
        try:
            ntype = mjai_msg.get('type')
            if ntype not in ('chi', 'pon'):
                return False
            sh = self._get_shanten_safe()
            if sh is None:
                return True
            if sh >= 2:
                return True
            if sh == 1 and ntype == 'pon':
                called = self._normalize_pai(mjai_msg.get('pai', ''))
                if self._is_yakuhai_tile(called):
                    return True
            return False
        except Exception:
            return False

    def _naki_safety_ok_somete_progress(self, mjai_msg: dict) -> bool:
        """
        染め手×進行オーバーライド用の安全判定（リーチ現物維持・終盤在庫を1枚さらに緩和）
        """
        try:
            ntype = mjai_msg.get("type", "")
            if ntype not in ("chi", "pon"):
                return True

            pai = self._normalize_pai(mjai_msg.get("pai", ""))
            riichi_ids = self._riichi_seat_ids()
            junme = self._junme()

            if riichi_ids:
                ok_any = any(self._is_genbutsu_to(rid, pai) for rid in riichi_ids)
                if not ok_any:
                    logger.debug(f"[SOMETE-PROG SAFETY] decline: need genbutsu vs riichi, pai={pai}")
                    return False

            if junme is not None and junme >= AKAGI_NAKI_SAFETY_JUNME_TIGHT:
                base_min = AKAGI_NAKI_SAFETY_MIN_ANPAI
                if AKAGI_SOMETE_SAFETY_RELAX:
                    base_min = max(0, base_min - 1)
                if AKAGI_SOMETE_PROGRESS_RELAX_ANPAI:
                    base_min = max(0, base_min - 1)
                anpai_cnt = self._count_anpai_against_riichi()
                if anpai_cnt < base_min:
                    logger.debug(f"[SOMETE-PROG SAFETY] decline late: anpai={anpai_cnt} < {base_min}")
                    return False

            if ntype in ("ankan","kakan","daiminkan"):
                return False

            return True
        except Exception as _e:
            logger.debug(f"[SOMETE-PROG SAFETY] error: {_e}")
            return False

    # ---- 連鎖鳴きヘルパー ----
    def _start_naki_chain(self):
        if not AKAGI_NAKI_CHAIN_ENABLE:
            return
        self._naki_chain_active = True
        self._naki_chain_count += 1
        self._naki_chain_anchor_junme = self._junme()
        logger.debug(f"[NAKI-CHAIN] start: count={self._naki_chain_count}, anchor_junme={self._naki_chain_anchor_junme}")

    def _maybe_stop_naki_chain_on_discard(self):
        if self._naki_chain_active:
            self._naki_chain_active = False
            self._naki_chain_anchor_junme = None
            self._naki_chain_count = 0
            logger.debug("[NAKI-CHAIN] stop on discard")

    def _naki_chain_window_open(self) -> bool:
        if not (AKAGI_NAKI_CHAIN_ENABLE and self._naki_chain_active):
            return False
        if self._naki_chain_count >= (1 + AKAGI_NAKI_CHAIN_MAX):
            return False
        threat = self._threat_level()
        if threat > AKAGI_NAKI_CHAIN_THREAT_MAX and not (self._anti_last_active() or self._oya_endgame_push_active()):
            return False
        try:
            j0 = self._naki_chain_anchor_junme or 0
            jn = self._junme() or j0
            return (jn - j0) <= AKAGI_NAKI_CHAIN_WINDOW_JUNME
        except Exception:
            return True

    def _naki_safety_ok_chain(self, mjai_msg: dict) -> bool:
        try:
            ntype = mjai_msg.get("type", "")
            if ntype not in ("chi", "pon"):
                return True
            pai = self._normalize_pai(mjai_msg.get("pai", ""))
            riichi_ids = self._riichi_seat_ids()
            junme = self._junme()

            if riichi_ids:
                ok_any = any(self._is_genbutsu_to(rid, pai) for rid in riichi_ids)
                if not ok_any:
                    logger.debug(f"[NAKI-CHAIN SAFETY] need genbutsu vs riichi, pai={pai}")
                    return False

            if junme is not None and junme >= AKAGI_NAKI_SAFETY_JUNME_TIGHT:
                base_min = AKAGI_NAKI_SAFETY_MIN_ANPAI
                if self._is染め手_like() and AKAGI_SOMETE_SAFETY_RELAX:
                    base_min = max(0, base_min - 1)
                if AKAGI_NAKI_CHAIN_RELAX_ANPAI:
                    base_min = max(0, base_min - 1)
                anpai_cnt = self._count_anpai_against_riichi()
                if anpai_cnt < base_min:
                    logger.debug(f"[NAKI-CHAIN SAFETY] decline late: anpai={anpai_cnt} < {base_min}")
                    return False

            if ntype in ("ankan","kakan","daiminkan"):
                return False

            return True
        except Exception as _e:
            logger.debug(f"[NAKI-CHAIN SAFETY] error: {_e}")
            return False

    # ---- KAN policy ----
    def _kan_allowed(self, mjai_msg: dict) -> bool:
        try:
            if not AKAGI_KAN_ENABLE:
                return False

            ktype = mjai_msg.get('type', '')
            if ktype not in ('ankan','kakan','daiminkan'):
                return True

            if ktype == 'ankan' and not AKAGI_ANKAN_ENABLE: return False
            if ktype == 'kakan' and not AKAGI_KAKAN_ENABLE: return False
            if ktype == 'daiminkan' and not AKAGI_DAIMINKAN_ENABLE: return False

            threat = self._threat_level()
            junme  = self._junme() or 0
            riichi_ids = self._riichi_seat_ids()

            strong_ok = (self._anti_last_active() and AKAGI_KAN_ALLOW_IF_ANTI_LAST) \
                        or (self._is染め手_like() and AKAGI_KAN_ALLOW_IF_SOMETE) \
                        or (self._need_big_hand_for_rankup() and AKAGI_KAN_ALLOW_IF_NEED_BIG)

            if junme >= AKAGI_KAN_LATE_JUNME_BLOCK and not strong_ok:
                return False
            if threat > AKAGI_KAN_THREAT_MAX and not strong_ok:
                return False

            if riichi_ids:
                if self._count_anpai_against_riichi() < AKAGI_KAN_MIN_ANPAI_VS_RIICHI:
                    return False

            shanten = self._get_shanten_safe()

            if ktype == 'ankan':
                if shanten is not None and shanten > AKAGI_ANKAN_MIN_SHANTEN:
                    return False
                if self._fold_mode:
                    return False
                return self.estimate_kan_ev_delta('ankan') > 0.0

            if ktype == 'kakan':
                if self._fold_mode:
                    return False
                if AKAGI_KAKAN_REQUIRE_TENPAI:
                    if shanten is None or shanten != 0:
                        return False
                if len(riichi_ids) > 0:
                    return False
                if self._good_shape_rate() < AKAGI_KAKAN_MIN_SHAPE_GOOD and not strong_ok:
                    return False
                return self.estimate_kan_ev_delta('kakan') > 0.0

            if ktype == 'daiminkan':
                if self._fold_mode:
                    return False
                if junme > AKAGI_DMK_EARLY_JUNME and not strong_ok:
                    return False
                if len(riichi_ids) > 0:
                    return False
                return self.estimate_kan_ev_delta('daiminkan') > 0.0

            return False
        except Exception as _e:
            logger.debug(f"[KAN] policy error: {_e}")
            return False

    # ---------------- main ----------------
    def act(self, mjai_msg: dict) -> list[Point]:
        if mjai_msg is None:
            return []
        logger.debug(f"Act: {mjai_msg}")
        logger.debug(f"reach_accepted: {self.bot.self_riichi_accepted}")

        # ---- 局開始イベントでフラグをリセット＆親判定 ----
        if mjai_msg.get("type") == "start_kyoku":
            try:
                oya = mjai_msg.get("oya", None)
                myid = getattr(self.bot, "player_id", None)
                self._is_oya = (oya is not None and myid is not None and int(oya) == int(myid))
            except Exception:
                self._is_oya = False
            self._first_discard_done = False
            self._fold_mode = False
            self._fold_locked_by_riichi = False
            self._capture_round_info_from_start(mjai_msg)

        # --- フォールドモード更新 ---
        try:
            self._update_fold_mode(mjai_msg)
        except Exception as _e:
            logger.debug(f"[FOLD] periodic update failed: {_e}")

        # --- 打牌（自分の手番） ---
        if mjai_msg['type'] == 'dahai' and not self.bot.self_riichi_accepted:
            wait = random.uniform(0.8, 1.0)

            if not self.bot.last_kawa_tile:
                wait = max(wait, 1.0)
                try:
                    if self._is_oya_now() and self._is_my_first_discard_this_hand():
                        extra = max(0.0, AKAGI_OYA_FIRST_DAHAI_EXTRA)
                        wait += extra
                        logger.debug(f"[OYA-FIRST] extra wait applied: +{extra}s "
                                    f"(dealer={getattr(self.bot, '_AkagiBot__dealer', None)}, "
                                    f"me={getattr(self.bot, 'player_id', None)})")
                except Exception as _e:
                    logger.debug(f"[OYA-FIRST] check skipped due to: {_e}")

            if self._is_oya and (not self._first_discard_done) and (not self.bot.last_kawa_tile):
                wait += max(0.0, AKAGI_OYA_FIRST_DAHAI_EXTRA)

            return_points = [Point(-1, -1, wait)]
            return_points += self.click_dahai(mjai_msg)

            # 連鎖鳴きは自打牌確定で終了
            self._maybe_stop_naki_chain_on_discard()

            self._first_discard_done = True
            return return_points

        if mjai_msg['type'] == 'dahai' and self.bot.self_riichi_accepted:
            return []

        # --- 鳴き/和了/宣言など ---
        if mjai_msg['type'] in [
            'none','chi','pon','daiminkan','ankan','kakan',
            'hora','reach','ryukyoku','nukidora','zimo'
        ]:
            return self.click_chiponkan(mjai_msg)

        return []

    def click_chiponkan(self, mjai_msg: dict) -> list[Point]:
        return_points: list[Point] = []
        operation_list: list[int] = [0]

        if self.bot.can_discard:      operation_list.append(1)
        if self.bot.can_chi:          operation_list.append(2)
        if self.bot.can_pon:          operation_list.append(3)
        # KAN 系も候補に出す（押すかはポリシーで判定）
        if self.bot.can_ankan:        operation_list.append(4)
        if self.bot.can_daiminkan:    operation_list.append(5)
        if self.bot.can_kakan:        operation_list.append(6)
        if self.bot.can_riichi:       operation_list.append(7)
        if self.bot.can_tsumo_agari:  operation_list.append(8)
        if self.bot.can_ron_agari:    operation_list.append(9)
        if self.bot.can_ryukyoku:     operation_list.append(10)
        if self.bot.tehai_vec34[9*3+3] > 0:
            operation_list.append(11)

        operation_list.sort(key=lambda x: ACTION_PIORITY[x])

        # hora を zimo 扱いへ補正（手牌枚数で自摸和了判定）
        if sum(self.bot.tehai_vec34) in [14, 11, 8, 5, 2] and mjai_msg['type'] == 'hora':
            mjai_msg['type'] = 'zimo'

        naki_types = {'chi','pon'}  # KAN除外（別ポリシー）

        # ===== リーチ三択ゲート =====
        try:
            if mjai_msg.get('type') == 'reach':
                decision = self._should_riichi_decision()
                if decision == "riichi":
                    pass
                elif decision == "dama":
                    logger.debug("[RIICHI] convert reach -> none (choose dama)")
                    mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
                else:
                    logger.debug("[RIICHI] convert reach -> none (fold)")
                    mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
        except Exception as _e:
            logger.debug(f"[RIICHI] gate error: {_e}")

        # --- 方針補正（フォールド優先。例外：Anti-Last/親終盤） ---
        try:
            oya_endgame = self._oya_endgame_push_active()
            anti_last = self._anti_last_active()

            # KANは状況可（ここでまずポリシーでふるい）
            if mjai_msg.get('type') in ('ankan','kakan','daiminkan'):
                if not self._kan_allowed(mjai_msg):
                    logger.debug("[KAN] decline by policy")
                    mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'

            if self._fold_mode:
                t = mjai_msg.get('type')
                if anti_last:
                    if t in ('reach','chi','pon'):
                        pass
                    else:
                        mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
                elif oya_endgame:
                    if t in ('chi','pon'):
                        pass
                    else:
                        mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
                else:
                    mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'

            # 親なら役牌はポン優先（降り中でも環境で強制可）
            force_accept_naki = False
            if (mjai_msg.get('type') == 'pon') and self._is_oya:
                called_tile = mjai_msg.get('pai', '')
                if self._is_yakuhai_tile(called_tile):
                    if AKAGI_OYA_YAKUHAI_FORCE_PON or (not self._fold_mode):
                        force_accept_naki = True
                        logger.debug(f"[OYA-YAKUHAI] FORCE PON on {called_tile} (oya, force={AKAGI_OYA_YAKUHAI_FORCE_PON}, fold={self._fold_mode})")

            # 鳴きは安全度→“できれば聴牌”の順で判定（＋EV比較）
            if mjai_msg.get('type') in naki_types:
                if not force_accept_naki:
                    # 守備チェック
                    if not self._naki_safety_ok(mjai_msg):
                        logger.debug(f"[TENPAI+SAFETY] decline {mjai_msg['type']} by safety")
                        mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
                    else:
                        # EV 比較
                        delta = self.estimate_meld_ev_gain(mjai_msg)
                        if delta <= 0.0:
                            # --- 進行オーバーライド（従来ロジック） ---
                            junme = self._junme() or 0
                            threat = self._threat_level()
                            allow_progress = (
                                AKAGI_NAKI_PROGRESS_OVERRIDE_ENABLE
                                and self._naki_advances_hand(mjai_msg)
                                and (junme <= AKAGI_NAKI_PROGRESS_MAX_JUNME)
                                and (threat <= AKAGI_NAKI_PROGRESS_THREAT_MAX or self._anti_last_active() or self._oya_endgame_push_active())
                            )
                            if allow_progress:
                                logger.debug(f"[NAKI-PROGRESS] override accept {mjai_msg['type']} "
                                             f"(sh={self._get_shanten_safe()}, junme={junme}, threat={threat:.2f}, delta={delta:.0f})")
                            else:
                                logger.debug(f"[TENPAI] decline {mjai_msg['type']} (oya={self._is_oya}, shanten={self._get_shanten_safe()}, delta={delta:.0f})")
                                mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
                        else:
                            logger.debug(f"[EV] accept {mjai_msg['type']} (delta={delta:.0f})")

                # --- 親テンパイ強制（yakuhai面子＋追加で0シャンテン見込） ---
                try:
                    if AKAGI_OYA_TENPAI_FORCE_ENABLE and self._is_oya and mjai_msg.get('type') in ('chi','pon') and mjai_msg.get('type') != 'none':
                        called = self._normalize_pai(mjai_msg.get('pai', ''))
                        sh = self._get_shanten_safe()
                        # 役牌面子が既にあるか（簡易：副露に役牌含む）
                        has_yaku_meld = False
                        furos = (self._furos().get(self._my_seat(), []) or [])
                        for meld in furos:
                            if any(self._is_yakuhai_tile(self._normalize_pai(p)) for p in (meld or [])):
                                has_yaku_meld = True
                                break
                        threat = self._threat_level()
                        if (sh is not None and sh == 1 and has_yaku_meld and threat <= AKAGI_OYA_TENPAI_FORCE_THREAT):
                            logger.debug(f"[OYA-TENPAI] force accept naki (sh=1->0, threat={threat:.2f})")
                        # 実装は既に受け側に寄っているため、ここではログのみ（ブロックを通過させる）
                except Exception as _e:
                    logger.debug(f"[FOLD] exception: allow oya naki to reach tenpai: {_e}")

                # --- 染め手・進行オーバーライド ---
                try:
                    if (
                        AKAGI_SOMETE_PROGRESS_OVERRIDE_ENABLE
                        and self._is染め手_like()
                        and mjai_msg.get('type') in ('chi','pon')
                        and mjai_msg.get('type') != 'none'
                    ):
                        called = self._normalize_pai(mjai_msg.get('pai', ''))
                        called_suit = self._suit_of(called)
                        if called_suit in ('m','p','s'):
                            hand = list(getattr(self.bot, "tehai_mjai", []))
                            norm = [self._normalize_pai(p) for p in hand]
                            suits = [p[1] for p in norm if isinstance(p, str) and len(p) == 2 and p[1] in ("m","p","s")]
                            most_suit = max(set(suits), key=suits.count) if suits else None

                            if most_suit and called_suit == most_suit:
                                if self._naki_advances_hand(mjai_msg):
                                    junme = self._junme() or 0
                                    threat = self._threat_level()
                                    if (junme <= AKAGI_SOMETE_PROGRESS_MAX_JUNME) and (threat <= AKAGI_SOMETE_PROGRESS_THREAT_MAX or self._anti_last_active() or self._oya_endgame_push_active()):
                                        if self._naki_safety_ok_somete_progress(mjai_msg):
                                            logger.debug(f"[SOMETE-PROGRESS] override ACCEPT {mjai_msg['type']} "
                                                         f"(suit={called_suit}, sh={self._get_shanten_safe()}, junme={junme}, threat={threat:.2f})")
                                        else:
                                            logger.debug("[SOMETE-PROGRESS] safety blocked (even relaxed)")
                                            mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
                                    else:
                                        logger.debug(f"[SOMETE-PROGRESS] gate blocked (junme/threat) junme={junme}, threat={threat:.2f}")
                                else:
                                    logger.debug("[SOMETE-PROGRESS] does not advance hand -> keep normal judgement")
                except Exception as _e:
                    logger.debug(f"[SOMETE-PROGRESS] error: {_e}")

                # --- 連鎖鳴きオーバーライド ---
                try:
                    if (mjai_msg.get('type') in ('chi','pon')) and self._naki_chain_window_open() and mjai_msg.get('type') != 'none':
                        if self._naki_advances_hand(mjai_msg):
                            if self._naki_safety_ok_chain(mjai_msg):
                                logger.debug(f"[NAKI-CHAIN] override ACCEPT {mjai_msg['type']} "
                                             f"(count={self._naki_chain_count}, threat={self._threat_level():.2f})")
                            else:
                                logger.debug("[NAKI-CHAIN] safety blocked (even relaxed)")
                                mjai_msg = dict(mjai_msg); mjai_msg['type'] = 'none'
                        else:
                            logger.debug("[NAKI-CHAIN] does not advance hand -> keep normal judgement")
                except Exception as _e:
                    logger.debug(f"[NAKI-CHAIN] error: {_e}")

        except Exception as _e:
            logger.debug(f"[POLICY] check error: {_e}")

        # ---- reach の index を控える（流局クリック用の基準座標）----
        reach_idx = None
        try:
            for idx, operation in enumerate(operation_list):
                if operation == ACTION2TYPE["reach"]:
                    reach_idx = idx
                    break
        except Exception:
            reach_idx = None

        # ---- まずはボタンを押す対象の index を決定（※流局はリーチ座標を採用）----
        will_click = False
        target_idx = None
        if mjai_msg['type'] == 'ryukyoku' and reach_idx is not None:
            will_click = True
            target_idx = reach_idx
            logger.debug("[RYUKYOKU] use reach position for ryukyoku button")
        else:
            for idx, operation in enumerate(operation_list):
                if operation == ACTION2TYPE[mjai_msg['type']]:
                    will_click = True
                    target_idx = idx
                    break

        if not will_click:
            return return_points

        # 鳴きのときだけ pre-wait / none は短め
        if mjai_msg['type'] in {'chi','pon'}:
            pre = max(0.0, NAKI_PREWAIT)
            return_points.append(Point(-1, -1, pre))
        elif mjai_msg['type'] == 'none':
            pre = max(0.0, NAKI_NONE_PREWAIT)
            return_points.append(Point(-1, -1, pre))

        # 個別ウェイト
        if mjai_msg['type'] == 'reach':
            btn_wait = AKAGI_REACH_WAIT
        elif mjai_msg['type'] == 'hora':
            btn_wait = AKAGI_RON_WAIT
        elif mjai_msg['type'] == 'zimo':
            btn_wait = AKAGI_TSUMO_WAIT
        elif mjai_msg['type'] == 'ryukyoku':
            btn_wait = AKAGI_REACH_WAIT
        else:
            btn_wait = max(0.0, NAKI_BUTTON_WAIT + random.uniform(-0.02, 0.02))

        # 連鎖鳴きは押す直前で開始フラグ（chi/ponのみ）
        if mjai_msg['type'] in ('chi','pon'):
            self._start_naki_chain()

        # メインのクリック
        return_points.append(Point(
            LOCATION['actions'][target_idx][0],
            LOCATION['actions'][target_idx][1],
            btn_wait
        ))
        if NAKI_DOUBLE_CLICK:
            return_points.append(Point(
                LOCATION['actions'][target_idx][0],
                LOCATION['actions'][target_idx][1],
                max(0.0, 0.04 + random.uniform(-0.01, 0.01))
            ))

        # 追加の保険クリック：流局は reach 座標を再クリック
        if mjai_msg['type'] == 'ryukyoku' and reach_idx is not None and reach_idx == target_idx:
            return_points.append(Point(
                LOCATION['actions'][reach_idx][0],
                LOCATION['actions'][reach_idx][1],
                max(0.0, 0.10 + random.uniform(-0.01, 0.01))
            ))

        # リーチは候補クリック不要
        if mjai_msg['type'] == 'reach':
            return return_points

        # ---- 候補（チーの左右/中、ポンの面子選択） ----
        naki_types = {'chi','pon'}
        if mjai_msg['type'] in naki_types:
            consumed_pais_mjai = sorted(mjai_msg['consumed'], key=cmp_to_key(compare_pai))

            if mjai_msg['type'] == 'chi':
                chi_candidates = sorted(self.bot.find_chi_consume_simple(), key=cmp_to_key(compare_tehai))
                if len(chi_candidates) == 1:
                    return_points.append(Point(-1, -1, max(0.0, NAKI_SINGLE_WAIT + random.uniform(-0.02, 0.02))))
                    return return_points
                for idx, chi_candidate in enumerate(chi_candidates):
                    if consumed_pais_mjai == chi_candidate:
                        candidate_idx = int((-(len(chi_candidates)/2)+idx+0.5)*2+5)
                        return_points.append(Point(
                            LOCATION['candidates'][candidate_idx][0],
                            LOCATION['candidates'][candidate_idx][1],
                            max(0.0, NAKI_CAND_WAIT + random.uniform(-0.02, 0.02))
                        ))
                        return return_points
                mid_idx = int((-(len(chi_candidates)/2)+(len(chi_candidates)//2)+0.5)*2+5)
                return_points.append(Point(
                    LOCATION['candidates'][mid_idx][0],
                    LOCATION['candidates'][mid_idx][1],
                    max(0.0, NAKI_CAND_WAIT + random.uniform(-0.02, 0.02))
                ))
                return return_points

            elif mjai_msg['type'] == 'pon':
                pon_candidates = self.bot.find_pon_consume_simple()
                if len(pon_candidates) == 1:
                    return_points.append(Point(-1, -1, max(0.0, NAKI_SINGLE_WAIT + random.uniform(-0.02, 0.02))))
                    return return_points
                def _norm(lst): return sorted(lst, key=cmp_to_key(compare_pai))
                target_norm = _norm(consumed_pais_mjai)
                idx_match = None
                for i, cand in enumerate(pon_candidates):
                    if _norm(cand) == target_norm:
                        idx_match = i
                        break
                if idx_match is None:
                    idx_match = 1 if len(pon_candidates) >= 2 else 0
                candidate_idx = int((-(len(pon_candidates)/2)+idx_match+0.5)*2+5)
                return_points.append(Point(
                    LOCATION['candidates'][candidate_idx][0],
                    LOCATION['candidates'][candidate_idx][1],
                    max(0.0, NAKI_CAND_WAIT + random.uniform(-0.02, 0.02))
                ))
                return return_points

        return return_points

    def get_pai_coord(self, idx: int, tehais: list[str]):
        tehai_count = len(tehais)
        if idx == 13:
            pai_cord = (LOCATION['tiles'][tehai_count][0] + LOCATION['tsumo_space'], LOCATION['tiles'][tehai_count][1])
        else:
            pai_cord = LOCATION['tiles'][idx]
        return pai_cord

    # ---- 染め手ケア用：安全寄り打牌への置換ロジック ----
    def _choose_safer_tile_vs_somete(self, original: str, danger_suits: set[str], tehai: list[str]) -> str | None:
        try:
            riichi_ids = self._riichi_seat_ids()
            if riichi_ids:
                for t in tehai:
                    q = self._normalize_pai(t)
                    if any(self._is_genbutsu_to(rid, q) for rid in riichi_ids):
                        s = self._suit_of(q)
                        if s is None or s not in danger_suits:
                            return q
            for t in tehai:
                q = self._normalize_pai(t)
                s = self._suit_of(q)
                if s is None:
                    return q
                if s not in danger_suits:
                    return q
        except Exception as _e:
            logger.debug(f"[SOMETE-CARE] choose safer tile failed: {_e}")
        return None

    def click_dahai(self, mjai_msg: dict) -> list[Point]:
        dahai = mjai_msg['pai']
        tehai = self.bot.tehai_mjai
        tsumohai = self.bot.last_self_tsumo
        is_tsumohai = False

        if len(tehai) in [14,11,8,5,2] and tsumohai != "":
            tehai.remove(tsumohai)
            is_tsumohai = True

        # ===== 染め手ケア：必要なら打牌を安全寄りに置き換える =====
        try:
            if AKAGI_SOMETE_CARE_ENABLE:
                danger_suits = self._detect_somete_danger_suits()
                if danger_suits:
                    orig_suit = self._suit_of(dahai)
                    threat = self._threat_level()
                    need_care = self._fold_mode or (threat >= AKAGI_SOMETE_CARE_THREAT_GATE)
                    if need_care and orig_suit in danger_suits:
                        alt = self._choose_safer_tile_vs_somete(dahai, danger_suits, tehai)
                        if alt and alt != dahai:
                            logger.debug(f"[SOMETE-CARE] replace discard {dahai} -> {alt} (danger_suits={danger_suits}, threat={threat:.2f}, fold={self._fold_mode})")
                            dahai = alt
        except Exception as _e:
            logger.debug(f"[SOMETE-CARE] overall care error: {_e}")

        tehai = sorted(tehai, key=cmp_to_key(compare_pai))
        return_points: list[Point] = []

        if is_tsumohai and dahai == tsumohai:
            pai_coord = self.get_pai_coord(13, tehai)
            return_points.append(Point(pai_coord[0], pai_coord[1], 0.3))
            return return_points

        for i in range(13):
            if i >= len(tehai):
                break
            if dahai == tehai[i]:
                pai_coord = self.get_pai_coord(i, tehai)
                return_points.append(Point(pai_coord[0], pai_coord[1], 0.3))
                return return_points

        return return_points


# ---- utility functions ----

def compare_tehai(hand1: list[str], hand2: list[str]) -> int:
    for p1, p2 in zip(hand1, hand2):
        cmp = compare_pai(p1, p2)
        if cmp != 0:
            return cmp
    if len(hand1) > len(hand2):
        return 1
    elif len(hand1) < len(hand2):
        return -1
    else:
        return 0

def compare_pai(pai1: str, pai2: str):
    pai_order = [
        '1m','2m','3m','4m','5mr','5m','6m','7m','8m','9m',
        '1p','2p','3p','4p','5pr','5p','6p','7p','8p','9p',
        '1s','2s','3s','4s','5sr','5s','6s','7s','8s','9s',
        'E','S','W','N','P','F','C','?'
    ]
    idx1 = pai_order.index(pai1)
    idx2 = pai_order.index(pai2)
    if idx1 > idx2:
        return 1
    elif idx1 == idx2:
        return 0
    else:
        return -1
