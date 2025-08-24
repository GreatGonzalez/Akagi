# #!/usr/bin/env bash
# # ===== strict =====
# set -Eeuo pipefail

# APPDIR="/Users/maruno/source/Akagi"
# VENV="$APPDIR/.venv"
# LOGDIR="$APPDIR/logs"
# PWLOG="$LOGDIR/playwright_boot.log"
# ENVLOG="$LOGDIR/env_at_launchd.log"

# mkdir -p "$LOGDIR"

# {
#   echo "===== $(date '+%F %T') start_akagi.sh ====="
#   echo "UID=$(id -u)  USER=$USER  SHELL=$SHELL  HOME=$HOME"
#   echo "PWD=$(pwd)"
#   echo "PATH=$PATH"
#   env | sort | sed 's/^\(LINE_CHANNEL_ACCESS_TOKEN\|OPENAI_API_KEY\)=.*/\1=***MASKED***/' > "$ENVLOG"
#   echo "(env snapshot) -> $ENVLOG"

#   # venv
#   if [[ ! -x "$VENV/bin/python" ]]; then
#     echo "!! venv python not found: $VENV/bin/python"
#   fi
#   echo "+ source $VENV/bin/activate"
#   # bash -c でも読めるように絶対パスで source
#   # shellcheck disable=SC1090
#   source "$VENV/bin/activate"

#   echo "+ python --version"
#   python --version

#   echo "+ which python"
#   which python

#   # playwright の依存が入っているか最低限チェック
#   echo "+ python -c 'import playwright;print(\"playwright OK\")'"
#   python - <<'PY' || { echo "!! playwright import failed"; exit 1; }
# import sys
# try:
#     import playwright # type: ignore
#     print("playwright OK")
# except Exception as e:
#     print("playwright import error:", e, file=sys.stderr); raise
# PY

#   # まず“最小”で headful を起動できるかを検証（about:blank）
#   echo "+ sanity: headful chromium open/close"
#   python - <<'PY' 2>&1 | tee -a "$PWLOG" || { echo "!! chromium sanity failed"; exit 1; }
# from pathlib import Path
# from playwright.sync_api import sync_playwright
# print("sanity: launching chromium headful...")
# with sync_playwright() as p:
#     ctx = p.chromium.launch_persistent_context(
#         user_data_dir=Path("/Users/maruno/source/Akagi/playwright_data"),
#         headless=False,
#         # sandboxはPlaywrightが適切に設定。独自で --no-sandbox を付けない
#         ignore_default_args=['--enable-automation'],
#         args=["--noerrdialogs"],
#         viewport={"width": 1600, "height": 960},
#     )
#     page = ctx.pages[0] if ctx.pages else ctx.new_page()
#     page.goto("about:blank")
#     page.wait_for_timeout(500)
#     print("sanity: ok, closing context.")
#     ctx.close()
# print("sanity: done.")
# PY

#   echo "+ launching run_akagi.py (real app)"
#   # 本番起動
#   exec python "$APPDIR/run_akagi.py"
# } >> "$LOGDIR/launchd.out" 2>> "$LOGDIR/launchd.err"
