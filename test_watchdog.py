# -*- coding: utf-8 -*-
"""
test_watchdog.py -- 6 Oct 2026 (HANDOVER 260). run_vwap.py ka imtihan ASAL processes ke saath
(chhota nakli bot: last_alive.json likhta hai; `mode` file se gire / atke). Asal bot / broker NAHI.

    python test_watchdog.py
"""
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime

import run_vwap as W

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

R = []


def ok(name, cond, extra=""):
    R.append((name, bool(cond)))
    print(("PAAS " if cond else "FAIL ") + name + (("   [%s]" % extra) if (extra and not cond) else ""), flush=True)


DUMMY = r'''
import json, os, sys, time
from datetime import datetime
here = os.path.dirname(os.path.abspath(__file__))
t0 = time.time()
while True:
    mode = open(os.path.join(here, "mode")).read().strip() if os.path.exists(os.path.join(here, "mode")) else ""
    if mode == "crash" and time.time() - t0 > 0.5:
        sys.exit(3)
    if mode != "hang":
        json.dump({"ts": datetime.now().isoformat()}, open(os.path.join(here, "last_alive.json"), "w"))
    time.sleep(0.3)
'''


def md5_8(b):
    return hashlib.md5(b).hexdigest()[:8]


def make_root(token="x"):
    root = tempfile.mkdtemp(prefix="wd_")
    man = {}
    for sym in ("DE40", "US30"):
        d = os.path.join(root, sym)
        os.makedirs(d)
        io.open(os.path.join(d, "bot.py"), "w", encoding="utf-8", newline="").write(DUMMY)
        for f in W.ENGINE:
            io.open(os.path.join(d, f), "w", encoding="utf-8", newline="").write("# %s\n" % f)
            man[f] = md5_8(("# %s\n" % f).encode())
        json.dump({"symbol": sym, "magic_number": 19990102, "telegram_token": token, "telegram_chat_id": "-5580906000",
                   "secret_key": "s", "mt5_login": 0, "strategy_enabled": True},
                  open(os.path.join(d, "config.json"), "w"))
    json.dump(man, open(os.path.join(root, "MANIFEST.json"), "w"))
    return root


CONF = {"stale_alive_sec": 2.5, "crash_window_sec": 60, "crash_max": 3, "crash_pause_sec": 5, "month_check_sec": 9999}
BOT = md5_8(DUMMY.encode())


def wd(root, tgs, logs):
    return W.Watchdog(root=root, conf=dict(CONF), log=logs.append, telegram=lambda s, t, c: tgs.append((s, t, c)),
                      bot_md5=BOT)


def wait(cond, sec=8):
    t1 = time.time() + sec
    while time.time() < t1:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


print("=" * 70)
print("test_watchdog -- %s" % W.VERSION)
print("=" * 70, flush=True)

# --- 1. jaanch: kharab files / config par bot NAHI chalta ---
root = make_root(token="")
tgs, logs = [], []
w = wd(root, tgs, logs)
bad = w.check_files("DE40")
ok("token khaali -> RADD", any("telegram_token" in b for b in bad))
cfg = json.load(open(os.path.join(root, "US30", "config.json")))
cfg.update(telegram_token="x", magic_number=19990101, mt5_login=123, ctrader={"url": "ws://127.0.0.1:1"})
json.dump(cfg, open(os.path.join(root, "US30", "config.json"), "w"))
b2 = w.check_files("US30")
ok("live magic 19990101, mt5_login, test url -> teeno RADD", any("19990102" in b for b in b2)
   and any("mt5_login" in b for b in b2) and any("url" in b for b in b2), str(b2))
open(os.path.join(root, "DE40", "bot.py"), "a").write("# badla\n")
ok("bot.py badli (md5) -> RADD", any("bot.py ka md5" in b for b in w.check_files("DE40")))
w.tick()
ok("kharab -> process NAHI chala + Telegram", not w.alive("DE40") and not w.alive("US30")
   and any("NAHI chalaya" in t for _, t, _ in tgs))
shutil.rmtree(root, ignore_errors=True)

# --- 2. dono chalte, aik gire to SIRF woh dobara ---
root = make_root()
tgs, logs = [], []
w = wd(root, tgs, logs)
w.tick()
ok("dono chal pare (alag PID)", wait(lambda: w.alive("DE40") and w.alive("US30"))
   and w.kids["DE40"]["pid"] != w.kids["US30"]["pid"])
p_de, p_us = w.kids["DE40"]["pid"], w.kids["US30"]["pid"]
W.kill(p_us)
wait(lambda: not w.alive("US30"))
w.tick()
ok("US30 mara -> sirf US30 dobara (naya PID), DE40 wahi", wait(lambda: w.alive("US30")) and w.kids["US30"]["pid"] != p_us
   and w.kids["DE40"]["pid"] == p_de)
ok("gira -> Telegram US30 ke bot se", any(s == "US30" and "band ho gaya" in t for s, t, _ in tgs))

# --- 3. watchdog khud restart -> chalte bots APNAYE, doosri copy NAHI ---
tgs2, logs2 = [], []
w2 = wd(root, tgs2, logs2)
w2.tick()
ok("naya watchdog: dono APNAYE, PID wahi", w2.kids["DE40"]["pid"] == p_de and w2.kids["US30"]["pid"] == w.kids["US30"]["pid"]
   and sum("apna liya" in l for l in logs2) == 2)
lk1 = W.FileLock(os.path.join(root, "run_vwap.lock"))
lk2 = W.FileLock(os.path.join(root, "run_vwap.lock"))
ok("aik waqt mein aik watchdog (lock)", lk1.acquire() and not lk2.acquire())

# --- 4. ATKA hua (alive purana) -> band kar ke dobara ---
open(os.path.join(root, "DE40", "mode"), "w").write("hang")
time.sleep(3.2)
old = w.kids["DE40"]["pid"]
w.tick()
os.remove(os.path.join(root, "DE40", "mode"))
ok("atka DE40 -> band + dobara (naya PID) + Telegram", wait(lambda: w.alive("DE40")) and w.kids["DE40"]["pid"] != old
   and any("ATKA" in t for _, t, _ in tgs))

# --- 5. crash ka chakkar -> 3 baar ke baad RUKO ---
open(os.path.join(root, "US30", "mode"), "w").write("crash")
for _ in range(4):
    wait(lambda: not w.alive("US30"), 4)
    w.tick()
ok("crash x3 -> ruk gaya + Telegram 'baar gira'", w.kids["US30"].get("paused_until", 0) > time.time()
   and any("baar gira" in t for _, t, _ in tgs))
os.remove(os.path.join(root, "US30", "mode"))
w.kids["US30"]["paused_until"] = 0
w.tick()
ok("rukne ke baad phir chala", wait(lambda: w.alive("US30")))

# --- 6. mahine ki hadd ---
month = datetime.now().strftime("%Y-%m")
with io.open(os.path.join(root, "DE40", "trades.csv"), "w", encoding="utf-8") as fh:
    fh.write("time,closed_at,ticket,realized_r\n")
    fh.write("%s-01T04:30:00,%s-01T05:00:00,1,-8.0\n" % (month, month))
    fh.write("%s-02T04:30:00,%s-02T05:00:00,2,-5.0\n" % (month, month))
    fh.write("2020-01-01T04:30:00,,3,\n")
w.month_check("DE40")
w.month_check("US30")
c_de = json.load(open(os.path.join(root, "DE40", "config.json")))
c_us = json.load(open(os.path.join(root, "US30", "config.json")))
ok("DE40 mahina -13R < -12.5 -> strategy_enabled false + Telegram; US30 chalu",
   c_de["strategy_enabled"] is False and c_us["strategy_enabled"] is True and any("MAHINA HADD" in t for _, t, _ in tgs))
c_de["strategy_enabled"] = True
json.dump(c_de, open(os.path.join(root, "DE40", "config.json"), "w"))
w.month_check("DE40")
ok("Majid ne dobara true kiya -> usi mahine watchdog band NAHI karta",
   json.load(open(os.path.join(root, "DE40", "config.json")))["strategy_enabled"] is True)

# --- 7. --stop ---
w.stop_all()
ok("stop_all: dono band", wait(lambda: not w.alive("DE40") and not w.alive("US30")))
shutil.rmtree(root, ignore_errors=True)

n = sum(1 for _, c in R if c)
print("\nKUL: %d / %d PAAS" % (n, len(R)))
sys.exit(0 if n == len(R) else 1)
