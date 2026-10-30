# -*- coding: utf-8 -*-
"""
sim_harness.py -- 6 Oct 2026 (HANDOVER 260). PARITY ka dhaancha (sirf PC tests).

bot.py (bd901c0f, HOOBAHOO copy) ko NAKLI GHADI par chalata hai -- us ke apne saare threads
(scanner, monitor, Friday, reports, heartbeat, Telegram poller, backup ...) asal code mein,
magar do din chand minute mein. Do raaste, AIK market:
  A = bot.py + NAKLI MT5 (asal MT5 ka rawaiyya, yahan alag se likha -- shim se ALAG)
  B = bot.py + mt5_ctrader (shim) + NAKLI cTRADER SERVER (JSON / WebSocket, asal payload numbers)
Dono ke log, Telegram, trades.csv, events.csv aur orders milaye jaate hain (test_parity.py).

Asal broker / account / Telegram ko KABHI nahi chhoota.
"""
import builtins
import calendar
import csv
import hashlib
import heapq
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import textwrap
import threading
import time as _rt
import types
from datetime import datetime as _RealDT, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
NY = ZoneInfo("America/New_York")
BOT_MD5 = "bd901c0f"
KNOWN_BOT = {"bd901c0f": "v4.35", "7a55255a": "v4.36 (report patch)", "267c6530": "v4.37 (offset NY+7)"}
BOT_FILE = os.environ.get("SIM_BOT") or os.path.join(HERE, "bot.py")
_real_sleep = _rt.sleep
INF = float("inf")


def md5_8(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()[:8]


def ny_ts(y, mo, d, h, mi, s=0):
    return _RealDT(y, mo, d, h, mi, s, tzinfo=NY).timestamp()


def srv(utc):
    """MT5 server waqt = NY + 7h (shim se ALAG hisaab, jaan-boojh kar)."""
    off = _RealDT.fromtimestamp(utc, NY).utcoffset().total_seconds()
    return int(utc + off + 7 * 3600)


# ====================================================================== NAKLI GHADI
class Stop(BaseException):
    pass


class VTime(object):
    """Bot ke threads ke liye ghadi. Sab so jayein to waqt agle jaagne (ya market event) tak kood jata hai."""

    def __init__(self, t0):
        self.t = float(t0)
        self.cv = threading.Condition()
        self.sleeping = {}
        self.managed = set()
        self.stopped = False
        self.events = []
        self.seq = 0

    def now(self):
        return self.t

    def sleep(self, s):
        th = threading.current_thread()
        if th not in self.managed:
            _real_sleep(min(max(float(s), 0.0), 0.01))
            return
        with self.cv:
            if self.stopped:
                raise Stop()
            self.sleeping[th] = self.t + max(float(s), 0.0)
            self.cv.notify_all()
            while th in self.sleeping and not self.stopped:
                self.cv.wait()
            if self.stopped:
                raise Stop()

    def done(self, th):
        with self.cv:
            self.managed.discard(th)
            self.sleeping.pop(th, None)
            self.cv.notify_all()

    def at(self, t, fn):
        heapq.heappush(self.events, (t, self.seq, fn))
        self.seq += 1

    def wait_quiet(self, real_timeout=90):
        deadline = _rt.monotonic() + real_timeout
        with self.cv:
            while True:
                busy = [th for th in self.managed if th not in self.sleeping]
                if not busy:
                    return
                if _rt.monotonic() > deadline:
                    stacks = []
                    frames = sys._current_frames()
                    import traceback
                    for th in busy:
                        f = frames.get(th.ident)
                        stacks.append("%s:\n%s" % (th.name, "".join(traceback.format_stack(f)) if f else "-"))
                    raise RuntimeError("nakli ghadi ATAK gayi -- yeh threads so nahi rahe:\n" + "\n".join(stacks))
                self.cv.wait(0.5)

    def run_until(self, t_end, progress=None):
        n = 0
        while True:
            self.wait_quiet()
            with self.cv:
                nxt = min(self.sleeping.values()) if self.sleeping else INF
            ev = self.events[0][0] if self.events else INF
            target = min(nxt, ev)
            if target > t_end:
                with self.cv:
                    self.t = max(self.t, t_end)
                return
            with self.cv:
                self.t = max(self.t, target)
            while self.events and self.events[0][0] <= self.t:
                heapq.heappop(self.events)[2]()
            with self.cv:
                for th, w in list(self.sleeping.items()):
                    if w <= self.t:
                        del self.sleeping[th]
                self.cv.notify_all()
            n += 1
            if progress and n % 20000 == 0:
                progress(self.t)

    def stop(self):
        with self.cv:
            self.stopped = True
            self.sleeping.clear()
            self.cv.notify_all()


class TimeProxy(types.ModuleType):
    def __init__(self, vt):
        types.ModuleType.__init__(self, "time")
        self._vt = vt

    def time(self):
        return self._vt.t

    def sleep(self, s):
        self._vt.sleep(s)

    def __getattr__(self, n):
        return getattr(_rt, n)


def make_dt(vt):
    # 11 Oct 2026: bina tz wala now() / today() = VPS ki LOCAL ghadi = New York (VPS clock NY par). Pehle PC ki
    # local ghadi leta tha -> laptop Dubai par gaya to trades.csv / bot.log ka waqt 8 h aage (test_rutin jurwa).
    class VDT(_RealDT):
        @classmethod
        def now(cls, tz=None):
            return _RealDT.fromtimestamp(vt.t, tz) if tz is not None else _RealDT.fromtimestamp(vt.t, NY).replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return _RealDT.utcfromtimestamp(vt.t)

        @classmethod
        def today(cls):
            return _RealDT.fromtimestamp(vt.t, NY).replace(tzinfo=None)
    return VDT


def make_threading(vt):
    class VThread(threading.Thread):
        def start(self):
            self._vt_m = self.name != "mt5-worker"
            if self._vt_m:
                with vt.cv:
                    vt.managed.add(self)
            threading.Thread.start(self)

        def run(self):
            try:
                threading.Thread.run(self)
            except Stop:
                pass
            finally:
                if getattr(self, "_vt_m", False):
                    vt.done(self)
    m = types.ModuleType("threading")
    m.__dict__.update(threading.__dict__)
    m.Thread = VThread
    return m


class FakeReq(object):
    """requests ki jagah: Telegram ke paighaam yahan jama (asal Telegram NAHI)."""

    def __init__(self):
        self.sent = []
        self.updates = []
        self.lock = threading.Lock()
        self.uid = 0

    class R(object):
        def __init__(self, ok=True, body=None):
            self.ok, self._b = ok, body or {"ok": True, "result": True}

        def json(self):
            return self._b

    def post(self, url, json=None, data=None, files=None, timeout=None, **kw):
        m = url.rsplit("/", 1)[1]
        with self.lock:
            if m == "sendMessage":
                self.sent.append(("msg", str((json or {}).get("chat_id")), (json or {}).get("text", "")))
            elif m == "sendDocument":
                fn = list((files or {}).values())[0][0]
                self.sent.append(("doc", str((data or {}).get("chat_id")), fn, (data or {}).get("caption", "")))
        return FakeReq.R()

    def get(self, url, params=None, timeout=None, **kw):
        with self.lock:
            off = int((params or {}).get("offset") or 0)
            res = [u for u in self.updates if u["update_id"] >= off]
        return FakeReq.R(True, {"ok": True, "result": res})

    def command(self, chat_id, text):
        with self.lock:
            self.uid += 1
            self.updates.append({"update_id": self.uid, "message": {"chat": {"id": int(chat_id)}, "text": text}})


# ====================================================================== MARKET (dono raaston ka AIK)
class Market(object):
    """Aik symbol ki qeemat: spot events (utc t, bid) + M5 bars. Spread muqarrar."""

    def __init__(self, name, base, t_hist0, t0, spread=1.0):
        self.name, self.spread = name, spread
        self.t0 = t0
        self.level = base
        self.hist = []                      # (t0, o, h, l, c, vol) -- sim se pehle ki band bars
        t = int(t_hist0 // 300) * 300
        while t + 300 <= t0:
            self.hist.append((t, base, base + 1, base - 1, base, 4))
            t += 300
        self.ev = []                        # (t, bid)
        self.cursor = int(t0 // 300) * 300  # yahan tak bars ban chuki

    # -- banana --
    def _bar_events(self, t, o, h, l, c):
        first, second = (l, h) if c >= o else (h, l)
        self.ev += [(t + 1, o), (t + 61, first), (t + 121, second), (t + 241, c)]
        self.level = c

    def flat_until(self, t_end):
        while self.cursor < t_end:
            self.ev.append((self.cursor + 1, self.level))
            self.cursor += 300

    def shaped(self, bars):
        for (o, h, l, c) in bars:
            self._bar_events(self.cursor, o, h, l, c)
            self.cursor += 300

    def path(self, t_entry_bar, waypoints, t_end):
        """Entry bar se aage: waypoints [(sec_offset, bid)] -- har bar ke +1 par maujooda level."""
        wp = sorted((t_entry_bar + off, px) for off, px in waypoints)
        k = 0
        while self.cursor < t_end:
            self.ev.append((self.cursor + 1, self.level))
            while k < len(wp) and wp[k][0] < self.cursor + 300:
                self.ev.append(wp[k])
                self.level = wp[k][1]
                k += 1
            self.cursor += 300

    def finish(self):
        self.ev.sort()
        self._bars = {}
        for t, px in self.ev:
            b0 = int(t // 300) * 300
            b = self._bars.get(b0)
            if b is None:
                self._bars[b0] = [px, px, px, px, 1]
            else:
                b[1], b[2], b[3], b[4] = max(b[1], px), min(b[2], px), px, b[4] + 1
        self._closed = [(t, o, h, l, c, v) for t, o, h, l, c, v in self.hist] + \
                       [(t, b[0], b[1], b[2], b[3], b[4]) for t, b in sorted(self._bars.items())]

    # -- parhna --
    def closed_m5(self, now):
        return [b for b in self._closed if b[0] + 300 <= now]

    def forming_m5(self, now):
        b0 = int(now // 300) * 300
        pts = [px for t, px in self.ev if b0 <= t <= now]
        if not pts:
            return None
        return (b0, pts[0], max(pts), min(pts), pts[-1], len(pts))

    def spot(self, now):
        last = None
        for t, px in self.ev:
            if t > now:
                break
            last = px
        return last

    def ticks(self, t1, t2):
        return [(t, px) for t, px in self.ev if t1 <= t <= t2]


def agg(bars, sec, key):
    """M5 -> bara timeframe. key(t) = bucket shuru (utc)."""
    out = {}
    for t, o, h, l, c, v in bars:
        k = key(t)
        b = out.get(k)
        if b is None:
            out[k] = [o, h, l, c, v]
        else:
            b[1], b[2], b[3], b[4] = max(b[1], h), min(b[2], l), c, b[4] + v
    return [(k, b[0], b[1], b[2], b[3], b[4]) for k, b in sorted(out.items())]


# ====================================================================== A: NAKLI MT5
class FakeMT5(object):
    """Asal MetaTrader5 ka rawaiyya (IC Markets, server = NY+7). Shim se ALAG likha."""
    C = dict(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, TRADE_ACTION_DEAL=1, TRADE_ACTION_SLTP=6,
             ORDER_TIME_GTC=0, ORDER_FILLING_IOC=1, TRADE_RETCODE_DONE=10009, DEAL_ENTRY_IN=0,
             DEAL_ENTRY_OUT=1, DEAL_REASON_CLIENT=0, DEAL_REASON_EXPERT=3, DEAL_REASON_SL=4,
             DEAL_REASON_TP=5, DEAL_TYPE_BUY=0, DEAL_TYPE_SELL=1, SYMBOL_TRADE_MODE_FULL=4,
             TIMEFRAME_M5=5, TIMEFRAME_H1=16385, TIMEFRAME_H4=16388, COPY_TICKS_ALL=-1)
    TF = {5: 300, 16385: 3600, 16388: 14400}

    def __init__(self, vt, markets, eurusd=1.10, balance=100000.0, quote_eur=()):
        self.vt, self.m = vt, markets
        self.eurusd = eurusd
        self.balance = balance
        self.quote_eur = set(quote_eur)
        self.pos, self.deals, self.orders = {}, [], []
        self.next = 70000000
        self.log = []                         # (kaam, symbol, side, volume, sl, tp)
        self.lock = threading.RLock()
        self.connected = False

    class O(object):
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def _conv(self, sym):
        return self.eurusd if sym in self.quote_eur else 1.0

    def _px(self, sym):
        if sym == "EURUSD":
            return self.eurusd, self.eurusd + 0.00002
        b = self.m[sym].spot(self.vt.t)
        return (b, b + self.m[sym].spread) if b is not None else None

    def module(self):
        mod = types.ModuleType("MetaTrader5")
        mod.__dict__.update(self.C)
        for n in ("initialize", "shutdown", "last_error", "account_info", "symbol_info", "symbol_info_tick",
                  "positions_get", "history_deals_get", "history_orders_get", "copy_rates_from_pos",
                  "copy_ticks_range", "order_send"):
            setattr(mod, n, getattr(self, n))
        return mod

    def initialize(self, *a, **kw):
        self.connected = True
        return True

    def shutdown(self):
        self.connected = False

    def last_error(self):
        return (1, "Success")

    def account_info(self):
        if not self.connected:
            return None
        with self.lock:
            fl = sum(self._profit(p) for p in self.pos.values())
            return FakeMT5.O(balance=round(self.balance, 2), equity=round(self.balance + fl, 2), login=1)

    def symbol_info(self, name):
        if name == "EURUSD":
            return FakeMT5.O(name=name, digits=5, point=1e-05, trade_tick_size=1e-05, trade_tick_value=1.0,
                             volume_min=0.01, volume_max=100, volume_step=0.01, trade_mode=4)
        if name not in self.m:
            return None
        return FakeMT5.O(name=name, digits=2, point=0.01, trade_tick_size=0.01,
                         trade_tick_value=0.01 * self._conv(name), volume_min=0.1, volume_max=250.0,
                         volume_step=0.1, trade_mode=4)

    def symbol_info_tick(self, name):
        if name == "EURUSD":
            evs = [t for t, _ in self.m[next(iter(self.m))].ev if t <= self.vt.t]
            t = evs[-1] if evs else self.vt.t
            return FakeMT5.O(time=srv(t), bid=self.eurusd, ask=self.eurusd + 0.00002)
        if name not in self.m:
            return None
        mk = self.m[name]
        evs = [t for t, _ in mk.ev if t <= self.vt.t]
        p = self._px(name)
        if p is None:
            return None
        return FakeMT5.O(time=srv(evs[-1] if evs else self.vt.t), bid=p[0], ask=p[1])

    def _profit(self, p):
        bid, ask = self._px(p["symbol"])
        cur = bid if p["type"] == 0 else ask
        return round(((cur - p["price"]) if p["type"] == 0 else (p["price"] - cur)) * p["volume"] * self._conv(p["symbol"]), 2)

    def _pobj(self, p):
        bid, ask = self._px(p["symbol"])
        return FakeMT5.O(ticket=p["ticket"], time=p["time"], type=p["type"], magic=p["magic"], volume=p["volume"],
                         price_open=p["price"], sl=p["sl"], tp=p["tp"], symbol=p["symbol"],
                         price_current=bid if p["type"] == 0 else ask, profit=self._profit(p))

    def positions_get(self, symbol=None, ticket=None, group=None):
        if not self.connected:
            return None
        with self.lock:
            ps = [self._pobj(p) for p in sorted(self.pos.values(), key=lambda x: x["ticket"])]
        if symbol is not None:
            ps = [p for p in ps if p.symbol == symbol]
        if ticket is not None:
            ps = [p for p in ps if p.ticket == int(ticket)]
        return tuple(ps)

    def _deal(self, p, entry, price, reason, profit):
        self.next += 1
        self.deals.append(FakeMT5.O(ticket=self.next, order=self.next, time=srv(int(self.vt.t)), magic=p["magic"],
                                    position_id=p["ticket"], symbol=p["symbol"], entry=entry, reason=reason,
                                    type=(p["type"] if entry == 0 else 1 - p["type"]), volume=p["volume"],
                                    price=price, profit=profit, commission=0.0, swap=0.0))

    def _close(self, tk, price, reason):
        p = self.pos.pop(tk)
        pr = round(((price - p["price"]) if p["type"] == 0 else (p["price"] - price)) * p["volume"] * self._conv(p["symbol"]), 2)
        self.balance += pr
        self._deal(p, 1, price, reason, pr)
        self.log.append(("close", p["symbol"], reason, round(price, 2)))

    def on_spot(self, sym):
        with self.lock:
            bid, ask = self._px(sym)
            for tk, p in list(self.pos.items()):
                if p["symbol"] != sym:
                    continue
                buy = p["type"] == 0
                px = bid if buy else ask
                if p["sl"] and ((px <= p["sl"]) if buy else (px >= p["sl"])):
                    self._close(tk, p["sl"], 4)
                elif p["tp"] and ((px >= p["tp"]) if buy else (px <= p["tp"])):
                    self._close(tk, p["tp"], 5)

    def _in_range(self, x, a, b):
        return (a is None or x >= a) and (b is None or x <= b)

    @staticmethod
    def _num(dt):
        return calendar.timegm(dt.timetuple()) if dt is not None else None

    def history_deals_get(self, date_from=None, date_to=None, group=None, position=None, ticket=None):
        if not self.connected:
            return None
        with self.lock:
            ds = list(self.deals)
        if position is not None:
            return tuple(d for d in ds if d.position_id == int(position))
        a, b = self._num(date_from), self._num(date_to)
        return tuple(d for d in ds if self._in_range(d.time, a, b))

    def history_orders_get(self, date_from=None, date_to=None, group=None, position=None, ticket=None):
        with self.lock:
            if position is not None:                      # asal MT5: sirf us position ke orders
                return tuple(o for o in self.orders if o.position_id == int(position))
            a, b = self._num(date_from), self._num(date_to)
            return tuple(o for o in self.orders if self._in_range(o.time_setup, a, b))

    def order_send(self, rq):
        with self.lock:
            sym = rq.get("symbol")
            if rq["action"] == 6:
                p = self.pos.get(int(rq["position"]))
                if p is None:
                    return FakeMT5.O(retcode=10036, comment="closed", order=0, price=0.0)
                p["sl"], p["tp"] = float(rq["sl"]), float(rq["tp"])
                self.log.append(("sltp", p["symbol"], round(p["sl"], 2), round(p["tp"], 2)))
                return FakeMT5.O(retcode=10009, comment="done", order=p["ticket"], price=0.0)
            if rq.get("position"):
                tk = int(rq["position"])
                p = self.pos.get(tk)
                if p is None:
                    return FakeMT5.O(retcode=10036, comment="closed", order=0, price=0.0)
                bid, ask = self._px(p["symbol"])
                self._close(tk, bid if p["type"] == 0 else ask, 3)
                return FakeMT5.O(retcode=10009, comment="done", order=tk, price=0.0)
            bid, ask = self._px(sym)
            typ = int(rq["type"])
            price = ask if typ == 0 else bid
            self.next += 1
            tk = self.next
            # asal MT5 volume ko step par gol karta hai (127.80000000000001 -> 127.8)
            p = dict(ticket=tk, time=srv(int(self.vt.t)), type=typ, magic=int(rq["magic"]), volume=round(float(rq["volume"]), 8),
                     price=price, sl=float(rq["sl"]), tp=float(rq["tp"]), symbol=sym)
            self.pos[tk] = p
            self.orders.append(FakeMT5.O(ticket=tk, position_id=tk, magic=p["magic"], symbol=sym, sl=p["sl"],
                                         tp=p["tp"], time_setup=p["time"]))
            self._deal(p, 0, price, 3, 0.0)
            self.log.append(("open", sym, "BUY" if typ == 0 else "SELL", round(p["volume"], 2), round(p["sl"], 2),
                             round(p["tp"], 2)))
            return FakeMT5.O(retcode=10009, comment="done", order=tk, price=price)

    def copy_rates_from_pos(self, symbol, tf, start, count):
        if symbol not in self.m or tf not in self.TF:
            return None
        import numpy as np
        mk, sec, now = self.m[symbol], self.TF[tf], self.vt.t
        closed = mk.closed_m5(now)
        fm = mk.forming_m5(now)
        allb = closed + ([fm] if fm else [])
        if sec == 300:
            bars = [(srv(b[0]),) + tuple(b[1:]) for b in allb]
        else:                                       # MT5 bars SERVER waqt par jurti hain
            sb = [(srv(b[0]),) + tuple(b[1:]) for b in allb]
            bars = agg(sb, sec, lambda t: (t // sec) * sec)
        bars = bars[-int(count):]
        return np.array([(t, o, h, l, c, v, 100, 0) for t, o, h, l, c, v in bars],
                        dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                               ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])

    def copy_ticks_range(self, symbol, d_from, d_to, flags):
        import numpy as np
        if symbol not in self.m:
            return None
        a, b = calendar.timegm(d_from.timetuple()), calendar.timegm(d_to.timetuple())
        mk = self.m[symbol]
        rows = [(srv(t), px, px + mk.spread, 0.0, 0, srv(t) * 1000, 6, 0.0) for t, px in mk.ev
                if a <= srv(t) <= b]
        return np.array(rows, dtype=[("time", "<i8"), ("bid", "<f8"), ("ask", "<f8"), ("last", "<f8"),
                                     ("volume", "<u8"), ("time_msc", "<i8"), ("flags", "<u4"), ("volume_real", "<f8")])


# ====================================================================== B: NAKLI cTRADER SERVER
class FakeCT(object):
    """cTrader Open API (JSON/WebSocket) ka nakli server -- asal payload numbers. Shim se ALAG."""
    SYM = {"US30": 101, "DE40": 201, "EURUSD": 1}

    def __init__(self, vt, markets, eurusd=1.10, balance=100000.0, quote_eur=(), names=None):
        self.vt, self.m = vt, markets
        self.eurusd = eurusd
        self.balance = int(round(balance * 100))
        self.quote_eur = set(quote_eur)
        self.names = names or {}
        self.pos, self.deals, self.orders = {}, [], []
        self.next = 5000
        self.conns = []
        self.lock = threading.RLock()
        self.log = []
        self.token = "tok1"
        self.expired = False
        self.refreshes = 0
        self.scope = "SCOPE_TRADE"          # token ka permissionScope (None = field nahi bhejta)
        self.bars_from = 0                  # is utc waqt se PEHLE ki bars nahi (broker ka purana data khatam)
        self.flaky_days = set()             # 'YYYY-MM-DD': 1 din se bari request mein yeh din GAYAB (forum ki shikayat)
        # kharabiyan (sirf shim tests)
        self.order_reject = 0
        self.order_mode = "normal"
        self.amend_reject = 0
        self.slippage = 0.0
        self.reconcile_silent = 0
        self.orders_sent = 0

    def sid_of(self, sym):
        return self.SYM[sym]

    def sym_of(self, sid):
        return {v: k for k, v in self.SYM.items()}[sid]

    def bname(self, sym):
        return self.names.get(sym, sym)

    def _conv(self, sym):
        return self.eurusd if sym in self.quote_eur else 1.0

    def _px(self, sym):
        if sym == "EURUSD":
            return self.eurusd, self.eurusd + 0.00002
        b = self.m[sym].spot(self.vt.t)
        return (b, b + self.m[sym].spread) if b is not None else None

    def ms(self):
        return int(round(self.vt.t * 1000))

    # -- market --
    def push_spot(self, sym):
        with self.lock:
            p = self._px(sym)
            if p is None:
                return
            pay = {"ctidTraderAccountId": 9, "symbolId": self.sid_of(sym),
                   "bid": int(round(p[0] * 100000)), "ask": int(round(p[1] * 100000))}
            for ws in list(self.conns):
                try:
                    ws.send(json.dumps({"payloadType": 2131, "payload": pay}))
                except Exception:
                    pass
            if sym == "EURUSD":
                return
            for pid, x in list(self.pos.items()):
                if x["sym"] != sym:
                    continue
                buy = x["side"] == 1
                px = p[0] if buy else p[1]
                if x["sl"] and ((px <= x["sl"]) if buy else (px >= x["sl"])):
                    self._close(pid, x["sl"], ("sl", x["sl"]))
                elif x["tp"] and ((px >= x["tp"]) if buy else (px <= x["tp"])):
                    self._close(pid, x["tp"], ("tp", x["tp"]))

    def _order(self, x, otype, closing, extra=None):
        self.next += 1
        o = {"orderId": self.next, "orderType": otype, "orderStatus": 2, "closingOrder": closing,
             "positionId": x["id"], "utcLastUpdateTimestamp": self.ms(),
             "tradeData": {"symbolId": self.sid_of(x["sym"]), "volume": x["vol"], "tradeSide": x["side"],
                           "openTimestamp": self.ms(), "label": x["label"], "comment": x["comment"]}}
        o.update(extra or {})
        self.orders.append(o)
        return o

    def _close(self, pid, px, why):
        x = self.pos.pop(pid)
        if why[0] == "sl":
            o = self._order(x, 4, True, {"stopPrice": why[1]})
        elif why[0] == "tp":
            o = self._order(x, 4, True, {"limitPrice": why[1]})
        else:
            o = self._order(x, 1, True)
        units = x["vol"] / 100.0
        pnl = ((px - x["price"]) if x["side"] == 1 else (x["price"] - px)) * units * self._conv(x["sym"])
        cents = int(round(pnl * 100))
        self.balance += cents
        self.next += 1
        self.deals.append({"dealId": self.next, "orderId": o["orderId"], "positionId": pid, "volume": x["vol"],
                           "filledVolume": x["vol"], "symbolId": self.sid_of(x["sym"]), "createTimestamp": self.ms(),
                           "executionTimestamp": self.ms(), "executionPrice": px,
                           "tradeSide": 2 if x["side"] == 1 else 1, "dealStatus": 2, "moneyDigits": 2,
                           "closePositionDetail": {"entryPrice": x["price"], "grossProfit": cents, "swap": 0,
                                                   "commission": 0, "balance": self.balance, "moneyDigits": 2,
                                                   "closedVolume": x["vol"]}})
        self.log.append(("close", x["sym"], why[0], round(px, 2)))

    def ppos(self, x):
        d = {"positionId": x["id"], "positionStatus": 1, "swap": 0, "price": x["price"], "moneyDigits": 2,
             "tradeData": {"symbolId": self.sid_of(x["sym"]), "volume": x["vol"], "tradeSide": x["side"],
                           "openTimestamp": x["open_ms"], "label": x["label"], "comment": x["comment"]}}
        if x["sl"]:
            d["stopLoss"] = x["sl"]
        if x["tp"]:
            d["takeProfit"] = x["tp"]
        return d

    def add_pos(self, sym, side, vol, price, sl, tp, label, comment="x", open_ms=None):
        with self.lock:
            self.next += 1
            x = dict(id=self.next, sym=sym, side=side, vol=vol, price=price, sl=sl, tp=tp, label=label,
                     comment=comment, open_ms=open_ms if open_ms is not None else self.ms())
            self.pos[x["id"]] = x
            o = self._order(x, 1, False)
            self.next += 1
            self.deals.append({"dealId": self.next, "orderId": o["orderId"], "positionId": x["id"], "volume": vol,
                               "filledVolume": vol, "symbolId": self.sid_of(sym), "createTimestamp": x["open_ms"],
                               "executionTimestamp": x["open_ms"], "executionPrice": price, "tradeSide": side,
                               "dealStatus": 2, "moneyDigits": 2})
            return x

    # -- server --
    def start(self):
        from websockets.sync.server import serve
        self.srv = serve(self.handle, "127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "ws://127.0.0.1:%d" % self.srv.socket.getsockname()[1]
        return self.url

    def close(self):
        for ws in list(self.conns):
            try:
                ws.close()
            except Exception:
                pass
        try:
            self.srv.shutdown()
        except Exception:
            pass

    def drop_all(self):
        for ws in list(self.conns):
            try:
                ws.close()
            except Exception:
                pass

    def handle(self, ws):
        self.conns.append(ws)
        try:
            for raw in ws:
                m = json.loads(raw)
                with self.lock:
                    if self._one(ws, m) == "DROP":
                        ws.close()
                        return
        except Exception:
            pass
        finally:
            if ws in self.conns:
                self.conns.remove(ws)

    def _bars(self, sym, per, f, t):
        mk = self.m[sym]
        sec = {5: 300, 9: 3600, 10: 14400}[per]
        now = self.vt.t
        closed = mk.closed_m5(now)
        if sec != 300:                               # cTrader bars UTC par jurti hain
            closed = [b for b in agg(closed, sec, lambda x: (x // sec) * sec) if b[0] + sec <= now]
        out = []
        big = (t - f) > 86400 * 1000
        for (b0, o, h, l, c, v) in closed:
            if b0 < self.bars_from:
                continue
            if big and _RealDT.utcfromtimestamp(b0).strftime("%Y-%m-%d") in self.flaky_days:
                continue
            if f <= b0 * 1000 <= t:
                lo = int(round(l * 100000))
                out.append({"low": lo, "deltaOpen": int(round(o * 100000)) - lo, "deltaHigh": int(round(h * 100000)) - lo,
                            "deltaClose": int(round(c * 100000)) - lo, "volume": v, "utcTimestampInMinutes": int(b0 // 60)})
        return out

    def _one(self, ws, m):
        pt, cid, p = m["payloadType"], m.get("clientMsgId"), m.get("payload", {})

        def reply(rpt, pay):
            ws.send(json.dumps({"clientMsgId": cid, "payloadType": rpt, "payload": pay}))

        def err(code):
            reply(2142, {"errorCode": code, "description": "nakli"})

        if pt == 51:
            return
        if pt == 2100:
            return reply(2101, {}) if p.get("clientSecret") == "sec" else err("CH_CLIENT_AUTH_FAILURE")
        if pt == 2149:
            if p["accessToken"] != self.token or self.expired:
                return err("CH_ACCESS_TOKEN_INVALID")
            pay = {} if self.scope is None else {"permissionScope": self.scope}
            return reply(2150, dict(pay, ctidTraderAccount=[{"ctidTraderAccountId": 9, "isLive": False, "traderLogin": 1234567},
                                                      {"ctidTraderAccountId": 7, "isLive": True, "traderLogin": 5550}]))
        if pt == 2173:
            self.refreshes += 1
            self.expired, self.token = False, "tok%d" % (self.refreshes + 1)
            return reply(2174, {"accessToken": self.token, "expiresIn": 2628000, "refreshToken": "ref%d" % (self.refreshes + 1)})
        if pt == 2102:
            if p["accessToken"] != self.token:
                return err("CH_ACCESS_TOKEN_INVALID")
            return reply(2103, {"ctidTraderAccountId": 9})
        if pt == 2121:
            return reply(2122, {"trader": {"balance": self.balance, "moneyDigits": 2, "traderLogin": 1234567,
                                           "brokerName": "IC Markets", "depositAssetId": 1}})
        if pt == 2114:
            return reply(2115, {"symbol": [{"symbolId": sid, "symbolName": self.bname(nm), "baseAssetId": 2 if nm == "EURUSD" else 9,
                                            "quoteAssetId": 2 if nm in self.quote_eur else 1}
                                           for nm, sid in self.SYM.items() if nm == "EURUSD" or nm in self.m]})
        if pt == 2112:
            return reply(2113, {"asset": [{"assetId": 1, "name": "USD"}, {"assetId": 2, "name": "EUR"}, {"assetId": 9, "name": "IDX"}]})
        if pt == 2116:
            sid = p["symbolId"][0]
            fx = sid == 1
            return reply(2117, {"symbol": [{"symbolId": sid, "digits": 5 if fx else 2, "pipPosition": 4 if fx else 0,
                                            "lotSize": 10000000 if fx else 100, "minVolume": 1000 if fx else 10,
                                            "maxVolume": 100000000 if fx else 25000, "stepVolume": 1000 if fx else 10}]})
        if pt == 2137:
            sym = self.sym_of(p["symbolId"])
            bars = self._bars(sym, p["period"], p["fromTimestamp"], p["toTimestamp"])
            return reply(2138, {"trendbar": bars[::-1][:p.get("count", 5000)][::-1]})
        if pt == 2127:
            reply(2128, {})
            self.push_spot(self.sym_of(p["symbolId"][0]))
            return
        if pt == 2124:
            if self.reconcile_silent:
                self.reconcile_silent -= 1
                return
            return reply(2125, {"position": [self.ppos(x) for x in sorted(self.pos.values(), key=lambda q: q["id"])]})
        if pt == 2187:
            u = []
            for x in self.pos.values():
                b, a = self._px(x["sym"])
                px = b if x["side"] == 1 else a
                pnl = ((px - x["price"]) if x["side"] == 1 else (x["price"] - px)) * x["vol"] / 100.0 * self._conv(x["sym"])
                u.append({"positionId": x["id"], "grossUnrealizedPnL": int(round(round(pnl, 2) * 100)), "netUnrealizedPnL": 0})
            return reply(2188, {"positionUnrealizedPnL": u, "moneyDigits": 2})
        if pt == 2106:
            self.orders_sent += 1
            if self.order_reject:
                self.order_reject -= 1
                return reply(2132, {"errorCode": "MARKET_CLOSED", "description": "nakli"})
            if self.order_mode == "silent_nofill":
                return
            sym = self.sym_of(p["symbolId"])
            side = p["tradeSide"]
            b, a = self._px(sym)
            fill = round((a + self.slippage) if side == 1 else (b - self.slippage), 2)
            rs, rt = p.get("relativeStopLoss", 0) / 100000.0, p.get("relativeTakeProfit", 0) / 100000.0
            sl = round((fill - rs) if side == 1 else (fill + rs), 2) if rs else 0.0
            tp = round((fill + rt) if side == 1 else (fill - rt), 2) if rt else 0.0
            if self.order_mode == "no_sl":
                sl = 0.0
            x = self.add_pos(sym, side, p["volume"], fill, sl, tp, p.get("label", ""), p.get("comment", ""))
            self.log.append(("open", sym, "BUY" if side == 1 else "SELL", round(p["volume"] / 100.0, 2)))
            if self.order_mode == "silent_fill":
                return
            if self.order_mode == "drop_after_fill":
                return "DROP"
            return reply(2126, {"executionType": 3, "position": self.ppos(x)})
        if pt == 2110:
            if self.amend_reject:
                self.amend_reject -= 1
                return reply(2132, {"errorCode": "TRADING_BAD_STOPS"})
            x = self.pos.get(p["positionId"])
            if x is None:
                return reply(2132, {"errorCode": "POSITION_NOT_FOUND"})
            x["sl"] = round(p.get("stopLoss", 0.0), 2)
            x["tp"] = round(p.get("takeProfit", 0.0), 2)
            self.log.append(("sltp", x["sym"], x["sl"], x["tp"]))
            return reply(2126, {"executionType": 4, "position": self.ppos(x)})
        if pt == 2111:
            x = self.pos.get(p["positionId"])
            if x is None:
                return reply(2132, {"errorCode": "POSITION_NOT_FOUND"})
            b, a = self._px(x["sym"])
            self._close(x["id"], b if x["side"] == 1 else a, ("market", 0))
            return reply(2126, {"executionType": 3})
        if pt == 2179:
            return reply(2180, {"deal": [d for d in self.deals if d["positionId"] == p["positionId"]], "hasMore": False})
        if pt == 2133:
            f, t = p.get("fromTimestamp", 0), p.get("toTimestamp", 2 ** 62)
            return reply(2134, {"deal": [d for d in self.deals if f <= d["executionTimestamp"] <= t], "hasMore": False})
        if pt == 2175:
            f, t = p.get("fromTimestamp", 0), p.get("toTimestamp", 2 ** 62)
            return reply(2176, {"order": [o for o in self.orders if f <= o["utcLastUpdateTimestamp"] <= t], "hasMore": False})
        if pt == 2145:
            sym = self.sym_of(p["symbolId"])
            mk = self.m[sym]
            add = mk.spread if p["type"] == 2 else 0.0
            ticks = [(int(t * 1000), int(round((px + add) * 100000))) for t, px in mk.ticks(p["fromTimestamp"] / 1000.0,
                                                                                            p["toTimestamp"] / 1000.0)]
            ticks = ticks[::-1]                       # nayi pehle
            enc, prev = [], None
            for ts, px in ticks:
                if prev is None:
                    enc.append({"timestamp": ts, "tick": px})
                else:
                    enc.append({"timestamp": ts - prev[0], "tick": px - prev[1]})
                prev = (ts, px)
            return reply(2146, {"tickData": enc, "hasMore": False})
        return err("UNKNOWN")


# ====================================================================== bot.py ko chalana
def _main_block():
    src = io.open(BOT_FILE, encoding="utf-8").read()
    i = src.index('if __name__ == "__main__":')
    return textwrap.dedent(src[i:].split("\n", 1)[1])


class Run(object):
    """Aik bot.py process ki nakal (aik folder, aik symbol)."""

    def __init__(self, route, sym, cfg, vt, broker, folder=None, shim_kw=None):
        self.route, self.sym, self.vt, self.broker = route, sym, vt, broker
        self.folder = folder or tempfile.mkdtemp(prefix="sim%s_%s_" % (route, sym))
        self.lines, self.shim_lines = [], []
        self.req = FakeReq()
        assert md5_8(BOT_FILE) in KNOWN_BOT, "bot.py ka md5 anjaan: %s" % md5_8(BOT_FILE)
        shutil.copy(BOT_FILE, os.path.join(self.folder, "bot.py"))
        shutil.copy(os.path.join(HERE, "vwap_strategy_adapter.py"), os.path.join(self.folder, "strategy.py"))
        if not os.path.exists(os.path.join(self.folder, "config.json")):
            json.dump(cfg, open(os.path.join(self.folder, "config.json"), "w"), indent=1)
        self.cfg = cfg
        self.shim = None
        if route == "A":
            self.mt5 = broker.module()
        else:
            import mt5_ctrader as S
            keys = os.path.join(self.folder, "..", "ctrader_keys.json") if False else os.path.join(self.folder, "ctrader_keys.json")
            if not os.path.exists(keys):
                json.dump({"client_id": "id", "client_secret": "sec", "access_token": "tok1", "refresh_token": "ref1",
                           "demo": True, "trader_login": 1234567}, open(keys, "w"))
            self.keys = keys
            kw = dict(shim_kw or {})

            def factory():
                t = S._LockedTrader(keys, allow_refresh=True, url=broker.url, timeout=kw.get("timeout", 3),
                                    log=self.shim_lines.append)
                t.clock = vt.now
                return t
            self.shim = S.Shim(folder=self.folder, clock=vt.now, link_factory=factory, log=self.shim_lines.append)
            mod = types.ModuleType("MetaTrader5")
            for k, v in S.__dict__.items():
                if k.isupper():
                    setattr(mod, k, v)
            for n in ("initialize", "shutdown", "last_error", "account_info", "symbol_info", "symbol_info_tick",
                      "positions_get", "history_deals_get", "history_orders_get", "copy_rates_from_pos",
                      "copy_ticks_range", "order_send", "symbol_select", "positions_total"):
                setattr(mod, n, getattr(self.shim, n))
            self.mt5 = mod

    def load(self):
        import vwap_strategy_adapter as AD
        sys.modules["MetaTrader5"] = self.mt5
        sys.modules["strategy"] = AD
        name = "bot_%s_%s_%d" % (self.route, self.sym, id(self))
        spec = importlib.util.spec_from_file_location(name, os.path.join(self.folder, "bot.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        vt = self.vt
        mod.time = TimeProxy(vt)
        mod.datetime = make_dt(vt)
        mod.req = self.req
        mod.threading = make_threading(vt)
        lines = self.lines

        def _print(*a, **kw):
            lines.append(" ".join(str(x) for x in a))
        mod.print = _print
        mod.app.run = lambda *a, **kw: None
        self.mod = mod
        return mod

    def start(self):
        mod = self.mod
        code = compile(_main_block(), "bot.py:__main__", "exec")
        th = mod.threading.Thread(target=lambda: exec(code, mod.__dict__), name="bot-main", daemon=True)
        th.start()
        return th


class Sim(object):
    """Aik ya zyada Run ek nakli ghadi par; `time` module ka proxy sirf chalne ke dauran."""

    def __init__(self, vt):
        self.vt = vt
        self.runs = []

    def add(self, run):
        self.runs.append(run)
        return run

    def go(self, t_end, progress=None):
        import zipfile, fpdf  # noqa: pehle se import -- chalne ke dauran proxy na pakde
        real_time = sys.modules["time"]
        cwd = os.getcwd()
        try:
            sys.modules["time"] = TimeProxy(self.vt)
            if len(self.runs) == 1:
                os.chdir(self.runs[0].folder)
            for r in self.runs:
                r.start()
            self.vt.run_until(t_end, progress)
        finally:
            sys.modules["time"] = real_time
            os.chdir(cwd)

    def stop(self):
        self.vt.stop()
        _real_sleep(0.2)


def read(folder, name):
    p = os.path.join(folder, name)
    return io.open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""
