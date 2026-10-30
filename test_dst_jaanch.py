# -*- coding: utf-8 -*-
"""test_dst_jaanch.py -- dst_jaanch.py nakli MT5 par: US-DST broker, EU-DST broker, data nahi, ajeeb."""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

import dst_jaanch as D

NY, UTC, ATH = ZoneInfo("America/New_York"), ZoneInfo("UTC"), ZoneInfo("Europe/Athens")   # Athens = EET/EEST (EU)
R = []


def ok(name, cond, extra=""):
    R.append(bool(cond))
    print(("PAAS " if cond else "FAIL ") + name + (("   [%s]" % extra) if (extra and not cond) else ""), flush=True)


class FakeMT5(object):
    TIMEFRAME_H1 = 16385

    def __init__(self, rule, start="2025-10-01", end="2026-10-09"):
        # asal UTC mein forex: Sun 17:00 NY se Fri 17:00 NY, har ghanta
        self.calls = []
        bars = []
        t = datetime(2025, 9, 28, 21, tzinfo=UTC)
        stop = datetime(2026, 10, 10, tzinfo=UTC)
        while t < stop:
            ny = t.astimezone(NY)
            wd, h = ny.weekday(), ny.hour
            openm = (wd == 6 and h >= 17) or wd in (0, 1, 2, 3) or (wd == 4 and h < 17)
            if openm:
                if rule == "US":
                    srv = ny.replace(tzinfo=None) + timedelta(hours=7)
                else:
                    srv = t.astimezone(ATH).replace(tzinfo=None)
                bars.append(int(srv.replace(tzinfo=timezone.utc).timestamp()))
            t += timedelta(hours=1)
        self.t = np.array(bars, dtype=np.int64)

    def copy_rates_range(self, sym, tf, a, b):
        self.calls.append(("copy_rates_range", sym))
        lo, hi = int(a.timestamp()), int(b.timestamp())
        sel = self.t[(self.t >= lo) & (self.t <= hi)]
        out = np.zeros(len(sel), dtype=[("time", "<i8")])
        out["time"] = sel
        return out


class NoOld(FakeMT5):
    def copy_rates_range(self, sym, tf, a, b):
        if a.year == 2025 or (a.year == 2026 and a.month == 3):
            return None
        return FakeMT5.copy_rates_range(self, sym, tf, a, b)


def run(mt5):
    lines = []
    rc = D.main(mt5=mt5, out=lines.append)
    return rc, "\n".join(lines)


rc, out = run(FakeMT5("US"))
print(out)
ok("US-DST broker: har hafta +7.00, NATIJA 'HAMESHA NY+7'", rc == 0 and "HAMESHA NY+7" in out and out.count("+7.00 h") == 9, out)
rc, out = run(FakeMT5("EU"))
print(out)
ok("EU-DST broker: beech wale 4 hafte +6.00, control +7.00, NATIJA 'EU DST'", rc == 0 and "EU DST" in out
   and out.count("+6.00 h") == 4 and out.count("+7.00 h") == 5, out)
rc, out = run(NoOld("US"))
ok("purani history nahi: FAISLA NAHI (andaza nahi lagata)", rc == 2 and "FAISLA NAHI" in out, out)
m = FakeMT5("US")
run(m)
ok("sirf copy_rates_range -- aur koi MT5 call nahi (sirf parhta)", {c[0] for c in m.calls} == {"copy_rates_range"})

# ---- v4.36 ka APNA _srv_naive (patch_report/bot.py se nikaal kar) -- EU-DST broker par daira kahan girta?
import os
import re
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch_report", "bot.py"), encoding="utf-8").read()
blk = re.search(r"\n( *)def _srv_naive\(_u\):\n.*?\n\1    \s*\+ timedelta\(hours=7\)\)\n", src, re.S).group(0)
g = {"ZoneInfo": ZoneInfo, "NY": NY, "timedelta": timedelta}
exec("\n".join(l[len(re.match(r"\n( *)", blk).group(1)):] for l in blk.strip("\n").split("\n")), g)
srv_naive = g["_srv_naive"]
DXB = ZoneInfo("Asia/Dubai")


def real_ny(srv, rule):
    """Server ka naive waqt -> asal NY waqt, broker ke qaide se."""
    if rule == "US":
        return (srv - timedelta(hours=7)).replace(tzinfo=NY)
    return srv.replace(tzinfo=ATH).astimezone(NY)


def us30_open(ny):
    """US30 khula? Sun 18:00 NY -> Fri 17:00 NY, roz 17:00-18:00 waqfa."""
    wd, h = ny.weekday(), ny.hour
    if wd == 5 or (wd == 6 and h < 18) or (wd == 4 and h >= 17):
        return False
    return h != 17


bad_w, n_w, exact = [], 0, True
d = datetime(2025, 10, 6, tzinfo=DXB)                           # Monday
while d.year < 2031:
    a = d                                                          # scheduler: Mon 00:00 Dubai
    b = (d + timedelta(days=5)).replace(hour=3)                     # Sat 03:00 Dubai
    for t in (a, b):
        u = t.astimezone(UTC).replace(tzinfo=None)
        if real_ny(srv_naive(u), "US") != t.astimezone(NY):
            exact = False
        if us30_open(real_ny(srv_naive(u), "EU")):
            bad_w.append(t)
    n_w += 1
    d += timedelta(days=7)
ok("v4.36 _srv_naive: US-DST broker par weekly daira HOOBAHOO (%d hafte 2025-2030)" % n_w, exact)
ok("v4.36 _srv_naive: EU-DST broker par bhi weekly ki dono hadd US30 BAND waqt mein (%d hafte)" % n_w, not bad_w,
   str(bad_w[:5]))
bad_m = []
for y in range(2026, 2031):
    for mo in range(1, 13):
        t = datetime(y, mo, 1, 3, tzinfo=DXB)                       # monthly hadd: 1 tareekh 03:00 Dubai
        u = t.astimezone(UTC).replace(tzinfo=None)
        if real_ny(srv_naive(u), "EU") != t.astimezone(NY) and us30_open(real_ny(srv_naive(u), "EU")):
            bad_m.append(t.astimezone(NY).strftime("%a %Y-%m-%d %H:%M NY"))
print("   EU-DST broker par monthly hadd jo khule market mein 1 ghanta khiskay: %s" % (bad_m or "koi nahi"))
ok("monthly: sirf 31 Oct wali hadd (19:00 NY), 2026 mein koi nahi (31 Oct 2026 = Saturday)",
   all("-10-31 19:00" in x for x in bad_m) and not any(x[4:8] == "2026" for x in bad_m), str(bad_m))
print("\nKUL: %d / %d PAAS" % (sum(R), len(R)))
sys.exit(0 if all(R) else 1)
