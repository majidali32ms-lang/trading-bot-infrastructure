#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
news_shadow.py  --  SHADOW ONLY. Kisi trade ko ROKTA NAHI.

KYUN (13 Sep 2026):
    Pre-live checklist ka A2 "news filter" hai. Majid ka sawal: filter
    kitna bachao karta hai? Us ka jawab filter LAGA kar nahi mil sakta
    -- agar woh trades rok de to hum kabhi jaan hi nahi payenge ke woh
    trades kya karteen.

    Is liye yeh sirf DARJ karta hai: har trade par likh deta hai ke woh
    news se kitne minute door thi. 60 trades ke baad hum koi bhi window
    (5, 15, 30, 60 minute) aazma kar dekh sakte hain ke kaunsi behtar
    thi -- aur faisla saboot ke sath hoga, andaze par nahi.

    Window yahan JAAN BOOJH KAR tay nahi ki gayi. Agar abhi tay karte
    to "best of N" wala masla banta.

DESIGN:
    - bot.py mein sirf 2-3 line jati hain (apply_news_shadow.py se).
    - saara kaam is file mein hai.
    - koi internet nahi, koi API nahi. Tareekhein news_dates.txt se.
      (Live bot ka koi hissa kisi bahar wali service par nahi tikna
       chahiye -- woh band ho jaye to filter khamoshi se ghalat jawab
       dene lagega.)
    - NFP khud hisab lagti hai: har mahine pehla Friday 08:30 ET.

KHUD CHALA KAR DEKHNE KE LIYE:
    python news_shadow.py              -- aane wali news dikhata hai
    python news_shadow.py --test       -- apne aap ko jaanchta hai
"""

import os
import sys
from datetime import datetime, timedelta

DATES_FILE = "news_dates.txt"
_CACHE = {"mtime": None, "events": []}


def _first_friday(year, month):
    d = datetime(year, month, 1)
    while d.weekday() != 4:          # 4 = Friday
        d += timedelta(days=1)
    return d.replace(hour=8, minute=30)


def nfp_dates(start, end):
    """Har mahine pehla Friday 08:30 ET."""
    out, y, m = [], start.year, start.month
    while datetime(y, m, 1) <= end:
        d = _first_friday(y, m)
        if start <= d <= end:
            out.append((d, "NFP"))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def load_events(folder=None):
    """news_dates.txt + khud hisab ki hui NFP. File badle to dobara parhta hai."""
    folder = folder or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(folder, DATES_FILE)
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = None
    if _CACHE["mtime"] == mt and _CACHE["events"]:
        return _CACHE["events"]

    ev = []
    if mt is not None:
        with open(path, encoding="utf-8", errors="replace") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"):
                    continue
                parts = ln.split(None, 2)
                if len(parts) < 3:
                    continue
                try:
                    d = datetime.strptime(parts[0] + " " + parts[1],
                                          "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                ev.append((d, parts[2].strip()))

    if ev:
        lo = min(d for d, _ in ev) - timedelta(days=400)
        hi = max(d for d, _ in ev) + timedelta(days=400)
    else:
        now = datetime.now()
        lo, hi = now - timedelta(days=400), now + timedelta(days=400)

    # NFP ka khud hisab. LEKIN agar us mahine ke liye news_dates.txt
    # mein NFP likhi hai to wohi chalegi -- chhutti ki wajah se NFP
    # khisak jati hai (misal: 1 Jan, ya 3 July 2026 -> 2 July),
    # aur qaida likhne ke bajaye Majid ka likha hua mano.
    manual_nfp = set((d.year, d.month) for d, n in ev
                     if n.strip().upper().startswith("NFP"))
    for d, n in nfp_dates(lo, hi):
        if (d.year, d.month) not in manual_nfp:
            ev.append((d, n))
    ev.sort()
    _CACHE["mtime"], _CACHE["events"] = mt, ev
    return ev


def nearest(when, folder=None):
    """Sab se qareeb news. Wapas: (naam, minute) ya (None, None).

    minute MANFI = news abhi aani hai (trade us se PEHLE hai)
    minute MUSBAT = news guzar chuki (trade us ke BAAD hai)
    """
    ev = load_events(folder)
    if not ev:
        return None, None
    best, bestm = None, None
    for d, name in ev:
        mins = (when - d).total_seconds() / 60.0
        if bestm is None or abs(mins) < abs(bestm):
            best, bestm = name, mins
    return best, int(round(bestm))


def tag(when, folder=None):
    """bot.py isi ko bulata hai. Hamesha aik chhoti satar wapas karta hai.

    Kabhi exception nahi phenkta -- bot kisi haal mein na ruke.
    """
    try:
        name, mins = nearest(when, folder)
        if name is None:
            return "NEWS_SHADOW none"
        return "NEWS_SHADOW %s %+d min" % (name, mins)
    except Exception as e:
        return "NEWS_SHADOW error %s" % type(e).__name__


# ---------------------------------------------------------------- test
def _test():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("  [OK  ] " if cond else "  [FAIL] ") + msg)
        if not cond:
            ok = False

    print("1. NFP ka hisab")
    # Sept 2026: 1st = Tuesday -> pehla Friday = 4 Sep
    chk(_first_friday(2026, 9) == datetime(2026, 9, 4, 8, 30), "Sep 2026 -> 4 Sep 08:30")
    # Oct 2026: 1st = Thursday -> pehla Friday = 2 Oct
    chk(_first_friday(2026, 10) == datetime(2026, 10, 2, 8, 30), "Oct 2026 -> 2 Oct 08:30")
    # May 2026: 1st = Friday khud
    chk(_first_friday(2026, 5) == datetime(2026, 5, 1, 8, 30), "May 2026 -> 1 May (khud Friday)")

    print("2. Faasla aur nishan")
    n, m = nearest(datetime(2026, 9, 16, 14, 7))
    chk(n == "FOMC" and m == 7, "FOMC ke 7 min BAAD -> +7  (mila: %s %s)" % (n, m))
    n, m = nearest(datetime(2026, 9, 16, 13, 45))
    chk(n == "FOMC" and m == -15, "FOMC se 15 min PEHLE -> -15  (mila: %s %s)" % (n, m))
    n, m = nearest(datetime(2026, 10, 2, 8, 30))
    chk(n == "NFP" and m == 0, "NFP par theek -> 0  (mila: %s %s)" % (n, m))

    print("2b. news_dates.txt ki NFP khud-hisab ko dabati hai")
    import tempfile
    td = tempfile.mkdtemp()
    with open(os.path.join(td, DATES_FILE), "w", encoding="utf-8") as f:
        f.write("2027-01-08 08:30  NFP\n")
    _CACHE["mtime"], _CACHE["events"] = None, []
    ev = load_events(td)
    jan = [d for d, n in ev if d.year == 2027 and d.month == 1 and n.startswith("NFP")]
    chk(len(jan) == 1 and jan[0].day == 8,
        "Jan 2027 NFP sirf 8 tareekh (1 Jan wali nahi) -- mila: %s" % [d.day for d in jan])
    feb = [d for d, n in ev if d.year == 2027 and d.month == 2 and n.startswith("NFP")]
    chk(len(feb) == 1 and feb[0].day == 5,
        "Feb 2027 NFP khud hisab se 5 -- mila: %s" % [d.day for d in feb])
    _CACHE["mtime"], _CACHE["events"] = None, []

    print("3. tag() ki shakl")
    chk(tag(datetime(2026, 9, 16, 14, 7)) == "NEWS_SHADOW FOMC +7 min", tag(datetime(2026, 9, 16, 14, 7)))
    chk(tag(datetime(2026, 9, 16, 13, 45)) == "NEWS_SHADOW FOMC -15 min", tag(datetime(2026, 9, 16, 13, 45)))

    print("4. Kharabi ki soorat mein bhi kabhi crash nahi")
    chk(tag(None).startswith("NEWS_SHADOW error"), "None do -> %s" % tag(None))
    chk(tag("kachra").startswith("NEWS_SHADOW error"), "text do -> %s" % tag("kachra"))
    _CACHE["mtime"], _CACHE["events"] = None, []
    chk(tag(datetime(2026, 9, 16, 14, 7), folder="/nahi/hai").startswith("NEWS_SHADOW"),
        "file gayab -> %s" % tag(datetime(2026, 9, 16, 14, 7), folder="/nahi/hai"))
    _CACHE["mtime"], _CACHE["events"] = None, []

    print()
    print("SAB THEEK" if ok else "KUCH FAIL HUA")
    return 0 if ok else 1


def main():
    if "--test" in sys.argv:
        return _test()
    ev = load_events()
    now = datetime.now()
    print("news_dates.txt + NFP se %d events mile." % len(ev))
    print()
    print("Aane wali 10:")
    for d, n in [x for x in ev if x[0] >= now][:10]:
        print("  %s  %s  (%d din baad)" % (d.strftime("%Y-%m-%d %H:%M"), n,
                                           (d - now).days))
    name, mins = nearest(now)
    print()
    print("Abhi sab se qareeb: %s  %+d min" % (name, mins))
    return 0


if __name__ == "__main__":
    sys.exit(main())
