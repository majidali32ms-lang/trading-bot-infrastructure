# -*- coding: utf-8 -*-
"""
build_vps.py -- 6 Oct 2026 (HANDOVER 260). VPS ke liye tayyar folder banata hai: vps_vwap\\
(us ka saara andar ka maal VPS par C:\\trading-bot-vwap\\ mein jata hai -- WAPSI.md dekhein).

  vps_vwap\\run_vwap.py, run_vwap_NAMOONA.json, MANIFEST.json, ctrader_keys_NAMOONA.json, WAPSI.md
  vps_vwap\\DE40\\  bot.py (bd901c0f HOOBAHOO) + MetaTrader5.py (= mt5_ctrader.py) + strategy.py
                   (= vwap_strategy_adapter.py) + ctrader_link.py + ctrader_trade.py + strategy_vwap.py
                   + config_NAMOONA.json (group -5580906000, port 8081)
  vps_vwap\\US30\\  wahi (port 8082)
Koi raaz (token / password) is folder mein NAHI -- Majid VPS par config.json mein khud daale.
"""
import hashlib
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "vps_vwap")
BOT_MD5 = "bd901c0f"
GROUP = "-5580906000"
PY_VPS = r"C:\Program Files\Python311\python.exe"
SRC = {"MetaTrader5.py": "mt5_ctrader.py", "strategy.py": "vwap_strategy_adapter.py",
       "ctrader_link.py": "ctrader_link.py", "ctrader_trade.py": "ctrader_trade.py",
       "strategy_vwap.py": "strategy_vwap.py"}
PINNED = {"ctrader_link.py": "352b526a", "strategy_vwap.py": "25a31752"}
OPTIONAL = {"news_shadow.py": "news_shadow.py", "news_dates.txt": "news_dates.txt"}      # VPS ke C:\trading-bot se -- ho to shamil
ROOT_FILES = ("rutin_vwap.py", "keys_bharo.py", "ctrader_check.py", "ct_backtest.py")
EXTRA_FILES = ("vwap_task.xml", "filter_jaanch.py", "sab_band.bat", "sab_chalu.bat", "fix_start_bat.py")
SYMS = {"DE40": dict(port=8081, aliases=["DE40", "GER40", "DE30", "GER30"], stop=-12.5),
        "US30": dict(port=8082, aliases=["US30"], stop=-14.4)}


def md5_8(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()[:8]


def config(sym):
    s = SYMS[sym]
    return {
        "_NOTE": "NAMOONA -> naam config.json kar dein. Sirf 2 khaali jagah bharein: telegram_token "
                 "(VWAP %s bot ka, BotFather) aur secret_key (webhook ka raaz, koi bhi lamba lafz). "
                 "Baqi qeematein live bot.py / VWAP backtest jaisi -- mat badlein." % sym,
        "secret_key": "", "symbol": sym, "magic_number": 19990102, "risk_percent": 1.0,
        "max_spread_points": 250, "max_daily_drawdown_percent": 5.0, "account_max_drawdown_percent": 10.0,
        "max_trades_per_day": 6, "max_consecutive_losses": 3, "breakeven_r": 0.5, "trailing_stop_r": 0,
        "retrace_guard_arm": 0, "retrace_guard_lock": 1.5, "retrace_guard_frac": 1.0,
        "retrace_guard_max_mae": -0.3, "telegram_token": "", "telegram_chat_id": GROUP,
        "heartbeat_time_ny": "20:00", "news_lockout_minutes_before": 30, "news_lockout_minutes_after": 30,
        "news_lockout_schedule": [],
        "sessions": [{"name": "Session A", "start": "00:00", "end": "00:00"},
                                   {"name": "Session B", "start": "00:00", "end": "00:00"}],
        "mt5_login": 0, "mt5_password": "", "mt5_server": "",
        "strategy_enabled": True, "strategy_scan_interval": 300, "strategy_test_mode": False,
        "skip_friday_ny_pm": True, "friday_flatten_enabled": True, "friday_flatten_time_ny": "16:45",
        "min_sl_units": 5.0, "retrace_guard_arm2": 0.3, "retrace_guard_lock2": 0.2,
        "webhook_host": "127.0.0.1", "webhook_port": s["port"],
        "ctrader": {"label": "VWAP-" + sym, "broker_names": s["aliases"], "point": 0.01,
                    "keys_file": "..\\ctrader_keys.json"},
    }


V436 = ("patch_report/bot.py", "7a55255a")       # bot.py v4.36 (report patch, HANDOVER 264)
V437 = ("patch_offset/bot.py", "267c6530")       # bot.py v4.37 (v4.36 + offset NY+7, HANDOVER 265)
PATCH_FILES = {"v436": ("apply_report_patch.py", "PATCH_V436.md", "dst_jaanch.py"),
               "v437": ("apply_report_patch.py", "PATCH_V436.md", "dst_jaanch.py", "apply_offset_patch.py",
                        "PATCH_V437.md")}


def build(out=OUT, v436=False, v437=False):
    bad = []
    if v437:
        bot_src, bot_md5 = os.path.join(HERE, V437[0]), V437[1]
    elif v436:
        bot_src, bot_md5 = os.path.join(HERE, V436[0]), V436[1]
    else:
        bot_src, bot_md5 = os.path.join(HERE, "bot.py.bak_v435"), BOT_MD5   # v4.35 (11 Oct: bot.py = live v4.37)
    if md5_8(bot_src) != bot_md5:
        bad.append("bot.py md5 %s NAHI (%s)" % (bot_md5, bot_src))
    for f, want in PINNED.items():
        if md5_8(os.path.join(HERE, f)) != want:
            bad.append("%s md5 %s NAHI" % (f, want))
    if bad:
        raise SystemExit("RUKA: " + "; ".join(bad))
    final, out = out, out + ".naya"
    if os.path.exists(out):
        shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    manifest = {"bot.py": bot_md5}
    for dst, src in SRC.items():
        manifest[dst] = md5_8(os.path.join(HERE, src))
    for dst, src in OPTIONAL.items():
        if os.path.exists(os.path.join(HERE, src)):
            manifest[dst] = md5_8(os.path.join(HERE, src))
    for sym in SYMS:
        d = os.path.join(out, sym)
        os.makedirs(d)
        shutil.copy(bot_src, os.path.join(d, "bot.py"))
        for dst, src in SRC.items():
            shutil.copy(os.path.join(HERE, src), os.path.join(d, dst))
        for dst, src in OPTIONAL.items():
            if os.path.exists(os.path.join(HERE, src)):
                shutil.copy(os.path.join(HERE, src), os.path.join(d, dst))
        with io.open(os.path.join(d, "config_NAMOONA.json"), "w", encoding="utf-8") as fh:
            json.dump(config(sym), fh, indent=2, ensure_ascii=False)
    shutil.copy(os.path.join(HERE, "run_vwap.py"), os.path.join(out, "run_vwap.py"))
    for f in ROOT_FILES:
        shutil.copy(os.path.join(HERE, f), os.path.join(out, f))
    for f in PATCH_FILES["v437" if v437 else "v436"] if (v436 or v437) else ():   # weekend patch (264 / 265)
        shutil.copy(os.path.join(HERE, f), os.path.join(out, f))
    for f in EXTRA_FILES:                      # record / Task ki files -- MANIFEST mein NAHI (262-D)
        if os.path.exists(os.path.join(HERE, f)):
            shutil.copy(os.path.join(HERE, f), os.path.join(out, f))
    shutil.copy(os.path.join(HERE, "ctrader_keys_NAMOONA.json"), os.path.join(out, "ctrader_keys_NAMOONA.json"))
    if os.path.exists(os.path.join(HERE, "WAPSI.md")):
        shutil.copy(os.path.join(HERE, "WAPSI.md"), os.path.join(out, "WAPSI.md"))
    with io.open(os.path.join(out, "run_vwap_NAMOONA.json"), "w", encoding="utf-8") as fh:
        json.dump({"symbols": ["DE40", "US30"], "python": PY_VPS,
                   "stop_month_r": {k: v["stop"] for k, v in SYMS.items()}}, fh, indent=2)
    manifest["run_vwap.py"] = md5_8(os.path.join(out, "run_vwap.py"))
    for f in ROOT_FILES:
        manifest[f] = md5_8(os.path.join(out, f))
    with io.open(os.path.join(out, "MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    if os.path.exists(final):                  # OneDrive taala laga sakta hai -- purana pehle hatao
        old = final + ".purana"
        shutil.rmtree(old, ignore_errors=True)
        for _ in range(20):
            try:
                os.rename(final, old)
                break
            except OSError:
                import time
                time.sleep(0.5)
        else:
            raise SystemExit("RUKA: %s hata nahi saka (OneDrive / Explorer khula?) -- naya package %s mein hai" % (final, out))
        shutil.rmtree(old, ignore_errors=True)
    os.rename(out, final)
    return manifest


if __name__ == "__main__":
    v6, v7 = "--v436" in sys.argv, "--v437" in sys.argv
    o = OUT + ("_v437" if v7 else "_v436" if v6 else "")
    m = build(out=o, v436=v6, v437=v7)
    print("%s\\ bana. md5:" % os.path.basename(o))
    for k, v in m.items():
        print("   %-18s %s" % (k, v))
