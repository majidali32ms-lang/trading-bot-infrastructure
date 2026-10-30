#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rutin.py  --  251: HAR DOOSRE DIN ka poora checkup AIK command mein.
SIRF PARHTA HAI (backtest copy ke siwa kuch nahi likhta).

  1 RAM                        2 checkup.py        3 health_check.py
  4 audit_ready.py             5 Windows tasks (archive / settings / bot)
  6 scan: aaj + kal ke [SESSION] aur [SIGNAL] Entry (bar + 5s?)
  7 jurwa v3: export_m5 --months 3 + jurwa.py (live vs backtest)
  8 KHULASA -- kahan dekhna hai

    cd C:\\trading-bot
    python rutin.py                 <- sab
    python rutin.py --no-jurwa      <- jurwa ke baghair (jaldi)
NY PM (15:00 NY = 23:00 Dubai) ke BAAD chalana behtar -- din poora ho.
"""
import io, os, re, sys, subprocess, hashlib
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VERSION = "rutin v1.1 -- 30 Sep -- har doosre din ka checkup (RAM: Chrome + 500 MB)"
try:
    _self = hashlib.md5(open(__file__, "rb").read()).hexdigest()[:8]
except Exception:
    _self = "??"
NOTE = []


def H(t):
    print("\n" + "#" * 78)
    print("# " + t)
    print("#" * 78)


def run(cmd, timeout=1800):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return r.returncode, r.stdout.decode("utf-8", "replace")
    except Exception as e:
        return -1, "   (chal nahi saka: %s)" % e


def py(script, *args, timeout=1800):
    if not os.path.exists(script):
        NOTE.append("%s nahi mili" % script)
        return "   %s nahi mili" % script
    env_cmd = [sys.executable, script] + list(args)
    rc, out = run(env_cmd, timeout)
    if rc != 0:
        NOTE.append("%s rc=%s" % (script, rc))
    return out


print("=" * 78)
print(VERSION)
print("script ka md5:", _self)
now = datetime.now()
print("VPS waqt (NY):", now.strftime("%Y-%m-%d %H:%M"))
if now.hour < 15 and now.weekday() < 5:
    print("NOTE: NY PM (14:00-15:00) abhi baqi -- aaj ka din adhoora.")
print("=" * 78)

H("1. RAM")
rc, out = run(["systeminfo"], 120)
for l in out.splitlines():
    if "Physical Memory" in l or "Virtual Memory: Available" in l:
        print("   " + l.strip())
m = re.search(r"Available Physical Memory:\s*([\d,]+)\s*MB", out)
# 252.7: Chrome band par khali ~900 MB. Chrome akela ~550-770 MB khata hai.
rc2, tl = run(["tasklist", "/fo", "csv", "/nh", "/fi", "IMAGENAME eq chrome.exe"], 60)
chrome_mb = 0
for _r in tl.splitlines():
    _p = [x.strip().strip('"') for x in _r.split('","')]
    if len(_p) >= 5 and _p[0].lower() == "chrome.exe":
        chrome_mb += int(re.sub(r"[^0-9]", "", _p[4]) or 0) // 1024
print("   Chrome: %s" % ("%d MB (khula)" % chrome_mb if chrome_mb else "band"))
if m:
    mb = int(m.group(1).replace(",", ""))
    if mb < 150:
        NOTE.append("RAM khali %d MB < 150 -- Chrome / faltu band karo" % mb)
    elif chrome_mb:
        NOTE.append("Chrome khula (%d MB) -- kaam ke baad band karein" % chrome_mb)
    elif mb < 500:
        NOTE.append("RAM khali %d MB (Chrome band) < 500 -- ram_jaanch.py chala kar bhejein" % mb)

H("2. CHECKUP")
out = py("checkup.py")
print(out)
if "[MASLA" in out or "MASLA" in out.split("KHULASA")[-1]:
    NOTE.append("checkup mein MASLA")

H("3. HEALTH")
out = py("health_check.py")
print(out)
if re.search(r"\[FAIL", out):
    NOTE.append("health mein FAIL")

H("4. AUDIT")
out = py("audit_ready.py")
print(out)
if "[OK     ] koi tabdeeli nahi" not in out:
    NOTE.append("audit: settings badli? dekho")

H("5. WINDOWS TASKS")
for tn in ("\\bot log archive", "\\bot settings log", "\\TradingBot"):
    rc, out = run(["schtasks", "/query", "/tn", tn, "/fo", "LIST", "/v"], 60)
    keep = [l.strip() for l in out.splitlines()
            if l.split(":")[0].strip() in ("TaskName", "Status", "Last Run Time", "Last Result")]
    print("   " + ("\n   ".join(keep) if keep else out.strip()[:200]))
    for l in keep:
        if l.startswith("Last Result") and tn != "\\TradingBot" and not l.rstrip().endswith(" 0"):
            NOTE.append("%s Last Result 0 nahi" % tn)
        if tn == "\\TradingBot" and l.startswith("Status") and "Running" not in l:
            NOTE.append("BOT CHAL NAHI RAHA")
    print("")

H("6. SCAN (aaj + kal) -- setup / faisle bar + 5s par?")
days = [(now - timedelta(days=k)).strftime("%Y-%m-%d") for k in (1, 0)]
try:
    lines = io.open("bot.log", encoding="utf-8", errors="replace").read().splitlines()
except Exception as e:
    lines = []
    print("   bot.log parh nahi saka:", e)
bad = 0
for l in lines:
    if l[1:11] in days and ("[SESSION]" in l or "[SIGNAL] Entry" in l):
        print("   " + l[:200])
        m = re.match(r"\[\d{4}-\d{2}-\d{2} \d{2}:(\d{2}):(\d{2})\]", l)
        if m and "[SIGNAL] Entry" in l:
            mm, ss = int(m.group(1)), int(m.group(2))
            if not (mm % 5 == 0 and 4 <= ss <= 12):
                bad += 1
if bad:
    NOTE.append("%d setup bar + 5s par NAHI -- scan dekho" % bad)

if "--no-jurwa" not in sys.argv:
    H("7. JURWA v3 (export + live vs backtest)")
    print(py("export_m5.py", "--months", "3", timeout=900))
    out = py("jurwa.py", timeout=2400)
    print(out)
    if "*** FARQ ***" in out:
        NOTE.append("jurwa GATE FARQ")
    m = re.search(r"JORE: (\d+) \| sirf live: (\d+) \| sirf backtest: (\d+)", out)
    if m and (int(m.group(2)) or int(m.group(3))):
        NOTE.append("jurwa: sirf live %s / sirf backtest %s -- dekho" % (m.group(2), m.group(3)))

H("8. KHULASA")
if NOTE:
    for n in NOTE:
        print("   [DEKHEIN] " + n)
else:
    print("   SAB THEEK -- koi masla nahi mila.")
print("\nHO GAYA.")
