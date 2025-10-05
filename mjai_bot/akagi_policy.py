# -*- coding: utf-8 -*-
"""
Akagi Policy (patched)
- 南4ラス目の安手鳴き抑止（必要打点 need_bp 連動・厳格ゲート）
- 将来基本点の自動推定（hint が無くても届く鳴きだけ許可）
- 染め手/進捗ブースト、ダマ/鳴き/リーチEVの一貫調整
- 非価値風ドラの役なしテンパイ化ガード
- チー候補スコアリング（どの形を鳴くか）
このファイル単体で既存の akagi_policy.py と置き換え可能です。
（上位層から渡されるコンテキストが足りない場合でも安全にデフォルトで動作します）
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os, math, random
from typing import List, Optional, Tuple

# ================= Env helpers =================
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

def _gets(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v not in (None, "") else default

# ================= Tunables =================
EV_MODE                   = _gets("AKAGI_EV_MODE", "placement")   # "score" or "placement"
PLACEMENT_MC_ITERS        = _geti("AKAGI_PLACEMENT_MC_ITERS", 800)  # 200-2000 目安
PLACEMENT_FAST_MODE       = _geti("AKAGI_PLACEMENT_FAST_MODE", 1)   # 1=速い擬似分布

# リーチ・鳴き・カンまわりの係数
EV_REACH_RISK_AVERSION    = _getf("AKAGI_EV_REACH_RISK_AVERSION", 1.05)
EV_REACH_MIN_BASEPOINT    = _getf("AKAGI_EV_REACH_MIN_BASEPOINT", 2600.0)
EV_REACH_TOP_LEAD_MARGIN  = _getf("AKAGI_EV_REACH_TOP_LEAD_MARGIN", 8000.0)
EV_REACH_LEAD_UPWEIGHT    = _getf("AKAGI_EV_REACH_LEAD_UPWEIGHT", 0.85)

EV_CALL_MIN_EXPECTED_PT   = _getf("AKAGI_EV_CALL_MIN_EXPECTED_POINT", 2600.0)
EV_CALL_ORAS_LAST_MIN     = _getf("AKAGI_EV_CALL_ORAS_LAST_MIN", 1300.0)
EV_YAKUHAI_PON_UNDER      = _getf("AKAGI_EV_YAKUHAI_PON_UNDER", 2000.0)

EV_FORBID_KAN_UNDER_THREAT= _geti("AKAGI_EV_FORBID_KAN_UNDER_THREAT", 1)
EV_FORBID_KAN_TOP_LEAD    = _geti("AKAGI_EV_FORBID_KAN_TOP_LEAD", 1)

# ラス回避強調
EV_LAST_ESCAPE_BONUS      = _getf("AKAGI_EV_LAST_ESCAPE_BONUS", 1.10)

# 形・安全度の重み
SHAPE_RYANMEN_BONUS       = _getf("AKAGI_SHAPE_RYANMEN_BONUS", 1.12)
SHAPE_DEAD_SHANTEN_PENAL  = _getf("AKAGI_SHAPE_DEAD_SHANTEN_PENAL", 0.92)
SAFETY_GOOD_BONUS         = _getf("AKAGI_SAFETY_GOOD_BONUS", 0.90)  # 放銃率を乗算で下げる
TURN_LATE_DEF_PENAL       = _getf("AKAGI_TURN_LATE_DEF_PENAL", 1.10) # 終盤守備寄せ

# ドラ/赤反映
DORA_VIS_BONUS_PER        = _getf("AKAGI_DORA_VIS_BONUS_PER", 0.04)
RED_COUNT_BONUS_PER       = _getf("AKAGI_RED_COUNT_BONUS_PER", 0.06)

# モデル安全側のクランプ
CLAMP_MIN_RATE            = 0.01
CLAMP_MAX_RATE            = 0.97

# 大差対策（南3のケースを含む一般化）
LAST_GAP_LARGE                = _getf("AKAGI_LAST_GAP_LARGE", 6000.0)
LAST_GAP_REACH_BOOST          = _getf("AKAGI_LAST_GAP_REACH_BOOST", 1.15)
LAST_GAP_CALL_PENALTY         = _getf("AKAGI_LAST_GAP_CALL_PENALTY", 0.85)
LAST_GAP_CALL_MIN_BASEPOINT   = _getf("AKAGI_LAST_GAP_CALL_MIN_BASEPOINT", 6400.0)
LAST_GAP_YAKUHAI_FORBID_UNDER = _getf("AKAGI_LAST_GAP_YAKUHAI_FORBID_UNDER", 2600.0)

# ---- オーラス脱ラスの“必要打点”連動ノブ ----
ORAS_ESCAPE_BUFFER                   = _geti("AKAGI_ORAS_ESCAPE_BUFFER", 300)      # 端数丸めのバッファ
ORAS_LAST_DAMA_UNDER_NEED_PENALTY    = _getf("AKAGI_ORAS_LAST_DAMA_UNDER_NEED_PENALTY", 0.60)
ORAS_LAST_CALL_UNDER_NEED_PENALTY    = _getf("AKAGI_ORAS_LAST_CALL_UNDER_NEED_PENALTY", 0.55)
ORAS_LAST_REACH_UNDER_NEED_BOOST     = _getf("AKAGI_ORAS_LAST_REACH_UNDER_NEED_BOOST", 1.15)
ORAS_LAST_CALL_MIN_RATIO             = _getf("AKAGI_ORAS_LAST_CALL_MIN_RATIO", 0.85)
CHIITOI_FORCE_REACH_NEED_BP          = _getf("AKAGI_CHIITOI_FORCE_REACH_NEED_BP", 2000.0)

# ---- 南4ラス目の安手鳴き“厳格ゲート” ----
ORAS_LAST_STRICT_CALL_ENABLE         = _geti("AKAGI_ORAS_LAST_STRICT_CALL_ENABLE", 1)
ORAS_LAST_CALL_NEED_RATIO            = _getf("AKAGI_ORAS_LAST_CALL_NEED_RATIO", 0.95)
ORAS_LAST_CALL_FUTURE_RATIO          = _getf("AKAGI_ORAS_LAST_CALL_FUTURE_RATIO", 0.90)
ORAS_LAST_CALL_PROGRESS_MIN_DELTA    = _geti("AKAGI_ORAS_LAST_CALL_PROGRESS_MIN_DELTA", 1)
ORAS_LAST_CALL_HARD_PENALTY          = _getf("AKAGI_ORAS_LAST_CALL_HARD_PENALTY", 0.45)

# ---- Dora honor guard (optional; hint only) ----
DORA_HONOR_PROTECT_TURNS   = _geti("AKAGI_DORA_HONOR_PROTECT_TURNS", 8)
DORA_HONOR_MIN_SHANTEN     = _geti("AKAGI_DORA_HONOR_MIN_SHANTEN", 1)
DORA_HONOR_RELEASE_NEED_BP = _getf("AKAGI_DORA_HONOR_RELEASE_NEED_BP", 6400.0)

# ---- リスク・押し引き調整 ----
EV_RISK_AVERSION                  = _getf("AKAGI_EV_RISK_AVERSION", 0.25)
EV_RISK_AVERSION_SOUTH_BONUS      = _getf("AKAGI_EV_RISK_SOUTH_BONUS", 0.10)
EV_RISK_AVERSION_VS_DEALER_REACH  = _getf("AKAGI_EV_RISK_VS_DEALER_REACH", 0.15)
EV_CALL_ENCOURAGE                 = _getf("AKAGI_CALL_ENCOURAGE", 0.28)
EV_CALL_ENCOURAGE_LAST            = _getf("AKAGI_CALL_ENCOURAGE_LAST", 0.25)
EV_TOP_LEAD_REACH_MIN_BASEPOINT   = _geti("AKAGI_TOP_LEAD_REACH_MIN_BP", 2000)
EV_STRICT_FORBID_KAN              = _geti("AKAGI_STRICT_FORBID_KAN", 1)
EV_CHIITOI_REACH_PENALTY          = _getf("AKAGI_CHIITOI_REACH_PENALTY", 0.30)
EV_PLACEMENT_WEIGHT               = _getf("AKAGI_PLACEMENT_WEIGHT", 0.60)

# ---- 染め手（ホンイツ/チンイツ）検知と鳴きブースト ----
HONITSU_CALL_ENABLE             = _geti("AKAGI_HONITSU_CALL_ENABLE", 1)
HONITSU_MIN_SUIT_RATIO          = _getf("AKAGI_HONITSU_MIN_SUIT_RATIO", 0.55)
HONITSU_SOFT_SUIT_RATIO         = _getf("AKAGI_HONITSU_SOFT_SUIT_RATIO", 0.65)
HONITSU_MIN_CALL_EXPECTED_BP    = _getf("AKAGI_HONITSU_MIN_CALL_EXPECTED_BP", 3600.0)
HONITSU_CALL_BOOST              = _getf("AKAGI_HONITSU_CALL_BOOST", 1.18)
HONITSU_DORA_BONUS              = _getf("AKAGI_HONITSU_DORA_BONUS", 0.06)
HONITSU_VALUE_HONOR_BONUS       = _getf("AKAGI_HONITSU_VALUE_HONOR_BONUS", 0.10)
HONITSU_PROTECT_OFFSUIT_RATIO   = _getf("AKAGI_HONITSU_PROTECT_OFFSUIT_RATIO", 0.75)

# ---- 役なしテンパイ化ガード（非価値風ドラ） ----
NOYAKU_OPEN_TENPAI_GUARD_ENABLE   = _geti("AKAGI_NOYAKU_OPEN_TENPAI_GUARD_ENABLE", 1)
NOYAKU_OPEN_TENPAI_PENALTY        = _getf("AKAGI_NOYAKU_OPEN_TENPAI_PENALTY", 0.50)
NOYAKU_GUARD_EARLY_TURNS          = _geti("AKAGI_NOYAKU_GUARD_EARLY_TURNS", 10)
NOYAKU_PROGRESS_MIN_DELTA         = _geti("AKAGI_NOYAKU_PROGRESS_MIN_DELTA", 1)
NOYAKU_MIN_FUTURE_BP_HINT         = _getf("AKAGI_NOYAKU_MIN_FUTURE_BP_HINT", 3600.0)

# ---- 将来打点（基本点）推定ノブ ----
FUTURE_BP_BASE_FU_OPEN         = _geti("AKAGI_FUTURE_BP_BASE_FU_OPEN", 30)
FUTURE_BP_TOITOI_FU_OPEN       = _geti("AKAGI_FUTURE_BP_TOITOI_FU_OPEN", 40)
FUTURE_BP_TANYAO_HAN_OPEN      = _geti("AKAGI_FUTURE_BP_TANYAO_HAN_OPEN", 1)
FUTURE_BP_YAKUHAI_HAN_OPEN     = _geti("AKAGI_FUTURE_BP_YAKUHAI_HAN_OPEN", 1)
FUTURE_BP_TOITOI_HAN_OPEN      = _geti("AKAGI_FUTURE_BP_TOITOI_HAN_OPEN", 2)
FUTURE_BP_HONITSU_HAN_OPEN     = _geti("AKAGI_FUTURE_BP_HONITSU_HAN_OPEN", 2)
FUTURE_BP_CHINITSU_HAN_OPEN    = _geti("AKAGI_FUTURE_BP_CHINITSU_HAN_OPEN", 5)
FUTURE_BP_RED_AS_DORA          = _geti("AKAGI_FUTURE_BP_RED_AS_DORA", 1)

# ================= Data Models =================
@dataclass
class ChiOption:
    tiles: List[str]
    discard_after: Optional[str] = None
    meld_suit: Optional[str] = None
    delta_shanten: int = 0
    ukeire_hint: float = 0.0
    leaves_ryanmen: int = 0
    leaves_kanchan: int = 0
    leaves_penchan: int = 0
    tanyao_feasible: bool = True
    dora_in_meld: int = 0
    keeps_value_pair: bool = False
    safety_after_genbutsu: int = 0
    future_bp_hint: float = 0.0

@dataclass
class PolicyContext:
    # スコア・局面
    my_score: int
    other_scores: List[int]
    player_id: int = 0
    is_oras: bool = False
    is_dealer: bool = False
    bakaze: str = "E"   # "E" or "S"

    # テーブル情報
    riichi_declared_count: int = 0
    opponent_threat: bool = False
    last_discard_is_yakuhai: bool = False
    last_discard_tile: Optional[str] = None
    last_discard_is_dora: bool = False
    turns_left: int = 12  # 残り手番目安（14~0）
    honba: int = 0
    kyotaku: int = 0

    # 風・ドラヒント
    seat_wind: str = "E"
    round_wind: str = "E"
    dora_markers: List[str] = field(default_factory=list)
    tiles_honor_dora: List[str] = field(default_factory=list)

    # 形・見込み
    win_rate: float = 0.18
    deal_in_rate: float = 0.07
    tempai_rate: float = 0.45
    basepoint: float = 2600.0

    # 精密化特徴
    is_ryanmen: bool = True
    shanten: int = 1                     # -1=アガリ,0=聴牌,1=一向聴,2=二向聴...
    safety_score: float = 0.5            # 0-1（高いほど安全）
    genbutsu_count: int = 3              # 現物枚数
    suji_count: int = 6                  # スジ数
    wall_info: float = 0.0               # 壁の強さ0-1
    red_count: int = 0                   # 赤の所持枚数
    dora_visible_count: int = 0          # 見えているドラ枚数
    dora_count: int = 0                  # 自分のドラ枚数（赤換算含む）
    call_speed_gain: float = 1.0
    chiitoi_like: bool = False
    toitoi_like: bool = False

    # 染め手用ヒント
    count_m: int = 0
    count_p: int = 0
    count_s: int = 0
    count_honor: int = 0
    has_value_honor: bool = False

    # 鳴き進捗・将来打点ヒント
    call_delta_shanten: int = 0
    call_meld_suit: Optional[str] = None
    call_future_bp_hint: float = 0.0  # 上位が与えない場合は自動推定


@dataclass
class PolicyDecision:
    allow_reach: bool
    allow_pon: bool
    allow_chi: bool
    allow_kan: bool
    expected_basepoint: float
    threat: bool
    oras: bool
    eval_mode: str
    reach_ev: float
    dama_ev: float
    call_ev: float
    # optional hints
    protect_tiles: List[str] = field(default_factory=list)

# ================= Helpers =================
def _lead_margin(my: int, others: List[int]) -> int:
    return my - (max(others) if others else my)

def _is_last(my: int, others: List[int]) -> bool:
    return my <= (min(others) if others else my)

def _table_threat(ctx: PolicyContext) -> bool:
    return ctx.riichi_declared_count > 0 or ctx.opponent_threat

def _gap_to_next_place(my: int, others: List[int]) -> int:
    higher = [s for s in others if s > my]
    return (min(higher) - my) if higher else 0

def _required_bp_to_escape(ctx: PolicyContext) -> float:
    gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
    if gap <= 0:
        return 0.0
    gap = max(0, gap - ctx.kyotaku * 1000)             # 供託
    gap = max(0, gap - ctx.honba * 300)                # 本場（ロン基準）
    mult = 6 if ctx.is_dealer else 4                   # 親は加点効率が高い
    need = math.ceil((gap + ORAS_ESCAPE_BUFFER) / mult / 100.0) * 100.0
    return max(1000.0, float(need))

def _clamp01(x: float) -> float:
    return max(CLAMP_MIN_RATE, min(CLAMP_MAX_RATE, x))

def _adjust_rates_by_shape_safety(ctx: PolicyContext, win: float, lose: float) -> Tuple[float, float]:
    if ctx.is_ryanmen:
        win *= SHAPE_RYANMEN_BONUS
    if ctx.shanten >= 2:
        win *= SHAPE_DEAD_SHANTEN_PENAL
    win *= (1.0 + ctx.dora_visible_count * DORA_VIS_BONUS_PER + ctx.red_count * RED_COUNT_BONUS_PER)
    safety_factor = (0.5 * ctx.safety_score) + (0.02 * ctx.genbutsu_count) + (0.01 * ctx.suji_count) + (0.1 * ctx.wall_info)
    if safety_factor > 0.6:
        lose *= SAFETY_GOOD_BONUS
    if ctx.turns_left <= 5:
        lose *= TURN_LATE_DEF_PENAL
    return _clamp01(win), _clamp01(lose)

# ================= Placement EV (Monte Carlo) =================
def _score_change_samples(bp: float, dealer: bool) -> List[int]:
    samples = []
    mults = [1.0, 1.2, 1.5, 2.0]
    probs = [0.65, 0.20, 0.10, 0.05] if PLACEMENT_FAST_MODE else [0.55, 0.22, 0.15, 0.08]
    for m, p in zip(mults, probs):
        n = max(1, int(PLACEMENT_MC_ITERS * p))
        val = int(bp * m)
        if dealer:
            val = int(val * 1.2)
        samples += [val] * n
    random.shuffle(samples)
    return samples[:PLACEMENT_MC_ITERS]

def _simulate_placement_ev(ctx: PolicyContext, win: float, lose: float, bp: float) -> float:
    my = ctx.my_score
    others = list(ctx.other_scores)
    N = PLACEMENT_MC_ITERS
    gain_samples = _score_change_samples(bp, ctx.is_dealer)

    expected_rank = 0.0
    for i in range(N):
        r = random.random()
        my_score = my
        other_scores = others[:]

        if r < win:
            delta = gain_samples[i]
            my_score += delta
        elif r > 1.0 - lose:
            delta = gain_samples[i]
            my_score -= int(delta * (1.0 if ctx.is_dealer else 0.9))

        if PLACEMENT_FAST_MODE:
            jitter = 200 * random.choice([-1, 0, 0, 1])
            j_idx = random.randrange(3) if other_scores else 0
            if other_scores:
                other_scores[j_idx] += jitter
        else:
            for j in range(len(other_scores)):
                other_scores[j] += random.choice([-200, 0, 0, 200])

        all_scores = other_scores + [my_score]
        rank = 1 + sum(1 for s in all_scores if s > my_score)
        expected_rank += rank

    expected_rank /= N
    return -expected_rank

# ---- 染め手スコア ----
def _honitsu_score(ctx: PolicyContext):
    m, p, s = max(0, ctx.count_m), max(0, ctx.count_p), max(0, ctx.count_s)
    suits_total = m + p + s
    if suits_total < 6:
        return 0.0, None
    suit_counts = {'m': m, 'p': p, 's': s}
    main_suit = max(suit_counts, key=lambda k: suit_counts[k])
    ratio = suit_counts[main_suit] / float(max(1, suits_total))
    return min(1.0, ratio), main_suit

# ---- 価値牌判定 ----
def _is_value_honor(tile: Optional[str], seat_wind: str, round_wind: str) -> bool:
    if tile is None:
        return False
    if tile in ("P", "F", "C"):
        return True
    if tile in ("E", "S", "W", "N") and tile in (seat_wind, round_wind):
        return True
    return False

# ---- 基本点計算（fu/han → basepoint） ----
def _basepoint_from_fu_han(fu: int, han: int) -> int:
    fu = int(math.ceil(max(20, fu) / 10.0) * 10)
    if han >= 13:
        return 8000
    if 11 <= han <= 12:
        return 6000
    if 8 <= han <= 10:
        return 4000
    if 6 <= han <= 7:
        return 3000
    if han >= 5:
        return 2000
    if (han == 4 and fu >= 40) or (han == 3 and fu >= 70):
        return 2000
    return min(2000, fu * (2 ** (han + 2)))

# ---- 鳴き後の将来基本点を推定 ----
def _estimate_future_bp_for_call(ctx: PolicyContext) -> int:
    ratio, main_suit = _honitsu_score(ctx)
    is_honitsu = ratio >= 0.70 and (ctx.count_honor > 0 or main_suit is not None)
    is_chinitsu = ratio >= 0.85 and ctx.count_honor == 0
    toitoi = bool(getattr(ctx, "toitoi_like", False))
    middle_tiles_bias = (ctx.count_honor <= 2) and (ctx.call_meld_suit in ("m", "p", "s"))
    tanyao_feasible = middle_tiles_bias
    dora_total = max(0, getattr(ctx, "dora_count", 0)) + max(0, getattr(ctx, "red_count", 0)) * FUTURE_BP_RED_AS_DORA

    han = 0
    fu  = FUTURE_BP_BASE_FU_OPEN
    if toitoi:
        han += FUTURE_BP_TOITOI_HAN_OPEN
        fu   = max(fu, FUTURE_BP_TOITOI_FU_OPEN)
    if is_chinitsu:
        han += FUTURE_BP_CHINITSU_HAN_OPEN
    elif is_honitsu:
        han += FUTURE_BP_HONITSU_HAN_OPEN
    if tanyao_feasible:
        han += FUTURE_BP_TANYAO_HAN_OPEN
    if ctx.has_value_honor:
        han += FUTURE_BP_YAKUHAI_HAN_OPEN
    han += dora_total

    bp = _basepoint_from_fu_han(fu, han)
    return int(bp)

# ================= EV Engine =================
class ExpectedValueEngine:
    """拡張EVエンジン：スコアEV/順位EVを切り替え可能"""

    @staticmethod
    def _reach_ev(ctx: PolicyContext) -> float:
        win = ctx.win_rate
        lose = ctx.deal_in_rate
        win, lose = _adjust_rates_by_shape_safety(ctx, win, lose)
        bp  = max(1000.0, ctx.basepoint)
        reach_bonus = 1.3 if ctx.is_dealer else 1.2
        if _lead_margin(ctx.my_score, ctx.other_scores) >= EV_REACH_TOP_LEAD_MARGIN:
            reach_bonus *= EV_REACH_LEAD_UPWEIGHT
        gain = win * bp * reach_bonus
        cost = lose * bp * EV_REACH_RISK_AVERSION * (1.2 if _table_threat(ctx) else 1.0)
        if _is_last(ctx.my_score, ctx.other_scores):
            gain *= EV_LAST_ESCAPE_BONUS
            gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
            if gap >= LAST_GAP_LARGE and ctx.turns_left <= 6:
                gain *= LAST_GAP_REACH_BOOST
        if EV_MODE == "placement":
            return _simulate_placement_ev(ctx, win, lose, bp * reach_bonus)
        return gain - cost

    @staticmethod
    def _dama_ev(ctx: PolicyContext) -> float:
        win = ctx.win_rate * 0.8
        lose = ctx.deal_in_rate * 0.8
        win, lose = _adjust_rates_by_shape_safety(ctx, win, lose)
        bp  = max(1000.0, ctx.basepoint)
        gain = win * bp
        cost = lose * bp * (EV_REACH_RISK_AVERSION - 0.1)
        if _is_last(ctx.my_score, ctx.other_scores):
            gain *= (EV_LAST_ESCAPE_BONUS - 0.05)
        if EV_MODE == "placement":
            return _simulate_placement_ev(ctx, win, lose, bp)
        return gain - cost

    @staticmethod
    def _call_ev(ctx: PolicyContext) -> float:
        win = min(0.95, ctx.win_rate * (0.9 + 0.25 * ctx.call_speed_gain))
        lose = ctx.deal_in_rate * (1.05 + 0.15 * (1.0 if _table_threat(ctx) else 0.0))
        win, lose = _adjust_rates_by_shape_safety(ctx, win, lose)
        bp  = max(1000.0, ctx.basepoint * (0.75 + 0.1 * ctx.call_speed_gain))
        gain = win * bp
        cost = lose * bp * EV_REACH_RISK_AVERSION
        is_last = _is_last(ctx.my_score, ctx.other_scores)
        if is_last and ctx.is_oras:
            gain *= (EV_LAST_ESCAPE_BONUS + 0.05)
        if is_last:
            gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
            if gap >= LAST_GAP_LARGE and ctx.turns_left <= 6:
                gain *= LAST_GAP_CALL_PENALTY

        # 染め手候補で鳴きEVをブースト
        if HONITSU_CALL_ENABLE:
            ratio, main_suit = _honitsu_score(ctx)
            if ratio >= HONITSU_MIN_SUIT_RATIO:
                suit_bonus = 1.0 + (ratio - HONITSU_MIN_SUIT_RATIO) * 0.6
                dora_bonus = 1.0 + ctx.dora_count * HONITSU_DORA_BONUS
                value_bonus = 1.0 + (HONITSU_VALUE_HONOR_BONUS if ctx.has_value_honor else 0.0)
                bp *= HONITSU_CALL_BOOST * suit_bonus * dora_bonus * value_bonus
                gain = win * bp
                # 進捗があれば更に押す
                progress = (ctx.call_delta_shanten >= 1) and ((ctx.call_meld_suit is None) or (main_suit is None) or (ctx.call_meld_suit == main_suit))
                if progress:
                    bp *= 1.15
                    gain = win * bp
                if bp < HONITSU_MIN_CALL_EXPECTED_BP:
                    gain = win * max(1000.0, ctx.basepoint)

        if EV_MODE == "placement":
            return _simulate_placement_ev(ctx, win, lose, bp)
        return gain - cost

    @staticmethod
    def decide(ctx: PolicyContext) -> PolicyDecision:
        # ===== EV計算 =====
        reach_ev = ExpectedValueEngine._reach_ev(ctx)
        dama_ev  = ExpectedValueEngine._dama_ev(ctx)
        call_ev  = ExpectedValueEngine._call_ev(ctx)

        # --- オーラス脱ラス必要打点でEVを動的調整 ---
        need_bp = 0.0
        is_last_flag = _is_last(ctx.my_score, ctx.other_scores)
        if ctx.is_oras and is_last_flag:
            need_bp = _required_bp_to_escape(ctx)
            if ctx.basepoint < need_bp:
                reach_ev *= ORAS_LAST_REACH_UNDER_NEED_BOOST
                dama_ev  *= ORAS_LAST_DAMA_UNDER_NEED_PENALTY
                call_ev  *= ORAS_LAST_CALL_UNDER_NEED_PENALTY
            if ctx.basepoint < need_bp * ORAS_LAST_CALL_MIN_RATIO:
                allow_call_by_need = False
            else:
                allow_call_by_need = True
        else:
            allow_call_by_need = True

        # ====== リスク回避：EVのソフト調整 ======
        threat = _table_threat(ctx)
        south  = bool(ctx.is_oras) or (getattr(ctx, "bakaze", "E") == "S")
        top_lead = ctx.my_score == max([ctx.my_score] + ctx.other_scores)

        vs_dealer_reach = bool(getattr(ctx, "dealer_reached", False))

        risk = EV_RISK_AVERSION
        if south:
            risk += EV_RISK_AVERSION_SOUTH_BONUS
        if vs_dealer_reach:
            risk += EV_RISK_AVERSION_VS_DEALER_REACH
        if EV_MODE == "placement":
            risk += 0.25 * EV_PLACEMENT_WEIGHT

        # チートイ弱待ちの抑制（相対EVで）
        adj_reach_ev = reach_ev
        if threat:
            adj_reach_ev -= abs(reach_ev) * risk
        if ctx.chiitoi_like:
            adj_reach_ev -= abs(reach_ev) * EV_CHIITOI_REACH_PENALTY

        adj_call_ev = call_ev
        encourage = EV_CALL_ENCOURAGE + (EV_CALL_ENCOURAGE_LAST if is_last_flag else 0.0)
        adj_call_ev += abs(call_ev) * encourage

        # 非価値風ドラの不用意ポンを抑制（役なしテンパイ化ガード）
        noyaku_guard = False
        if NOYAKU_OPEN_TENPAI_GUARD_ENABLE and ctx.last_discard_is_yakuhai:
            is_value = _is_value_honor(getattr(ctx, "last_discard_tile", None), getattr(ctx, "seat_wind", "E"), getattr(ctx, "round_wind", "E"))
            is_nonvalue_honor_dora = (not is_value) and bool(getattr(ctx, "last_discard_is_dora", False))
            if is_nonvalue_honor_dora:
                early = ctx.turns_left >= NOYAKU_GUARD_EARLY_TURNS
                honitsu_ratio, _ = _honitsu_score(ctx)
                honitsu_ok  = (honitsu_ratio >= HONITSU_SOFT_SUIT_RATIO)
                toitoi_ok   = bool(getattr(ctx, "toitoi_like", False))
                progress_ok = (ctx.call_delta_shanten >= NOYAKU_PROGRESS_MIN_DELTA) and (float(getattr(ctx, "call_future_bp_hint", 0.0)) >= NOYAKU_MIN_FUTURE_BP_HINT)
                noyaku_guard = early and not (honitsu_ok or toitoi_ok or progress_ok)
                if noyaku_guard:
                    adj_call_ev *= NOYAKU_OPEN_TENPAI_PENALTY

        # ---- 南4ラス目・安手鳴きの厳格ゲート（EVにも適用） ----
        strict_ng = False
        if ORAS_LAST_STRICT_CALL_ENABLE and ctx.is_oras and is_last_flag:
            future_bp_hint = float(max(0.0, getattr(ctx, "call_future_bp_hint", 0.0)))
            if future_bp_hint <= 0.0:
                future_bp_hint = float(_estimate_future_bp_for_call(ctx))
            future_bp = future_bp_hint
            progress  = int(getattr(ctx, "call_delta_shanten", 0))
            exception = (progress >= ORAS_LAST_CALL_PROGRESS_MIN_DELTA) and (need_bp > 0) and (future_bp >= need_bp * ORAS_LAST_CALL_FUTURE_RATIO)
            if need_bp > 0 and ctx.basepoint < need_bp * ORAS_LAST_CALL_NEED_RATIO and not exception:
                strict_ng = True
                adj_call_ev *= ORAS_LAST_CALL_HARD_PENALTY

        # ===== Reach可否 =====
        allow_reach = True
        if ctx.basepoint < EV_REACH_MIN_BASEPOINT:
            allow_reach = False
        if adj_reach_ev < max(0.0, dama_ev, adj_call_ev):
            allow_reach = False
        if _lead_margin(ctx.my_score, ctx.other_scores) >= EV_REACH_TOP_LEAD_MARGIN and ctx.basepoint < (EV_REACH_MIN_BASEPOINT + 800):
            allow_reach = False
        if top_lead and threat and ctx.basepoint < EV_TOP_LEAD_REACH_MIN_BASEPOINT:
            allow_reach = False
        if ctx.is_oras and is_last_flag and ctx.chiitoi_like and ctx.basepoint < max(need_bp, CHIITOI_FORCE_REACH_NEED_BP):
            allow_reach = True
            if dama_ev >= reach_ev:
                dama_ev *= ORAS_LAST_DAMA_UNDER_NEED_PENALTY

        # ===== Pon/Chi可否 =====
        allow_pon = True
        if ctx.last_discard_is_yakuhai and ctx.basepoint < EV_YAKUHAI_PON_UNDER:
            allow_pon = False
        min_call = EV_CALL_ORAS_LAST_MIN if (ctx.is_oras and _is_last(ctx.my_score, ctx.other_scores)) else EV_CALL_MIN_EXPECTED_PT
        if ctx.basepoint < min_call and not (ctx.is_oras and _is_last(ctx.my_score, ctx.other_scores)):
            allow_pon = False
        if adj_call_ev < -200.0 and not (ctx.is_oras and _is_last(ctx.my_score, ctx.other_scores)):
            allow_pon = False
        if _is_last(ctx.my_score, ctx.other_scores):
            gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
            if gap >= LAST_GAP_LARGE and ctx.turns_left <= 6:
                if ctx.last_discard_is_yakuhai and ctx.basepoint < LAST_GAP_YAKUHAI_FORBID_UNDER:
                    allow_pon = False
                if ctx.basepoint < LAST_GAP_CALL_MIN_BASEPOINT:
                    allow_pon = False
            if ctx.is_oras and need_bp > 0:
                if not allow_call_by_need or strict_ng:
                    allow_pon = False
        if noyaku_guard:
            allow_pon = False
        allow_chi = allow_pon

        # ===== Kan可否 =====
        allow_kan = True
        if (EV_FORBID_KAN_UNDER_THREAT and _table_threat(ctx)) or (EV_STRICT_FORBID_KAN and threat and (top_lead or south)):
            allow_kan = False
        if EV_FORBID_KAN_TOP_LEAD and _lead_margin(ctx.my_score, ctx.other_scores) >= EV_REACH_TOP_LEAD_MARGIN:
            allow_kan = False

        # ---- Dora honor guard (hint to tile selector) ----
        protect_tiles: List[str] = []
        def _has_honor_dora(ctx: PolicyContext) -> bool:
            if ctx.tiles_honor_dora:
                return True
            return False
        if _has_honor_dora(ctx):
            early = ctx.turns_left >= DORA_HONOR_PROTECT_TURNS
            shape_ok = ctx.shanten >= DORA_HONOR_MIN_SHANTEN
            released = (ctx.is_oras and is_last_flag and _required_bp_to_escape(ctx) >= DORA_HONOR_RELEASE_NEED_BP)
            if early and shape_ok and not released:
                protect_tiles = list(ctx.tiles_honor_dora)


        try:
            gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
            print(f"[POLICY][GAP] last={_is_last(ctx.my_score, ctx.other_scores)} gap={gap} need_bp={need_bp:.0f} "
                  f"turns_left={ctx.turns_left} base={ctx.basepoint:.0f} "
                  f"EV reach/dama/call={adj_reach_ev:.1f}/{dama_ev:.1f}/{adj_call_ev:.1f} "
                  f"strict_ng={strict_ng} progressΔ={getattr(ctx,'call_delta_shanten',0)} "
                  f"future_bp={float(getattr(ctx,'call_future_bp_hint',0.0) or _estimate_future_bp_for_call(ctx)):.0f} "
                  f"allow R/P/C/K={allow_reach}/{allow_pon}/{allow_chi}/{allow_kan}")
        except Exception:
            pass

        return PolicyDecision(
            allow_reach=allow_reach,
            allow_pon=allow_pon,
            allow_chi=allow_chi,
            allow_kan=allow_kan,
            expected_basepoint=float(ctx.basepoint),
            threat=_table_threat(ctx),
            oras=bool(ctx.is_oras),
            eval_mode=EV_MODE,
            reach_ev=float(adj_reach_ev),
            dama_ev=float(dama_ev),
            call_ev=float(adj_call_ev),
            protect_tiles=protect_tiles,
        )
