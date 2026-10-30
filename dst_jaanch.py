# -*- coding: utf-8 -*-
"""
dst_jaanch.py -- 10 Oct 2026 (HANDOVER 264.6). SIRF PARHTA HAI: koi order nahi, kuch nahi likhta.

Sawal: broker (MT5) ka server waqt US DST ke saath badalta hai (hamesha NY+7) ya EU DST ke saath
(EU aur US ki tareekhon ke beech wale hafton mein NY+6)?

Tareeqa: forex ka hafta HAR broker par Sunday 17:00 New York par khulta hai. EURUSD ki H1 bars mein har
hafte ki PEHLI bar ka server waqt dekho:
    server - NY(Sun 17:00) = 7 ghante  -> us hafte server = NY+7
    server - NY(Sun 17:00) = 6 ghante  -> us hafte server = NY+6
Ahem hafte = "beech wale" (US DST badal chuka, EU nahi -- ya ulta):
    Oct 26 2025 (EU 26 Oct khatam, US 2 Nov)    Mar 08 / 15 / 22 2026 (US 8 Mar shuru, EU 29 Mar)
Agar in hafton mein bhi 7 -> server US DST ke saath (NY+7 hamesha) -> v4.36 report ka farz SAHI.
Agar in mein 6 -> EU DST ke saath -> un hafton mein server NY+6 (264.6 dekho: weekly par asar nahi).

    cd C:\\trading-bot && (python dst_jaanch.py) > dst_jaanch.txt 2>&1 & notepad dst_jaanch.txt
Chahiye: chalta MT5 terminal (EURUSD ki H1 history). Python 3.11.
"""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

VERSION = "dst_jaanch v1 -- 10 Oct 2026 (sirf parhta hai)"
NY = ZoneInfo("America/New_York")
MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")

# (hafte ka Sunday, kis qism ka hafta)
WEEKS = [
    ("2025-10-19", "dono garmi (control)"),
    ("2025-10-26", "BEECH: EU sardi, US garmi"),
    ("2025-11-02", "dono sardi (control)"),
    ("2026-03-01", "dono sardi (control)"),
    ("2026-03-08", "BEECH: US garmi, EU sardi"),
    ("2026-03-15", "BEECH: US garmi, EU sardi"),
    ("2026-03-22", "BEECH: US garmi, EU sardi"),
    ("2026-03-29", "dono garmi (control)"),
    ("2026-09-27", "dono garmi (control)"),
]


def week_gap(mt5, sym, sunday):
    """Us hafte ki pehli H1 bar: (server waqt naive, server - NY Sun 17:00 ghanton mein) ya None."""
    d = datetime.strptime(sunday, "%Y-%m-%d")
    ny_open = d.replace(hour=17)                                   # NY naive, Sunday 17:00
    lo = ny_open + timedelta(hours=2)                              # server naive: NY+2 .. NY+12 ke beech dhoondo
    hi = ny_open + timedelta(hours=14)
    r = mt5.copy_rates_range(sym, mt5.TIMEFRAME_H1, lo.replace(tzinfo=timezone.utc), hi.replace(tzinfo=timezone.utc))
    if r is None or len(r) == 0:
        return None
    first = datetime.fromtimestamp(int(r[0]["time"]), timezone.utc).replace(tzinfo=None)
    prev = mt5.copy_rates_range(sym, mt5.TIMEFRAME_H1, (lo - timedelta(hours=40)).replace(tzinfo=timezone.utc),
                                (first - timedelta(minutes=1)).replace(tzinfo=timezone.utc))
    # pehli bar se pehle kam az kam 24 ghante khaali (weekend) -- warna yeh hafte ki pehli bar nahi
    if prev is not None and len(prev) and (first - datetime.fromtimestamp(int(prev[-1]["time"]), timezone.utc)
                                           .replace(tzinfo=None)) < timedelta(hours=24):
        return None
    return first, round((first - ny_open).total_seconds() / 3600.0, 2)


def main(mt5=None, out=print):
    out(VERSION)
    own = mt5 is None
    if own:
        import MetaTrader5 as mt5
        if not mt5.initialize(path=MT5_PATH):
            out("MT5 se raabta nahi: %s" % (mt5.last_error(),))
            return 1
    try:
        rows = []
        for sunday, kind in WEEKS:
            got = None
            for sym in SYMBOLS:
                got = week_gap(mt5, sym, sunday)
                if got:
                    got = (sym,) + got
                    break
            rows.append((sunday, kind, got))
    finally:
        if own:
            mt5.shutdown()

    out("\nHafta (Sunday)  qism                          symbol  pehli bar (server)   server - NY")
    for sunday, kind, got in rows:
        if got:
            sym, first, h = got
            out("%-15s %-30s %-7s %-20s %+.2f h" % (sunday, kind, sym, first.strftime("%a %Y-%m-%d %H:%M"), h))
        else:
            out("%-15s %-30s data nahi (H1 history itni purani nahi?)" % (sunday, kind))

    beech = [g[2] for _, k, g in rows if k.startswith("BEECH") and g]
    ctrl = [g[2] for _, k, g in rows if not k.startswith("BEECH") and g]
    out("")
    if not beech:
        out("FAISLA NAHI: beech wale hafton ka data nahi mila. MT5 mein EURUSD H1 chart kholo, Home dabao")
        out("(purani history aaye) aur dobara chalao.")
        return 2
    if ctrl and any(h != 7 for h in ctrl):
        out("AJEEB: control hafte bhi 7 nahi (%s) -- output Claude ko." % ctrl)
        return 3
    if all(h == 7 for h in beech):
        out("NATIJA: server US DST ke saath -- HAMESHA NY+7 (beech wale hafte bhi). v4.36 report ka farz SAHI.")
        return 0
    if all(h == 6 for h in beech):
        out("NATIJA: server EU DST ke saath -- beech wale hafton mein NY+6. v4.36: weekly par asar NAHI (daira")
        out("market band ke waqt khatam); sirf 31 Oct jab haftay ka din ho, monthly ki had 1 ghanta khiskay (264.6).")
        return 0
    out("MILA-JULA natija (%s) -- output Claude ko." % beech)
    return 3


if __name__ == "__main__":
    sys.exit(main())
