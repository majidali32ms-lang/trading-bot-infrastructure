# -*- coding: utf-8 -*-
"""
test_weekend_cmds.py -- 10 Oct 2026 (HANDOVER 264). PATCH_V436.md ki weekend commands (qadam 5 "lagao" aur
WAPSI) HOOBAHOO cmd.exe mein chalata hai -- aarzi folders mein (C:\\trading-bot jaisa dhaancha); sirf rasta aur
`python` (PC par Store wala nakli) badalta hai. VPS / asal bot ko kuch nahi.

    python test_weekend_cmds.py
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


W = tempfile.mkdtemp(prefix="wk_")
PYW = '"%s"' % sys.executable
V = os.path.join(HERE, "vps_vwap_v436")
shutil.copytree(os.path.join(HERE, "vps_vwap"), os.path.join(W, "trading-bot-vwap"))          # VPS aaj (v4.35)
os.makedirs(os.path.join(W, "trading-bot"))
shutil.copy(os.path.join(HERE, "bot.py.bak_v435"), os.path.join(W, "trading-bot", "bot.py"))   # VPS aaj = v4.35
for s in ("DE40", "US30"):
    c = json.load(open(os.path.join(W, "trading-bot-vwap", s, "config_NAMOONA.json"), encoding="utf-8"))
    c.update(telegram_token="x", secret_key="s")
    json.dump(c, open(os.path.join(W, "trading-bot-vwap", s, "config.json"), "w"))
shutil.copytree(os.path.join(W, "trading-bot-vwap"), os.path.join(W, "trading-bot-vwap-backup-v436"))   # qadam 1
PRE = None                                                    # qadam 3 se PEHLE ki halat (neeche)
for d in ("trading-bot", os.path.join("trading-bot-vwap", "DE40"), os.path.join("trading-bot-vwap", "US30")):  # qadam 3
    shutil.copy(os.path.join(V, "apply_report_patch.py"), os.path.join(W, d))
for f in ("run_vwap.py", "MANIFEST.json"):
    shutil.copy(os.path.join(V, f), os.path.join(W, "trading-bot-vwap"))

doc = open(os.path.join(V, "PATCH_V436.md"), encoding="utf-8").read()
s5 = re.search(r"## 5\..*?```\n(cd C:.*?)\n```", doc, re.S).group(1)
wp = re.search(r"## WAPSI.*?```\n\s*(cd C:.*?)\n\s*```", doc, re.S).group(1)


def local(cmd):
    cmd = cmd.replace("C:\\trading-bot", W + "\\trading-bot").replace("cd C:\\ &&", "cd /d %s &&" % W)
    cmd = re.sub(r"(?<![\w\\])python ", lambda _m: PYW + " ", cmd)
    return cmd.split(" & notepad")[0]


def state():
    return dict(sb=m(os.path.join(W, "trading-bot", "bot.py")), de=m(os.path.join(W, "trading-bot-vwap", "DE40", "bot.py")),
                us=m(os.path.join(W, "trading-bot-vwap", "US30", "bot.py")),
                man=json.load(open(os.path.join(W, "trading-bot-vwap", "MANIFEST.json")))["bot.py"],
                rv=m(os.path.join(W, "trading-bot-vwap", "run_vwap.py")))


def run(cmd, outname):
    bat = os.path.join(W, "x.bat")
    open(bat, "w").write("@echo off\n" + cmd + "\n")
    subprocess.run(["cmd", "/c", bat], capture_output=True)
    p = os.path.join(W, "trading-bot-vwap", outname)
    return open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""


print("=" * 72)
print("test_weekend_cmds -- PATCH_V436.md ki commands, cmd.exe, aarzi folder")
print("=" * 72)
st0 = state()
PRE = dict(st0, man="bd901c0f", rv=m(os.path.join(W, "trading-bot-vwap-backup-v436", "run_vwap.py")))   # backup (VPS aaj)
ok("shuru: teeno bot.py bd901c0f (VPS aaj jaisa)", (st0["sb"], st0["de"], st0["us"]) == ("bd901c0f",) * 3, str(st0))
out = run(local(s5), "patch_v436.txt")
st = state()
print("   " + "\n   ".join(l.strip()[:110] for l in out.splitlines() if re.search(r"LAGA|RUKA|masle|^[0-9a-f]{32}", l)))
ok("qadam 5: output file bani, TEEN dafa 'LAGA ... 7a55255a', koi RUKA nahi", out.count("LAGA: bot.py v4.36 md5 7a55255a") == 3
   and "RUKA" not in out)
ok("qadam 5: --status DE40 + US30 'md5 masle: koi nahi' (naya watchdog MANIFEST 7a55255a maanta)",
   out.count("md5 masle: koi nahi") == 2, out[-600:])
ok("qadam 5: certutil 7a55255a + teeno bot.py 7a55255a", "7a55255a" in out and (st["sb"], st["de"], st["us"]) == ("7a55255a",) * 3,
   str(st))
ok("qadam 5: backup bot.py.bak_report bd901c0f teeno jagah", all(m(os.path.join(W, d, "bot.py.bak_report")) == "bd901c0f" for d in
   ("trading-bot", os.path.join("trading-bot-vwap", "DE40"), os.path.join("trading-bot-vwap", "US30"))))
out2 = run(local(s5), "patch_v436.txt")
ok("qadam 5 DOBARA chalaya: teen dafa 'PEHLE SE', kuch nahi bigra", out2.count("PEHLE SE LAGA") == 3 and state() == st)
outw = run(local(wp), "wapsi_v436.txt")
stw = state()
print("   " + "\n   ".join(l.strip()[:110] for l in outw.splitlines() if re.search(r"WAPAS|RUKA|copied|^[0-9a-f]{32}", l)))
ok("WAPSI: teen dafa 'WAPAS ... bd901c0f', run_vwap + MANIFEST purane", outw.count("WAPAS: bot.py md5 bd901c0f") == 3
   and stw == PRE, "%s vs %s" % (stw, PRE))
shutil.rmtree(W, ignore_errors=True)
print("\nKUL: %d / %d PAAS" % (sum(R), len(R)))
sys.exit(0 if all(R) else 1)
