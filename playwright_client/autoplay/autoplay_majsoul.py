import os
import time
import json
import random
from .logger import logger
from .util import Point
from settings.settings import settings

from functools import cmp_to_key
from mjai_bot.bot import AkagiBot


# ---- Tuning knobs (can be overridden by env) ----
def _getf(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None else default
    except Exception:
        return default

# 鳴きUIが出るまでの“短い”待機（秒）
NAKI_PREWAIT = _getf("AKAGI_NAKI_PREWAIT", 2.00)
# リーチUIが出るまでの“短い”待機（秒）
AKAGI_REACH_WAIT = _getf("AKAGI_REACH_WAIT", 1.00)
# ロンUIが出るまでの“短い”待機（秒）
AKAGI_RON_WAIT = _getf("AKAGI_RON_WAIT", 1.50)
# ツモUIが出るまでの“短い”待機（秒）
AKAGI_TSUMO_WAIT = _getf("AKAGI_TSUMO_WAIT", 1.50)
# 鳴きボタン（ポン/チー/カン）クリックの直後待機（秒）
NAKI_BUTTON_WAIT = _getf("AKAGI_NAKI_BUTTON_WAIT", 0.50)
# 候補（チーの左中右など）クリックの直後待機（秒）
NAKI_CAND_WAIT = _getf("AKAGI_NAKI_CAND_WAIT", 0.25)
# ボタンの“保険”ダブルクリック（0 or 1回）
NAKI_DOUBLE_CLICK = int(os.getenv("AKAGI_NAKI_DOUBLE_CLICK", "0"))

# 候補が1件でも待つ
NAKI_SINGLE_WAIT   = _getf("AKAGI_NAKI_SINGLE_WAIT", NAKI_CAND_WAIT)
# none 押下の空振り防止プリウェイト
NAKI_NONE_PREWAIT  = _getf("AKAGI_NAKI_NONE_PREWAIT", 0.20)

# ★追加: 親番の最初の打牌だけ遅らせる追加ウェイト（秒）
AKAGI_OYA_FIRST_DAHAI_EXTRA = _getf("AKAGI_OYA_FIRST_DAHAI_EXTRA", 2.00)


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
    "candidates_kan": [
        (4.325,   6.3),
        (5.4915,  6.3),
        (6.6583,  6.3),
        (7.825,   6.3),
        (8.9917,  6.3),
        (10.1583, 6.3),
        (11.325,  6.3),
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


class AutoPlayMajsoul(object):
    def __init__(self):
        self.bot: AkagiBot = None
        # 親番フラグ／「この局の最初の自分の打牌が終わったか」フラグ
        self._is_oya: bool = False
        self._first_discard_done: bool = True
        # 追加: いま自分が親かを AkagiBot の内部状態から都度判定
    def _is_oya_now(self) -> bool:
        try:
            dealer = getattr(self.bot, "_AkagiBot__dealer", None)
            myid   = getattr(self.bot, "player_id", None)
            return dealer is not None and myid is not None and int(dealer) == int(myid)
        except Exception:
            return False

    # 追加: この局の「自分の最初の打牌」かどうか（= 自分の河が空か）
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

    def act(self, mjai_msg: dict) -> list[Point]:
        if mjai_msg is None:
            return []
        logger.debug(f"Act: {mjai_msg}")
        logger.debug(f"reach_accepted: {self.bot.self_riichi_accepted}")

        # ---- 局開始イベントでフラグをリセット＆親判定 ----
        # mjai イベントに 'start_kyoku' が来たら:
        #   - oya（0-3の座席ID）と self.bot.player_id を比較して親番判定
        if mjai_msg.get("type") == "start_kyoku":
            try:
                oya = mjai_msg.get("oya", None)
                myid = getattr(self.bot, "player_id", None)
                self._is_oya = (oya is not None and myid is not None and int(oya) == int(myid))
            except Exception:
                self._is_oya = False
            self._first_discard_done = False

        # --- 打牌（自分の手番） ---
        if mjai_msg['type'] == 'dahai' and not self.bot.self_riichi_accepted:
            wait = random.uniform(1.2, 1.5)

            # 既存: 開幕（自分河が空）ならやや長め
            if not self.bot.last_kawa_tile:
                wait = max(wait, 1.5)
                try:
                    if self._is_oya_now() and self._is_my_first_discard_this_hand():
                        extra = max(0.0, AKAGI_OYA_FIRST_DAHAI_EXTRA)
                        wait += extra
                        logger.debug(f"[OYA-FIRST] extra wait applied: +{extra}s "
                                    f"(dealer={getattr(self.bot, '_AkagiBot__dealer', None)}, "
                                    f"me={getattr(self.bot, 'player_id', None)})")
                except Exception as _e:
                    logger.debug(f"[OYA-FIRST] check skipped due to: {_e}")

            # ★親番 かつ この局で最初の自分打牌 かつ 開幕（河が空）→ 追加ウェイト
            if self._is_oya and (not self._first_discard_done) and (not self.bot.last_kawa_tile):
                wait += max(0.0, AKAGI_OYA_FIRST_DAHAI_EXTRA)

            return_points = [Point(-1, -1, wait)]
            return_points += self.click_dahai(mjai_msg)

            # この局の最初の自分打牌が完了
            self._first_discard_done = True
            return return_points

        if mjai_msg['type'] == 'dahai' and self.bot.self_riichi_accepted:
            return []

        # --- 鳴き/和了/宣言など ---
        if mjai_msg['type'] in [
            'none','chi','pon','daiminkan','ankan','kakan',
            'hora','reach','ryukyoku','nukidora','zimo'
        ]:
            # ※ pre-wait は click_chiponkan 側に集約
            return self.click_chiponkan(mjai_msg)

        return []

    def click_chiponkan(self, mjai_msg: dict) -> list[Point]:
        return_points: list[Point] = []
        operation_list: list[int] = [0]

        if self.bot.can_discard:      operation_list.append(1)
        if self.bot.can_chi:          operation_list.append(2)
        if self.bot.can_pon:          operation_list.append(3)
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

        naki_types = {'chi','pon','ankan','kakan'}  # 鳴きに限定

        # ---- まずは鳴き/和了/宣言ボタンを押す ----
        will_click = False
        target_idx = None
        for idx, operation in enumerate(operation_list):
            if operation == ACTION2TYPE[mjai_msg['type']]:
                will_click = True
                target_idx = idx
                break

        if not will_click:
            return return_points  # 押す対象なし

        # 鳴きのときだけ pre-wait（UI生成ラグ吸収）
        if mjai_msg['type'] in naki_types:
            pre = max(0.0, NAKI_PREWAIT)
            return_points.append(Point(-1, -1, pre))
        elif mjai_msg['type'] == 'none':
            # 空振り防止の保険
            pre = max(0.0, NAKI_NONE_PREWAIT)
            return_points.append(Point(-1, -1, pre))

        # 個別ウェイト（reach/ron/zimo は少し長め。鳴きは短め）
        if mjai_msg['type'] == 'reach':
            btn_wait = AKAGI_REACH_WAIT
        elif mjai_msg['type'] == 'hora':
            btn_wait = AKAGI_RON_WAIT
        elif mjai_msg['type'] == 'zimo':
            btn_wait = AKAGI_TSUMO_WAIT
        else:
            btn_wait = max(0.0, NAKI_BUTTON_WAIT + random.uniform(-0.02, 0.02))

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

        # リーチは候補クリック不要
        if mjai_msg['type'] == 'reach':
            return return_points

        # ---- 候補（チーの左右/中、カンの牌選択等） ----
        if mjai_msg['type'] in naki_types:
            consumed_pais_mjai = sorted(mjai_msg['consumed'], key=cmp_to_key(compare_pai))

            if mjai_msg['type'] == 'chi':
                chi_candidates = sorted(self.bot.find_chi_consume_simple(), key=cmp_to_key(compare_tehai))
                if len(chi_candidates) == 1:
                    return_points.append(Point(-1, -1, max(0.0, NAKI_SINGLE_WAIT + random.uniform(-0.02, 0.02))))
                    return return_points  # 実クリックなし → 追加待機のみ
                for idx, chi_candidate in enumerate(chi_candidates):
                    if consumed_pais_mjai == chi_candidate:
                        candidate_idx = int((-(len(chi_candidates)/2)+idx+0.5)*2+5)
                        return_points.append(Point(
                            LOCATION['candidates'][candidate_idx][0],
                            LOCATION['candidates'][candidate_idx][1],
                            max(0.0, NAKI_CAND_WAIT + random.uniform(-0.02, 0.02))
                        ))
                        return return_points
                # 一致しなければ中央を押す
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
                    return return_points  # 実クリックなし → 追加待機のみ
                # consumed と一致候補を優先（順不同のため正規化比較）
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

            elif mjai_msg['type'] in ['ankan','kakan']:
                tehai34 = self.bot.tehai_vec34
                kan_candidates = [TILES[idx] for idx,val in enumerate(tehai34) if val >= 4]
                if len(kan_candidates) == 1:
                    return_points.append(Point(-1, -1, max(0.0, NAKI_SINGLE_WAIT + random.uniform(-0.02, 0.02))))
                    return return_points  # 実クリックなし
                consumed_pai = mjai_msg['pai'][0]
                if consumed_pai.endswith('r'):
                    consumed_pai = consumed_pai[:2]
                for idx, pai in enumerate(kan_candidates):
                    if pai == consumed_pai:
                        candidate_idx = int((-(len(kan_candidates)/2)+idx+0.5)*2+3)
                        return_points.append(Point(
                            LOCATION['candidates_kan'][candidate_idx][0],
                            LOCATION['candidates_kan'][candidate_idx][1],
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

    def click_dahai(self, mjai_msg: dict) -> list[Point]:
        dahai = mjai_msg['pai']
        tehai = self.bot.tehai_mjai
        tsumohai = self.bot.last_self_tsumo
        is_tsumohai = False

        if len(tehai) in [14,11,8,5,2] and tsumohai != "":
            tehai.remove(tsumohai)
            is_tsumohai = True

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
