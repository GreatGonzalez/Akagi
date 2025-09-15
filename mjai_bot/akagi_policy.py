# mjai_bot/akagi_policy.py
from dataclasses import dataclass
import os, math, random
from typing import List, Optional

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
EV_MODE                   = _gets("AKAGI_EV_MODE", "score")   # "score" or "placement"
PLACEMENT_MC_ITERS        = _geti("AKAGI_PLACEMENT_MC_ITERS", 600)  # 200-2000 目安
PLACEMENT_FAST_MODE       = _geti("AKAGI_PLACEMENT_FAST_MODE", 1)   # 1=速い擬似分布

# リーチ・鳴き・カンまわりの係数
EV_REACH_RISK_AVERSION    = _getf("AKAGI_EV_REACH_RISK_AVERSION", 1.05)
EV_REACH_MIN_BASEPOINT    = _getf("AKAGI_EV_REACH_MIN_BASEPOINT", 2600.0)
EV_REACH_TOP_LEAD_MARGIN  = _getf("AKAGI_EV_REACH_TOP_LEAD_MARGIN", 8000.0)
EV_REACH_LEAD_UPWEIGHT    = _getf("AKAGI_EV_REACH_LEAD_UPWEIGHT", 0.85)

EV_CALL_MIN_EXPECTED_PT   = _getf("AKAGI_EV_CALL_MIN_EXPECTED_POINT", 2600.0)
EV_CALL_ORAS_LAST_MIN     = _getf("AKAGI_EV_CALL_ORAS_LAST_MIN", 1000.0)
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

# ================= Data Models =================
@dataclass
class PolicyContext:
    # スコア・局面
    my_score: int
    other_scores: List[int]
    player_id: int = 0
    is_oras: bool = False
    is_dealer: bool = False

    # テーブル情報
    riichi_declared_count: int = 0
    opponent_threat: bool = False
    last_discard_is_yakuhai: bool = False
    turns_left: int = 12  # 残り手番目安（14~0）

    # 形・見込み
    win_rate: float = 0.18
    deal_in_rate: float = 0.07
    tempai_rate: float = 0.45
    basepoint: float = 2600.0

    # 精密化特徴
    is_ryanmen: bool = True
    shanten: int = 1                     # -1=アガリ,0=聴牌,1=一向聴,2=二向聴...
    safety_score: float = 0.5            # 0-1（高いほど安全）
    genbutsu_count: int = 3              # 自身が持つ現物の枚数
    suji_count: int = 6                  # スジ数
    wall_info: float = 0.0               # 壁の強さ0-1
    red_count: int = 0                   # 赤5の所持枚数
    dora_visible_count: int = 0          # 見えているドラ枚数（味方/場合含む）
    call_speed_gain: float = 1.0

@dataclass
class PolicyDecision:
    allow_reach: bool
    allow_pon: bool
    allow_chi: bool
    allow_kan: bool
    # 補助
    expected_basepoint: float
    threat: bool
    oras: bool
    eval_mode: str
    reach_ev: float
    dama_ev: float
    call_ev: float

# ================= Helpers =================
def _lead_margin(my: int, others: List[int]) -> int:
    return my - (max(others) if others else my)

def _is_last(my: int, others: List[int]) -> bool:
    return my <= (min(others) if others else my)

def _table_threat(ctx: PolicyContext) -> bool:
    return ctx.riichi_declared_count > 0 or ctx.opponent_threat

def _clamp01(x: float) -> float:
    return max(CLAMP_MIN_RATE, min(CLAMP_MAX_RATE, x))

def _adjust_rates_by_shape_safety(ctx: PolicyContext, win: float, lose: float):
    """形（両面/シャンテン）と安全度、巡目で win/lose を微調整"""
    # 形: 両面は上振れ、死にシャンテンは下振れ
    if ctx.is_ryanmen:
        win *= SHAPE_RYANMEN_BONUS
    if ctx.shanten >= 2:
        win *= SHAPE_DEAD_SHANTEN_PENAL

    # ドラ/赤の打点上振れ → 実質的に勝率・打点が伸びる方向で効く
    win *= (1.0 + ctx.dora_visible_count * DORA_VIS_BONUS_PER + ctx.red_count * RED_COUNT_BONUS_PER)

    # 安全度: 現物・スジ・壁枚数が潤沢なら放銃率を減らす
    safety_factor = (0.5 * ctx.safety_score) + (0.02 * ctx.genbutsu_count) + (0.01 * ctx.suji_count) + (0.1 * ctx.wall_info)
    if safety_factor > 0.6:
        lose *= SAFETY_GOOD_BONUS

    # 終盤は押しの負債が重くなりがち → lose 補正
    if ctx.turns_left <= 5:
        lose *= TURN_LATE_DEF_PENAL

    return _clamp01(win), _clamp01(lose)

# ================= Placement EV (Monte Carlo) =================
def _score_change_samples(bp: float, dealer: bool) -> List[int]:
    """打点分布の簡易サンプル（高速モード時はランダム幅を小さめに）"""
    # ベース点から満貫/ハネマンの上振れを少量混ぜる
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
    """現局面だけを対象に、アクション選択による着順期待値の差を評価（簡易）"""
    my = ctx.my_score
    others = list(ctx.other_scores)
    N = PLACEMENT_MC_ITERS
    gain_samples = _score_change_samples(bp, ctx.is_dealer)

    expected_rank = 0.0
    for i in range(N):
        # 1試行: 自分が和了 or 放銃 or 流局（何も無し）
        r = random.random()
        my_score = my
        other_scores = others[:]

        if r < win:
            # 自分のアガリ：+bp（+裏・ツモ等の上振れをサンプルで代用）
            delta = gain_samples[i]
            my_score += delta
            # ランダムな相手から供託/直撃の差分は簡易化して無視（高速化）
        elif r > 1.0 - lose:
            # 放銃：-bp 等価の損失（実際は相手の加点だが順位EVへの寄与は同等視）
            delta = gain_samples[i]
            my_score -= int(delta * (1.0 if ctx.is_dealer else 0.9))
        else:
            # 何も無し（進行のみ）
            pass

        # ランダムな他家の増減（他家同士のやり取り）を少し混ぜて順位移動の不確実性を表現
        if PLACEMENT_FAST_MODE:
            jitter = 200 * random.choice([-1, 0, 0, 1])
            j_idx = random.randrange(3) if other_scores else 0
            if other_scores:
                other_scores[j_idx] += jitter
        else:
            for j in range(len(other_scores)):
                other_scores[j] += random.choice([-200, 0, 0, 200])

        # ランク（1=トップ…4=ラス）を算出
        all_scores = other_scores + [my_score]
        rank = 1 + sum(1 for s in all_scores if s > my_score)
        expected_rank += rank

    expected_rank /= N
    # 着順が良いほど評価が高い → EVとしては -rank を返す
    return -expected_rank

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
        if _is_last(ctx.my_score, ctx.other_scores) and ctx.is_oras:
            gain *= (EV_LAST_ESCAPE_BONUS + 0.05)

        if EV_MODE == "placement":
            return _simulate_placement_ev(ctx, win, lose, bp)
        return gain - cost

    @staticmethod
    def decide(ctx: PolicyContext) -> PolicyDecision:
        # ===== EV計算 =====
        reach_ev = ExpectedValueEngine._reach_ev(ctx)
        dama_ev  = ExpectedValueEngine._dama_ev(ctx)
        call_ev  = ExpectedValueEngine._call_ev(ctx)

        # ===== Reach可否 =====
        allow_reach = True
        if ctx.basepoint < EV_REACH_MIN_BASEPOINT:
            allow_reach = False
        if reach_ev < max(0.0, dama_ev):
            allow_reach = False
        if _lead_margin(ctx.my_score, ctx.other_scores) >= EV_REACH_TOP_LEAD_MARGIN and ctx.basepoint < (EV_REACH_MIN_BASEPOINT + 800):
            allow_reach = False

        # ===== Pon/Chi可否 =====
        allow_pon = True
        if ctx.last_discard_is_yakuhai and ctx.basepoint < EV_YAKUHAI_PON_UNDER:
            allow_pon = False
        min_call = EV_CALL_ORAS_LAST_MIN if (ctx.is_oras and _is_last(ctx.my_score, ctx.other_scores)) else EV_CALL_MIN_EXPECTED_PT
        if ctx.basepoint < min_call and not (ctx.is_oras and _is_last(ctx.my_score, ctx.other_scores)):
            allow_pon = False
        if call_ev < -200.0 and not (ctx.is_oras and _is_last(ctx.my_score, ctx.other_scores)):
            allow_pon = False

        allow_chi = allow_pon

        # ===== Kan可否 =====
        allow_kan = True
        if EV_FORBID_KAN_UNDER_THREAT and _table_threat(ctx):
            allow_kan = False
        if EV_FORBID_KAN_TOP_LEAD and _lead_margin(ctx.my_score, ctx.other_scores) >= EV_REACH_TOP_LEAD_MARGIN:
            allow_kan = False

        return PolicyDecision(
            allow_reach=allow_reach,
            allow_pon=allow_pon,
            allow_chi=allow_chi,
            allow_kan=allow_kan,
            expected_basepoint=float(ctx.basepoint),
            threat=_table_threat(ctx),
            oras=bool(ctx.is_oras),
            eval_mode=EV_MODE,
            reach_ev=float(reach_ev),
            dama_ev=float(dama_ev),
            call_ev=float(call_ev),
        )
