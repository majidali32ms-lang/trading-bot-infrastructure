# -*- coding: utf-8 -*-
"""
test_weekend_v437.py -- 10 Oct 2026 (HANDOVER 265). 17-18 Oct ki POORI weekend tarteeb HOOBAHOO cmd.exe mein
(aarzi folders, C:\\trading-bot jaisa dhaancha): PATCH_V436.md qadam 5 -> PATCH_V437.md qadam 1-3 -> dobara ->
WAPSI A (v4.36 par) -> phir lagao -> WAPSI B (v4.35 par). Sirf rasta aur `python` badalta hai. VPS ko kuch nahi.

    python test_weekend_v437.py
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
R = []


def ok(name, cond, extra=""):
    R.append(bool(cond))
    print(("PAAS " if cond else "FAIL ") + name + (("   [%s]" % extra) if (extra and not cond) else ""), flush=True)


def m(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()[:8]


W = tempfile.mkdtemp(prefix="wk7_")
PYW = '"%s"' % sys.executable
V6, V7 = os.path.join(HERE, "vps_vwap_v436"), os.path.join(HERE, "vps_vwap_v437")
TB, TV = os.path.join(W, "trading-bot"), os.path.join(W, "trading-bot-vwap")
DIRS = (TB, os.path.join(TV, "DE40"), os.path.join(TV, "US30"))
shutil.copytree(os.path.join(HERE, "vps_vwap"), TV)                                   # VPS aaj (v4.35)
os.makedirs(TB)
shutil.copy(os.path.join(HERE, "bot.py.bak_v435"), os.path.join(TB, "bot.py"))   # VPS (10 Oct se pehle) = v4.35
for s in ("DE40", "US30"):
    c = json.load(open(os.path.join(TV, s, "config_NAMOONA.json"), encoding="utf-8"))
    c.update(telegram_token="x", secret_key="s")
    json.dump(c, open(os.path.join(TV, s, "config.json"), "w"))
shutil.copytree(TV, os.path.join(W, "trading-bot-vwap-backup-v436"))                 # V436 qadam 1


def local(cmd):
    cmd = cmd.replace("C:\\trading-bot", W + "\\trading-bot").replace("cd C:\\ &&", "cd /d %s &&" % W)
    cmd = re.sub(r"(?<![\w\\])python ", lambda _m: PYW + " ", cmd)
    return cmd.split(" & notepad")[0]


def run(cmd, out=None):
    bat = os.path.join(W, "x.bat")
    open(bat, "w").write("@echo off\n" + local(cmd) + "\n")
    p = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True, errors="replace")
    if out is None:
        return p.stdout + p.stderr
    f = os.path.join(W, out)
    return open(f, encoding="utf-8", errors="replace").read() if os.path.exists(f) else ""


def state():
    return dict(sb=m(os.path.join(TB, "bot.py")), de=m(os.path.join(TV, "DE40", "bot.py")),
                us=m(os.path.join(TV, "US30", "bot.py")),
                man=json.load(open(os.path.join(TV, "MANIFEST.json")))["bot.py"], rv=m(os.path.join(TV, "run_vwap.py")))


def status():
    p = subprocess.run([sys.executable, "run_vwap.py", "--status"], cwd=TV, capture_output=True, text=True, errors="replace")
    return p.stdout.count("md5 masle: koi nahi")


d6 = open(os.path.join(V6, "PATCH_V436.md"), encoding="utf-8").read()
d7 = open(os.path.join(V7, "PATCH_V437.md"), encoding="utf-8").read()
ok("dono package ki PATCH_V436.md aik jaisi", d6 == open(os.path.join(V7, "PATCH_V436.md"), encoding="utf-8").read())
s5 = re.search(r"## 5\..*?```\n(cd C:.*?)\n```", d6, re.S).group(1)
w6 = re.search(r"## WAPSI.*?```\n\s*(cd C:.*?)\n\s*```", d6, re.S).group(1)
c1 = re.search(r"## 1\..*?```\n(copy /Y .*?)\n```", d7, re.S).group(1)
c2 = re.search(r"## 2\..*?```\n(cd C:.*?)\n```", d7, re.S).group(1)
c3 = re.search(r"## 3\..*?```\n(cd C:.*?)\n```", d7, re.S).group(1)
wa = re.search(r"\*\*A\..*?```\n\s*(cd C:.*?)\n\s*```", d7, re.S).group(1)

print("=" * 72)
print("test_weekend_v437 -- PATCH_V436 qadam 5 + PATCH_V437 1-3 + WAPSI A / B, cmd.exe, aarzi folder")
print("=" * 72)
st0 = state()
PRE = dict(st0)
ok("shuru: teeno bot.py bd901c0f, MANIFEST bd901c0f, run_vwap 3e326a33 (VPS aaj)",
   st0 == dict(sb="bd901c0f", de="bd901c0f", us="bd901c0f", man="bd901c0f", rv="3e326a33"), str(st0))
# ---- v4.36: qadam 3 (files) + qadam 5
for d in DIRS:
    shutil.copy(os.path.join(V6, "apply_report_patch.py"), d)
for f in ("run_vwap.py", "MANIFEST.json"):
    shutil.copy(os.path.join(V6, f), TV)
o = run(s5, os.path.join("trading-bot-vwap", "patch_v436.txt"))
ok("V436 qadam 5: 3x LAGA 7a55255a", o.count("LAGA: bot.py v4.36 md5 7a55255a") == 3 and "RUKA" not in o, o[-300:])
# ---- v4.37 qadam 1
for d in DIRS:
    shutil.copy(os.path.join(V7, "apply_offset_patch.py"), d)
run(c1)
ok("V437 qadam 1: MANIFEST_v436.json bana (bot.py 7a55255a)",
   json.load(open(os.path.join(TV, "MANIFEST_v436.json")))["bot.py"] == "7a55255a")
shutil.copy(os.path.join(V7, "MANIFEST.json"), TV)
# ---- qadam 2 dikhawa
o = run(c2, os.path.join("trading-bot", "patch437_dikhawa.txt"))
ok("V437 qadam 2 dikhawa: 7a55255a, 3 jagah, hogi 267c6530, kuch nahi likha", "bot.py md5 abhi: 7a55255a" in o
   and "3 jagah" in o and "hogi 267c6530 (chahiye 267c6530)" in o and "DIKHAWA" in o
   and m(os.path.join(TB, "bot.py")) == "7a55255a", o[-300:])
# ---- qadam 3
o = run(c3, os.path.join("trading-bot-vwap", "patch_v437.txt"))
st = state()
ok("V437 qadam 3: 3x LAGA 267c6530, koi RUKA nahi", o.count("LAGA: bot.py v4.37 md5 267c6530") == 3 and "RUKA" not in o,
   o[-400:])
ok("V437 qadam 3: --status DE40 + US30 'md5 masle: koi nahi'", o.count("md5 masle: koi nahi") == 2, o[-600:])
ok("V437 qadam 3: certutil 267c6530 + teeno bot.py 267c6530 + MANIFEST 267c6530", "267c6530" in o and
   (st["sb"], st["de"], st["us"], st["man"]) == ("267c6530",) * 4, str(st))
ok("backups: bot.py.bak_offset 7a55255a + bot.py.bak_report bd901c0f teeno jagah",
   all(m(os.path.join(d, "bot.py.bak_offset")) == "7a55255a" and m(os.path.join(d, "bot.py.bak_report")) == "bd901c0f"
       for d in DIRS))
o = run(c3, os.path.join("trading-bot-vwap", "patch_v437.txt"))
ok("qadam 3 DOBARA: 3x PEHLE SE, kuch nahi bigra", o.count("PEHLE SE LAGA") == 3 and state() == st)
# ---- WAPSI A
o = run(wa, os.path.join("trading-bot-vwap", "wapsi_v437.txt"))
st = state()
ok("WAPSI A: 3x WAPAS 7a55255a, MANIFEST 7a55255a, run_vwap 6bb3a5f4", o.count("WAPAS: bot.py md5 7a55255a") == 3
   and st == dict(sb="7a55255a", de="7a55255a", us="7a55255a", man="7a55255a", rv="6bb3a5f4"), "%s | %s" % (st, o[-300:]))
ok("WAPSI A ke baad --status: dono 'koi nahi' (v4.36 watchdog ke saath chalega)", status() == 2)
# ---- dobara lagao, phir WAPSI B (A ka qadam 2 + V436 WAPSI qadam 2)
shutil.copy(os.path.join(V7, "MANIFEST.json"), TV)
o = run(c3, os.path.join("trading-bot-vwap", "patch_v437.txt"))
ok("dobara lagaya: 3x LAGA 267c6530", o.count("LAGA: bot.py v4.37 md5 267c6530") == 3)
run(wa, os.path.join("trading-bot-vwap", "wapsi_v437.txt"))
o = run(w6, os.path.join("trading-bot-vwap", "wapsi_v436.txt"))
st = state()
ok("WAPSI B: 3x WAPAS bd901c0f, run_vwap + MANIFEST backup jaise (VPS aaj)",
   o.count("WAPAS: bot.py md5 bd901c0f") == 3 and st == PRE, "%s vs %s" % (st, PRE))
ok("WAPSI B ke baad --status: dono 'koi nahi'", status() == 2)
shutil.rmtree(W, ignore_errors=True)
print("\nKUL: %d / %d PAAS" % (sum(R), len(R)))
sys.exit(0 if all(R) else 1)
