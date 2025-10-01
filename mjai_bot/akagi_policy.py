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

# ---- New: オーラス脱ラスの“必要打点”連動ノブ ----
ORAS_ESCAPE_BUFFER                   = _geti("AKAGI_ORAS_ESCAPE_BUFFER", 300)      # 端数丸めのバッファ
ORAS_LAST_DAMA_UNDER_NEED_PENALTY    = _getf("AKAGI_ORAS_LAST_DAMA_UNDER_NEED_PENALTY", 0.60)
ORAS_LAST_CALL_UNDER_NEED_PENALTY    = _getf("AKAGI_ORAS_LAST_CALL_UNDER_NEED_PENALTY", 0.55)
ORAS_LAST_REACH_UNDER_NEED_BOOST     = _getf("AKAGI_ORAS_LAST_REACH_UNDER_NEED_BOOST", 1.15)
CHIITOI_FORCE_REACH_NEED_BP          = _getf("AKAGI_CHIITOI_FORCE_REACH_NEED_BP", 2000.0)


# ---- New: リスク・押し引き調整（既定は控えめ）----
# 脅威下でのリーチEV減衰（例: 0.0=無効, 1.0=強）
EV_RISK_AVERSION                  = _getf("AKAGI_EV_RISK_AVERSION", 0.25)
# 南場(オーラス含む)の追加減衰（リーチ押し過ぎ対策）
EV_RISK_AVERSION_SOUTH_BONUS      = _getf("AKAGI_EV_RISK_SOUTH_BONUS", 0.10)
# 親リーチ(他家)がいる時の追加減衰
EV_RISK_AVERSION_VS_DEALER_REACH  = _getf("AKAGI_EV_RISK_VS_DEALER_REACH", 0.15)
# テンパイまで浅い副露の加点（和了率アップ寄り）
EV_CALL_ENCOURAGE                 = _getf("AKAGI_CALL_ENCOURAGE", 0.25)
# ラス目時の更なる副露加点（ラス回避）
EV_CALL_ENCOURAGE_LAST            = _getf("AKAGI_CALL_ENCOURAGE_LAST", 0.25)
# トップ目の安手リーチ抑制：この素点未満かつ脅威ありで抑制
EV_TOP_LEAD_REACH_MIN_BASEPOINT   = _geti("AKAGI_TOP_LEAD_REACH_MIN_BP", 2000)
# カンの抑制を強める（トップ目・脅威下）
EV_STRICT_FORBID_KAN              = _geti("AKAGI_STRICT_FORBID_KAN", 1)
# チートイ（推定）時のリーチペナルティ（弱待ちダマ寄り）
EV_CHIITOI_REACH_PENALTY          = _getf("AKAGI_CHIITOI_REACH_PENALTY", 0.30)
# placement重視時の押し引き強度（0-1、1で強くラス回避）
EV_PLACEMENT_WEIGHT               = _getf("AKAGI_PLACEMENT_WEIGHT", 0.60)
ORAS_LAST_CALL_MIN_RATIO             = _getf("AKAGI_ORAS_LAST_CALL_MIN_RATIO", 0.85)

# ---- New: 染め手（ホンイツ/チンイツ）検知と鳴きブースト ----
HONITSU_CALL_ENABLE             = _geti("AKAGI_HONITSU_CALL_ENABLE", 1)      # 0で無効
HONITSU_MIN_SUIT_RATIO          = _getf("AKAGI_HONITSU_MIN_SUIT_RATIO", 0.55) # 1色占有率の閾値
HONITSU_SOFT_SUIT_RATIO         = _getf("AKAGI_HONITSU_SOFT_SUIT_RATIO", 0.65) # 高いほど強ブースト
HONITSU_MIN_CALL_EXPECTED_BP    = _getf("AKAGI_HONITSU_MIN_CALL_EXPECTED_BP", 3600.0) # 安手鳴き防止
HONITSU_CALL_BOOST              = _getf("AKAGI_HONITSU_CALL_BOOST", 1.18)    # 鳴きEVに掛ける係数
HONITSU_DORA_BONUS              = _getf("AKAGI_HONITSU_DORA_BONUS", 0.06)    # ドラ1枚あたりの上乗せ
HONITSU_VALUE_HONOR_BONUS       = _getf("AKAGI_HONITSU_VALUE_HONOR_BONUS", 0.10) # 役牌を抱えている時
HONITSU_PROTECT_OFFSUIT_RATIO   = _getf("AKAGI_HONITSU_PROTECT_OFFSUIT_RATIO", 0.75) # 牌選択層へのヒント
HONITSU_PROGRESS_ENABLE         = _geti("AKAGI_HONITSU_PROGRESS_ENABLE", 1)
HONITSU_PROGRESS_MIN_DELTA      = _geti("AKAGI_HONITSU_PROGRESS_MIN_DELTA", 1)   # Δシャンテン ≧ 1 を進捗とみなす
HONITSU_PROGRESS_CALL_BOOST     = _getf("AKAGI_HONITSU_PROGRESS_CALL_BOOST", 1.15)
HONITSU_PROGRESS_NEED_RELIEF    = _getf("AKAGI_HONITSU_PROGRESS_NEED_RELIEF", 0.80) # need_bp×0.80 まで鳴き門を緩める
 
# ================= Data Models =================
@dataclass
class PolicyContext:
    # スコア・局面
    my_score: int
    other_scores: List[int]
    player_id: int = 0
    is_oras: bool = False
    is_dealer: bool = False
    bakaze: str = "E"

    # テーブル情報
    riichi_declared_count: int = 0
    opponent_threat: bool = False
    last_discard_is_yakuhai: bool = False
    turns_left: int = 12  # 残り手番目安（14~0）
    honba: int = 0
    kyotaku: int = 0

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
    chiitoi_like: bool = False
    # 染め手用の軽量カウント（無ければ0でOK：後方互換）
    count_m: int = 0
    count_p: int = 0
    count_s: int = 0
    count_honor: int = 0
    dora_count: int = 0
    seat_wind: str = "E"
    round_wind: str = "E"
    has_value_honor: bool = False  # 自風/場風/三元のいずれかを持っているか（簡易）
    call_delta_shanten: int = 0             # その鳴きをすると何段階シャンテンが縮むか（0=変化なし）
    call_meld_suit: Optional[str] = None    # 'm'/'p'/'s'/None（鳴きメルドの主スート）
    call_future_bp_hint: float = 0.0        # 鳴いた先に見込める概算基本点（分からなければ0）
 
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

def _gap_to_next_place(my: int, others: List[int]) -> int:
    """自分より上の最も近いスコアとの差（上がいなければ0）。ラス目なら3位との差。"""
    higher = [s for s in others if s > my]
    return (min(higher) - my) if higher else 0

# ---- New: 染め手スコア（0-1）と対象スートの推定 ----
def _honitsu_score(ctx: PolicyContext):
    # 数牌合計と各スート比率
    m, p, s = max(0, ctx.count_m), max(0, ctx.count_p), max(0, ctx.count_s)
    suits_total = m + p + s
    if suits_total < 6:  # 牌姿が散っている/情報不足
        return 0.0, None
    suit_counts = {'m': m, 'p': p, 's': s}
    main_suit = max(suit_counts, key=lambda k: suit_counts[k])
    ratio = suit_counts[main_suit] / max(1, suits_total)
    return min(1.0, ratio), main_suit

def _required_bp_to_escape(ctx: PolicyContext) -> float:
    gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
    if gap <= 0:
        return 0.0
    # 期待上積み分を控えめに控除（局所近似）
    gap = max(0, gap - ctx.kyotaku * 1000)             # 供託
    gap = max(0, gap - ctx.honba * 300)                # 本場（ロン基準）
    mult = 6 if ctx.is_dealer else 4                   # 親は加点効率が高い
    need = math.ceil((gap + ORAS_ESCAPE_BUFFER) / mult / 100.0) * 100.0
    return max(1000.0, float(need))


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
        is_last = _is_last(ctx.my_score, ctx.other_scores)
        if is_last:
            gain *= EV_LAST_ESCAPE_BONUS
        # --- ラス目かつ大差＆終盤なら門前リーチを優遇 ---
        if is_last:
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
        # --- ラス目かつ大差＆終盤なら副露EVを減衰（安手のスピード鳴き抑制） ---
        if is_last:
            gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
            if gap >= LAST_GAP_LARGE and ctx.turns_left <= 6:
                gain *= LAST_GAP_CALL_PENALTY

        if HONITSU_CALL_ENABLE:
            ratio, main_suit = _honitsu_score(ctx)
            if ratio >= HONITSU_MIN_SUIT_RATIO:
                # 期待打点の増加をbp側に反映（字牌を含むホンイツも想定して+α）
                suit_bonus = 1.0 + (ratio - HONITSU_MIN_SUIT_RATIO) * 0.6  # 0〜+0.24程度
                dora_bonus = 1.0 + ctx.dora_count * HONITSU_DORA_BONUS
                value_bonus = 1.0 + (HONITSU_VALUE_HONOR_BONUS if ctx.has_value_honor else 0.0)
                bp *= HONITSU_CALL_BOOST * suit_bonus * dora_bonus * value_bonus
                gain = win * bp

                if HONITSU_PROGRESS_ENABLE:
                    progress = (ctx.call_delta_shanten >= HONITSU_PROGRESS_MIN_DELTA) and \
                               ((ctx.call_meld_suit is None) or (main_suit is None) or (ctx.call_meld_suit == main_suit))
                    if progress:
                        bp *= HONITSU_PROGRESS_CALL_BOOST
                        gain = win * bp
                # それでも見込み打点が低すぎるならブーストを無効化（空鳴き保護）
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
        is_last = _is_last(ctx.my_score, ctx.other_scores)
        if ctx.is_oras and is_last:
            need_bp = _required_bp_to_escape(ctx)
            if ctx.basepoint < need_bp:
                reach_ev *= ORAS_LAST_REACH_UNDER_NEED_BOOST
                dama_ev  *= ORAS_LAST_DAMA_UNDER_NEED_PENALTY
                call_ev  *= ORAS_LAST_CALL_UNDER_NEED_PENALTY
            # 鳴き許可は “必要打点×比率” 未満なら原則禁止
            if ctx.basepoint < need_bp * ORAS_LAST_CALL_MIN_RATIO:
                allow_call_by_need = False
            else:
                allow_call_by_need = True
        else:
            allow_call_by_need = True

         # ====== 卓状況の脅威評価 ======
        threat = _table_threat(ctx)  # 既存ヘルパ
        south  = bool(ctx.is_oras) or (ctx.bakaze == "S")
        last   = _is_last(ctx.my_score, ctx.other_scores)
        top_lead = _lead_margin(ctx.my_score, ctx.other_scores) >= 0 and \
                ctx.my_score == max([ctx.my_score] + ctx.other_scores)

        # 親リーチの検出（安全に推定：見えている宣言の誰かが親でreach）
        vs_dealer_reach = False
        try:
            vs_dealer_reach = (ctx.dealer_reached is True)
        except Exception:
            pass

        # ====== リスク回避：EVのソフト調整 ======
        risk = EV_RISK_AVERSION
        if south:
            risk += EV_RISK_AVERSION_SOUTH_BONUS
        if vs_dealer_reach:
            risk += EV_RISK_AVERSION_VS_DEALER_REACH
        if EV_MODE == "placement":
            risk += 0.25 * EV_PLACEMENT_WEIGHT  # ラス回避寄せ

        # チートイ（安全推定：対子4以上や対子多めの簡易判定がctxに無くても無害）
        is_chiitoi_like = False
        for name in ("is_chiitoi", "shape_chiitoi", "chiitoi_like"):
            if getattr(ctx, name, False):
                is_chiitoi_like = True
        # reach/damaの相対EVへソフトペナルティを与える
        adj_reach_ev = reach_ev
        if threat:
            adj_reach_ev -= abs(reach_ev) * risk
        if is_chiitoi_like:
            adj_reach_ev -= abs(reach_ev) * EV_CHIITOI_REACH_PENALTY

        adj_call_ev = call_ev
        encourage = EV_CALL_ENCOURAGE + (EV_CALL_ENCOURAGE_LAST if last else 0.0)
        adj_call_ev += abs(call_ev) * encourage

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
        # チートイ等・弱待ちで必要打点未満はリーチ寄りに（ダマ抑制）
        if ctx.is_oras and is_last and ctx.chiitoi_like and ctx.basepoint < max(need_bp, CHIITOI_FORCE_REACH_NEED_BP):
            allow_reach = True  # リーチ許容を優先
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
        # --- ラス目・大差・終盤の特別ルール ---
        if _is_last(ctx.my_score, ctx.other_scores):
            gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
            if gap >= LAST_GAP_LARGE and ctx.turns_left <= 6:
                # 役牌ポンの原則禁止（一定打点未満）
                if ctx.last_discard_is_yakuhai and ctx.basepoint < LAST_GAP_YAKUHAI_FORBID_UNDER:
                    allow_pon = False
                # 鳴きは最低打点を満たす場合のみ許容（リーチ逆転ルート優先）
                if ctx.basepoint < LAST_GAP_CALL_MIN_BASEPOINT:
                    allow_pon = False
            if ctx.is_oras and need_bp > 0 and not allow_call_by_need:
                # 染め手かつ進捗がある鳴きなら、鳴き門を少しだけ緩める
                ratio, main_suit = _honitsu_score(ctx)
                progress = HONITSU_PROGRESS_ENABLE and (ctx.call_delta_shanten >= HONITSU_PROGRESS_MIN_DELTA) \
                           and ((ctx.call_meld_suit is None) or (main_suit is None) or (ctx.call_meld_suit == main_suit))
                # need_bp×0.80 以上の将来打点が見込めるなら許可（ヒントが無いときは従来どおり禁止）
                if progress and ratio >= HONITSU_SOFT_SUIT_RATIO and \
                   ctx.call_future_bp_hint >= max(HONITSU_MIN_CALL_EXPECTED_BP, need_bp * HONITSU_PROGRESS_NEED_RELIEF):
                    allow_pon = True

        if HONITSU_CALL_ENABLE and allow_pon:
            ratio, main_suit = _honitsu_score(ctx)
            if ratio >= HONITSU_SOFT_SUIT_RATIO:
                # ある程度まとまっていれば鳴き許容を一段緩める（ただし安手条件は上のneed_bp Gateが管理）
                pass  # 許可済み。ここで更に緩める条件があれば追加

        allow_chi = allow_pon

        # ===== Kan可否 =====
        allow_kan = True
        if (EV_FORBID_KAN_UNDER_THREAT and _table_threat(ctx)) or (EV_STRICT_FORBID_KAN and threat and (top_lead or south)):
            allow_kan = False
        if EV_FORBID_KAN_TOP_LEAD and _lead_margin(ctx.my_score, ctx.other_scores) >= EV_REACH_TOP_LEAD_MARGIN:
            allow_kan = False

        try:
            gap = _gap_to_next_place(ctx.my_score, ctx.other_scores)
            ratio, main_suit = _honitsu_score(ctx)
            print(f"[POLICY][GAP] last={_is_last(ctx.my_score, ctx.other_scores)} gap={gap} need_bp={need_bp:.0f} "
                f"turns_left={ctx.turns_left} base={ctx.basepoint:.0f} "
                f"EV reach/dama/call={reach_ev:.1f}/{dama_ev:.1f}/{call_ev:.1f} "
                f"honitsu_ratio={ratio:.2f} main={main_suit} "
                f"progressΔ={ctx.call_delta_shanten} meld_suit={ctx.call_meld_suit} "
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
            reach_ev=float(reach_ev),
            dama_ev=float(dama_ev),
            call_ev=float(call_ev),
        )
