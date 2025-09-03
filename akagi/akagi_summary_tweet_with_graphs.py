#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
summary_tweet_with_graphs.py
- Akagiログを読み、順位分布(棒)＋累積ポイント(折れ線)画像を作って
  朝/昼/晩ランダム時刻で自動ツイート

環境変数（任意）:
  AKAGI_LOG_PATH           (既定: ./akagi.log)
  AKAGI_TWEET_HOURS        (ポイント推移の対象時間: 既定 48)
  AKAGI_TWEET_HASHTAGS     (既定: "#雀魂 #Akagi")
  AKAGI_TWEET_DRYRUN       ("1"なら実際には投稿せず保存のみ)
"""

import os, re, json, time, random, threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import matplotlib.pyplot as plt
import requests

# 同パッケージ内の投稿ユーティリティ（あなたの x_post.py）
from .x_post import ensure_access_token, post_tweet, post_tweet_with_img

LOG_PATH = os.getenv("AKAGI_LOG_PATH", "./akagi.log")
HOURS = int(os.getenv("AKAGI_TWEET_HOURS", "48"))
HASHTAGS = os.getenv("AKAGI_TWEET_HASHTAGS", "#雀魂 #Akagi")
DRYRUN = os.getenv("AKAGI_TWEET_DRYRUN", "0") == "1"

# --------- ログ解析（[API] data= {...} を拾う） ----------
_RE_API_JSON = re.compile(r"\[API\]\s*data\s*=\s*(\{.*\})")

def _safe_json(s: str):
    try: return json.loads(s)
    except: return None

def _parse_ts(line: str) -> Optional[datetime]:
    # 先頭が "YYYY-MM-DD HH:MM:SS,ms" の想定
    try:
        return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f")
    except: return None

def _extract(line: str):
    m = _RE_API_JSON.search(line)
    if not m: return None
    obj = _safe_json(m.group(1))
    if not isinstance(obj, dict): return None
    if "rank" in obj:
        # grading_after: その対局後の累積ポイント
        total = obj.get("grading_after")
        try:
            total = int(total) if total is not None else None
        except: total = None
        # timestamp はログ行の先頭（なければ今）
        ts = _parse_ts(line) or datetime.now()
        return {
            "ts": ts,
            "rank": obj.get("rank"),
            "delta": obj.get("grading_delta"),
            "total": total,
        }
    return None

def _read_recent(hours=48) -> List[Dict[str,Any]]:
    now = datetime.now()
    start = now - timedelta(hours=hours)
    recs=[]
    if not os.path.exists(LOG_PATH): return recs
    with open(LOG_PATH, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            ts = _parse_ts(line)
            if not ts or ts < start: continue
            r = _extract(line)
            if r: recs.append(r)
    return recs

# --------- 集計 & 画像生成 ----------
def _summarize(records: List[Dict[str,Any]]) -> Dict[str,Any]:
    dist={1:0,2:0,3:0,4:0}
    points=[]
    for r in records:
        try:
            rk = int(r.get("rank"))
            if rk in dist: dist[rk]+=1
        except: pass
        if isinstance(r.get("total"), int):
            points.append((r["ts"], r["total"]))
    points = sorted(points, key=lambda x:x[0])
    n = sum(dist.values())
    avg = round(sum(r*k for r,k in dist.items())/n, 2) if n else None
    return {"count":n,"dist":dist,"avg":avg,"points":points}

def _make_graph(dist: Dict[int,int], points: List[tuple], out="summary.png") -> str:
    # 1行2列: 左=棒グラフ 右=折れ線グラフ
    fig, axes = plt.subplots(1,2,figsize=(8,3))

    # 左：順位分布
    ranks=[1,2,3,4]; vals=[dist.get(r,0) for r in ranks]
    axes[0].bar(ranks, vals)
    axes[0].set_xticks(ranks)
    axes[0].set_xlabel("順位"); axes[0].set_ylabel("回数"); axes[0].set_title("順位分布")

    # 右：累積ポイント推移
    if points:
        xs=[p[0] for p in points]; ys=[p[1] for p in points]
        axes[1].plot(xs, ys, marker="o", linestyle="-")
        axes[1].set_title("累積ポイント推移")
        axes[1].tick_params(axis='x', rotation=45)
    else:
        axes[1].text(0.5,0.5,"データなし",ha="center",va="center")

    fig.tight_layout()
    plt.savefig(out)
    plt.close(fig)
    return out

# --------- 投稿テキスト ----------
def _format_text(period_label: str, summ: Dict[str,Any]) -> str:
    if summ["count"] == 0:
        return f"【{period_label}の戦績】対局なし {HASHTAGS}"
    d=summ["dist"]; avg=summ["avg"]
    msg=f"【{period_label}の戦績】{summ['count']}戦 1位{d[1]} 2位{d[2]} 3位{d[3]} 4位{d[4]}"
    if avg is not None:
        msg += f" 平均{avg}"
    msg += f" {HASHTAGS}"
    return msg[:280]

def _period_label(run_at: datetime) -> str:
    h=run_at.hour
    if h<11: return "朝"
    if h<17: return "昼"
    return "夜"

# --------- 実行本体（1回分） ----------
def run_summary_once(run_at: datetime) -> None:
    recs = _read_recent(hours=HOURS)
    summ = _summarize(recs)
    text = _format_text(_period_label(run_at), summ)
    img  = _make_graph(summ["dist"], summ["points"])
    if DRYRUN:
        print("[DRYRUN] text:", text)
        print("[DRYRUN] image saved:", img)
        return
    # 画像つき投稿
    status, data = post_tweet_with_img(text, [img])
    print("[Tweet]", status, data)

# --------- スケジューラ（朝昼晩ランダム） ----------
def _pick_times():
    now=datetime.now()
    slots=[(6,10),(12,15),(19,23)]
    times=[]
    for s,e in slots:
        h=random.randint(s,e); m=random.randint(0,59)
        t=now.replace(hour=h,minute=m,second=0,microsecond=0)
        if t<now: t+=timedelta(days=1)
        times.append(t)
    return sorted(times)

def _loop():
    while True:
        plan=_pick_times()
        for t in plan:
            wait=(t-datetime.now()).total_seconds()
            if wait>0: time.sleep(wait)
            try:
                run_summary_once(t)
            except Exception as e:
                print("[SummaryTweet Error]", e)
        # 翌日0時までスリープ
        tomorrow=(datetime.now()+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        rest=(tomorrow-datetime.now()).total_seconds()
        if rest>0: time.sleep(rest)

def start_daily_summary_scheduler() -> None:
    threading.Thread(target=_loop, daemon=True).start()

# CLI用：今すぐ1回テスト
if __name__=="__main__":
    # ドライランで1回だけ画像生成＆投稿テキスト表示（投稿しない）
    os.environ.setdefault("AKAGI_TWEET_DRYRUN","1")
    run_summary_once(datetime.now())
