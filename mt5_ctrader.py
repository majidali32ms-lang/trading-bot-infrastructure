# -*- coding: utf-8 -*-
"""
mt5_ctrader.py -- 6 Oct 2026 (HANDOVER 260). "NAKLI MT5": bot.py (bd901c0f) ko BINA BADLE
cTrader par chalata hai.

VPS par yeh file har VWAP symbol folder mein `MetaTrader5.py` naam se rakhi jati hai
(C:\\trading-bot-vwap\\DE40\\MetaTrader5.py). bot.py `import MetaTrader5 as mt5` karta hai --
script ka folder sys.path mein sab se pehle hota hai, is liye asal MT5 package ki jagah
YEH milta hai. bot.py ka aik byte nahi badalta; us ke saare features (Telegram, reports,
webhook, BE, guard, MAE, shadows ...) waise hi chalte hain.

Jo bot.py MT5 se maangta hai, wahi shakl yahan cTrader se bani:
  initialize / account_info / last_error / symbol_info / symbol_info_tick / positions_get /
  history_deals_get / history_orders_get / copy_rates_from_pos / copy_ticks_range / order_send
WAQT: bot.py MT5 ke "server" waqt (NY + 7 ghante) par chalta hai -- yahan bhi wahi.
MAGIC: cTrader mein magic nahi -> label (VWAP-DE40). Apne label ki position = config ka magic.
QAIDE jo cTrader ki wajah se yahan hain (bot_vwap.py / ctrader_trade.py se):
  * MARKET order par absolute SL/TP nahi -> relative bhejo, fill ke baad bot ki ASAL qeemat
    par amend; SL bilkul na lage -> position FORAN band, 5 min naya order nahi.
  * DE40 EUR mein -> tick_value EURUSD se USD.
  * Token refresh: lock file -- do VWAP process aik token; jo pehle refresh kare, doosra
    file se naya token utha leta hai (dobara refresh NAHI).
  * Aik folder = aik process: `shim_running.lock` -- doosri copy kabhi connect nahi hoti.
Config: bot ki config.json ki "ctrader" key (bot.py use nazarandaz karta hai).
"""
import calendar
import io
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

try:
    import numpy as _np
except Exception:                     # VPS par numpy hai (asal MT5 package ki zaroorat)
    _np = None

VERSION = "mt5_ctrader v1 -- 6 Oct 2026"

# ---------------------------------------------------------------- MT5 constants (asal qeematein)
ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
TRADE_ACTION_DEAL, TRADE_ACTION_SLTP = 1, 6
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
TRADE_RETCODE_REJECT = 10006
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_ERROR = 10011
TRADE_RETCODE_INVALID = 10013
TRADE_RETCODE_INVALID_VOLUME = 10014
TRADE_RETCODE_INVALID_STOPS = 10016
TRADE_RETCODE_MARKET_CLOSED = 10018
TRADE_RETCODE_NO_MONEY = 10019
TRADE_RETCODE_POSITION_CLOSED = 10036
DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
DEAL_REASON_CLIENT, DEAL_REASON_MOBILE, DEAL_REASON_WEB, DEAL_REASON_EXPERT = 0, 1, 2, 3
DEAL_REASON_SL, DEAL_REASON_TP, DEAL_REASON_SO = 4, 5, 6
SYMBOL_TRADE_MODE_DISABLED, SYMBOL_TRADE_MODE_CLOSEONLY, SYMBOL_TRADE_MODE_FULL = 0, 3, 4
TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 5, 15, 30
TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1 = 16385, 16388, 16408
COPY_TICKS_ALL, COPY_TICKS_INFO, COPY_TICKS_TRADE = -1, 1, 2

_CT_PERIOD = {TIMEFRAME_M1: (1, 60), TIMEFRAME_M5: (5, 300), TIMEFRAME_M15: (7, 900),
              TIMEFRAME_M30: (8, 1800), TIMEFRAME_H1: (9, 3600), TIMEFRAME_H4: (10, 14400),
              TIMEFRAME_D1: (12, 86400)}
_ERR_RETCODE = {"MARKET_CLOSED": TRADE_RETCODE_MARKET_CLOSED, "NOT_ENOUGH_MONEY": TRADE_RETCODE_NO_MONEY,
                "TRADING_BAD_VOLUME": TRADE_RETCODE_INVALID_VOLUME, "TRADING_BAD_STOPS": TRADE_RETCODE_INVALID_STOPS,
                "POSITION_NOT_FOUND": TRADE_RETCODE_POSITION_CLOSED}
SL_BLOCK_SEC = 300
SRV_FROM_NY = 7 * 3600

RATES_DTYPE = [("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
               ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")]
TICKS_DTYPE = [("time", "<i8"), ("bid", "<f8"), ("ask", "<f8"), ("last", "<f8"), ("volume", "<u8"),
               ("time_msc", "<i8"), ("flags", "<u4"), ("volume_real", "<f8")]


class _Obj(object):
    """MT5 ke namedtuple jaisa: attributes + _asdict()."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def _asdict(self):
        return dict(self.__dict__)

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join("%s=%r" % kv for kv in sorted(self.__dict__.items())))


class AccountInfo(_Obj):
    pass


class SymbolInfo(_Obj):
    pass


class Tick(_Obj):
    pass


class TradePosition(_Obj):
    pass


class TradeDeal(_Obj):
    pass


class TradeOrder(_Obj):
    pass


class OrderSendResult(_Obj):
    pass


def _rows(dtype, rows):
    if _np is not None:
        return _np.array(rows, dtype=dtype)
    names = [n for n, _ in dtype]
    return [dict(zip(names, r)) for r in rows]


class _FileLock(object):
    """Aik process ka taala (Windows: msvcrt, warna fcntl). Process mare to OS khud chhorta hai."""

    def __init__(self, path):
        self.path = path
        self.fh = None

    def acquire(self, blocking=False, timeout=10.0):
        fh = open(self.path, "a+")
        t0 = time.monotonic()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fh = fh
                return True
            except OSError:
                if not blocking or time.monotonic() - t0 > timeout:
                    fh.close()
                    return False
                time.sleep(0.05)

    def release(self):
        fh, self.fh = self.fh, None
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def _ny_offset(utc_epoch):
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(utc_epoch, ZoneInfo("America/New_York")).utcoffset().total_seconds()


def srv_from_utc(utc_epoch):
    """Asal UTC -> MT5 'server' epoch (NY + 7h, DST ke saath)."""
    return int(utc_epoch + _ny_offset(utc_epoch) + SRV_FROM_NY)


def utc_from_srv(srv_epoch):
    u = srv_epoch - SRV_FROM_NY + 4 * 3600
    for _ in range(3):
        u = srv_epoch - SRV_FROM_NY - _ny_offset(u)
    return u


def _dt_to_srv(dt):
    """MT5 ki tarah: naive datetime ke HINDSE server waqt hain; tz wali UTC-numbers bhi wahi."""
    if isinstance(dt, (int, float)):
        return int(dt)
    return calendar.timegm(dt.timetuple())


class Shim(object):
    def __init__(self, folder=None, clock=None, link_factory=None, log=None, sleep=None):
        self.folder = folder or _default_folder()
        self.clock = clock or time.time
        self._sleep = sleep or time.sleep
        self._log = log
        self.link_factory = link_factory
        self.link = None
        self.cfg = {}
        self.ccfg = {}
        self.err = (1, "Success")
        self.sym = None                     # config ka naam (DE40)
        self.sid = None
        self.broker_name = None
        self.spec = {}
        self.conv = None                    # (sid, invert) ya None
        self.eurusd_sid = None
        self.label = ""
        self.magic = 0
        self.point = 0.01
        self.lot_size = 100
        self.names = {}                     # broker naam -> sid
        self.id_name = {}                   # sid -> naam (apna symbol = config naam)
        self.spot_t = {}                    # sid -> clock waqt (aakhri spot)
        self.book = {}                      # pid -> {sl, tp, time, volume, side, comment, by_us}
        self.sl_block_until = 0.0
        self.last_connect_try = 0.0
        self.order_cache = {}
        self._label_pids = set()
        self.run_lock = None
        self.lock = threading.RLock()
        self.book_path = os.path.join(self.folder, "shim_orders.json")
        self._load_book()

    # ---------- log ----------
    def log(self, msg):
        line = "[SHIM] " + msg
        if self._log:
            self._log(line)
        else:
            print("[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), line), flush=True)

    # ---------- book (apni positions ki asal SL/TP, kis ne band ki) ----------
    def _load_book(self):
        try:
            with io.open(self.book_path, encoding="utf-8") as fh:
                self.book = {int(k): v for k, v in json.load(fh).items()}
        except FileNotFoundError:
            self.book = {}
        except Exception as e:
            self.book = {}
            self.log("shim_orders.json parh nahi saka: %s" % e)

    def _save_book(self):
        try:
            tmp = self.book_path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as fh:
                json.dump({str(k): v for k, v in self.book.items()}, fh)
            os.replace(tmp, self.book_path)
        except Exception as e:
            self.log("shim_orders.json likh nahi saka: %s" % e)

    # ---------- connection ----------
    def _read_cfg(self):
        with io.open(os.path.join(self.folder, "config.json"), encoding="utf-8-sig") as fh:
            self.cfg = json.load(fh)
        self.ccfg = self.cfg.get("ctrader") or {}
        self.sym = self.cfg.get("symbol", "")
        self.magic = int(self.cfg.get("magic_number", 0))
        self.label = self.ccfg.get("label") or ("VWAP-" + self.sym)
        self.point = float(self.ccfg.get("point", 0.01))

    def _make_link(self):
        if self.link_factory:
            return self.link_factory()
        import ctrader_trade as T
        keys = self.ccfg.get("keys_file", os.path.join("..", "ctrader_keys.json"))
        if not os.path.isabs(keys):
            keys = os.path.join(self.folder, keys)
        url = self.ccfg.get("url")
        if url and not (url.startswith("ws://127.0.0.1:") or url.startswith("ws://localhost:")):
            raise RuntimeError("ctrader.url sirf local nakli server ke liye (tests) -- %r RADD" % url)
        return _LockedTrader(keys, allow_refresh=True, log=self.log, url=url or None)

    def initialize(self, path=None, login=None, password=None, server=None, **kw):
        with self.lock:
            if self.run_lock is None:
                lk = _FileLock(os.path.join(self.folder, "shim_running.lock"))
                if not lk.acquire():
                    self.err = (-6, "doosra bot isi folder mein pehle se chal raha (shim_running.lock)")
                    self.log(self.err[1] + " -- yeh copy KABHI connect nahi hogi")
                    return False
                self.run_lock = lk
            try:
                self._read_cfg()
                if self.link is not None:
                    try:
                        self.link.close()
                    except Exception:
                        pass
                    self.link = None
                link = self._make_link()
                if hasattr(link, "clock"):
                    link.clock = self.clock
                link.connect()
                link.trader()
                self.link = link
                self._setup_symbols()
                self.err = (1, "Success")
                self.log("%s | cTrader jura | %s -> '%s' | label %s | magic %d"
                         % (VERSION, self.sym, self.broker_name, self.label, self.magic))
                return True
            except Exception as e:
                self.err = (-10004, "cTrader connect nakaam: %s: %s" % (type(e).__name__, e))
                self.log(self.err[1])
                return False

    def _setup_symbols(self):
        link = self.link
        names = link.light_symbols(refresh=True)
        self.names = {n: int(s.get("symbolId")) for n, s in names.items()}
        aliases = self.ccfg.get("broker_names") or [self.sym]
        nm, sid = link.find_symbol(aliases)
        if not sid:
            raise RuntimeError("broker par %s nahi mila (%s)" % (self.sym, "/".join(aliases)))
        self.broker_name, self.sid = nm, sid
        self.spec = link.symbol_spec(sid)
        self.lot_size = int(self.spec.get("lotSize") or 100)
        self.id_name = {v: k for k, v in self.names.items()}
        self.id_name[sid] = self.sym
        q, d, cn, cid, inv = link.quote_conversion(nm)
        self.conv = (cid, inv) if cn else None
        self.eurusd_sid = self.names.get("EURUSD")
        subs = {sid}
        if cid:
            subs.add(cid)
        if self.eurusd_sid:
            subs.add(self.eurusd_sid)
        for s in sorted(subs):
            link.subscribe(s)

    def _alive(self):
        return self.link is not None and self.link.alive

    def _ensure(self):
        """MT5 terminal ki tarah: raabta toota ho to khud jurne ki koshish (har 10 s mein aik)."""
        if self._alive():
            return True
        now = self.clock()
        if 0 <= now - self.last_connect_try < 10:
            return False
        self.last_connect_try = now
        self.log("raabta nahi -- dobara jor raha")
        return self.initialize()

    def shutdown(self):
        with self.lock:
            if self.link:
                self.link.close()
            self.link = None

    def last_error(self):
        return self.err

    # ---------- qeemat / waqt ----------
    def _px(self, sid):
        s = self.link.spots.get(sid) if self.link else None
        if not s or s[0] is None or s[1] is None:
            return None
        return s[0], s[1], s[2]

    def _conv_rate(self):
        if not self.conv:
            return 1.0
        cid, inv = self.conv
        p = self._px(cid)
        if not p:
            return None
        return (1.0 / p[1]) if inv else p[0]

    def _name_to_sid(self, name):
        if name == self.sym:
            return self.sid
        return self.names.get(name)

    def _sid_name(self, sid):
        return self.id_name.get(sid, str(sid))

    # ---------- account ----------
    def account_info(self):
        with self.lock:
            if not self._alive():
                return None
            try:
                t = self.link.trader()
                self._token_watch()
                eq = self.link.equity(t["balance"])
                return AccountInfo(login=t["login"], balance=round(t["balance"], 2), equity=round(eq, 2),
                                   profit=round(eq - t["balance"], 2), currency="USD", server="cTrader",
                                   company=t.get("broker", ""), trade_allowed=True, margin_free=eq)
            except Exception as e:
                self.err = (-10004, "account_info: %s" % e)
                return None

    def _token_watch(self):
        try:
            exp = self.link.token_expires_at()
            if exp and exp - time.time() < 3 * 86400:
                self.link.refresh_token()
        except Exception as e:
            self.log("token refresh nakaam: %s" % e)

    # ---------- symbols ----------
    def symbol_info(self, name):
        with self.lock:
            if not self._ensure():
                return None
            sid = self._name_to_sid(name)
            if not sid:
                self.err = (-1, "symbol %s nahi" % name)
                return None
            if sid == self.sid:
                spec, lot = self.spec, self.lot_size
                conv = self._conv_rate()
                point = self.point
            else:
                spec = self.link.symbol_spec(sid)
                lot = int(spec.get("lotSize") or 100)
                conv, point = 1.0, 10.0 ** -(spec.get("digits") or 5)
            units_per_lot = lot / 100.0
            p = self._px(sid)
            return SymbolInfo(name=name, digits=int(spec.get("digits") or 2), point=point,
                              trade_tick_size=point,
                              trade_tick_value=(point * units_per_lot * conv) if conv else 0.0,
                              volume_min=(spec.get("minVolume") or 1) / float(lot),
                              volume_max=(spec.get("maxVolume") or lot * 1000) / float(lot),
                              volume_step=(spec.get("stepVolume") or 1) / float(lot),
                              trade_contract_size=units_per_lot, trade_mode=SYMBOL_TRADE_MODE_FULL,
                              bid=p[0] if p else 0.0, ask=p[1] if p else 0.0, visible=True)

    def symbol_info_tick(self, name):
        with self.lock:
            if not self._ensure():
                return None
            sid = self._name_to_sid(name)
            p = self._px(sid) if sid else None
            if not p:
                return None
            srv = srv_from_utc(p[2])
            return Tick(time=srv, bid=p[0], ask=p[1], last=0.0, volume=0, time_msc=srv * 1000, flags=6,
                        volume_real=0.0)

    def symbol_select(self, name, enable=True):
        return True

    # ---------- positions ----------
    def _positions_raw(self):
        """Sab khuli positions MT5 shakl mein. Jawab na aaye -> exception."""
        out = []
        conv = self._conv_rate() or 0.0
        for p in self.link.positions():
            ours = p.label == self.label and p.symbol_id == self.sid
            px = self._px(p.symbol_id)
            cur = (px[0] if p.side == "BUY" else px[1]) if px else p.price
            units = p.volume / 100.0
            c = conv if p.symbol_id == self.sid else 1.0
            prof = ((cur - p.price) if p.side == "BUY" else (p.price - cur)) * units * c
            lot = self.lot_size if p.symbol_id == self.sid else 100
            out.append(TradePosition(
                ticket=p.id, identifier=p.id, time=srv_from_utc(p.open_ms / 1000.0) if p.open_ms else 0,
                time_msc=0, type=POSITION_TYPE_BUY if p.side == "BUY" else POSITION_TYPE_SELL,
                magic=self.magic if ours else 0, volume=p.volume / float(lot), price_open=p.price,
                sl=p.sl or 0.0, tp=p.tp or 0.0, price_current=cur, swap=0.0, profit=round(prof, 2),
                symbol=self._sid_name(p.symbol_id), comment=p.comment, reason=DEAL_REASON_EXPERT))
            if ours and p.id in self.book:
                self.book[p.id]["last_sl"], self.book[p.id]["last_tp"] = p.sl, p.tp
        return out

    def positions_get(self, symbol=None, ticket=None, group=None):
        with self.lock:
            if not self._ensure():
                self.err = (-10004, "cTrader raabta nahi")
                return None
            try:
                ps = self._positions_raw()
            except Exception as e:
                self.err = (-10004, "positions: %s" % e)
                return None
            if symbol is not None:
                ps = [p for p in ps if p.symbol == symbol]
            if ticket is not None:
                ps = [p for p in ps if p.ticket == int(ticket)]
            return tuple(ps)

    def positions_total(self):
        r = self.positions_get()
        return len(r) if r is not None else None

    # ---------- deals / orders ----------
    def _magic_of(self, pid, sid):
        if sid != self.sid:
            return 0
        if pid in self.book or pid in self._label_pids:
            return self.magic
        return 0

    def _learn_labels(self, raw):
        """Book mein na hon to khulne wali order ke label se pehchano (restart / purani positions)."""
        for d in raw:
            pid, sid = int(d.get("positionId")), int(d.get("symbolId"))
            if sid != self.sid or pid in self.book or pid in self._label_pids or d.get("closePositionDetail"):
                continue
            o = self._order(int(d.get("orderId") or 0), int(d.get("executionTimestamp") or 0))
            if o is not None and (o.get("tradeData") or {}).get("label") == self.label:
                self._label_pids.add(pid)

    def _reason(self, d, pid):
        b = self.book.get(pid) or {}
        if b.get("by_us"):
            return DEAL_REASON_EXPERT
        oid = int(d.get("orderId") or 0)
        o = self._order(oid, int(d.get("executionTimestamp") or 0))
        px = float(d.get("executionPrice") or 0.0)
        if o is not None:
            if o.get("isStopOut"):
                return DEAL_REASON_SO
            if int(o.get("orderType") or 0) == 4:          # STOP_LOSS_TAKE_PROFIT
                if o.get("limitPrice") is not None and o.get("stopPrice") is None:
                    return DEAL_REASON_TP
                if o.get("stopPrice") is not None and o.get("limitPrice") is None:
                    return DEAL_REASON_SL
                return self._near(px, b)
            return DEAL_REASON_CLIENT                    # haath se band (bot ne nahi)
        return self._near(px, b)

    @staticmethod
    def _near(px, b):
        sl, tp = b.get("last_sl") or b.get("sl") or 0.0, b.get("last_tp") or b.get("tp") or 0.0
        if tp and (not sl or abs(px - tp) < abs(px - sl)):
            return DEAL_REASON_TP
        if sl:
            return DEAL_REASON_SL
        return DEAL_REASON_CLIENT

    def _order(self, oid, ts_ms):
        if not oid:
            return None
        if oid in self.order_cache:
            return self.order_cache[oid]
        try:
            p = self.link.request(2175, {"ctidTraderAccountId": self.link.account_id,
                                         "fromTimestamp": ts_ms - 86400000, "toTimestamp": ts_ms + 60000}, 2176)
            for o in p.get("order") or []:
                self.order_cache[int(o.get("orderId"))] = o
        except Exception as e:
            self.log("order list nahi mili: %s" % e)
            return None
        return self.order_cache.get(oid)

    def _deal_obj(self, d):
        pid = int(d.get("positionId"))
        sid = int(d.get("symbolId"))
        cpd = d.get("closePositionDetail")
        lot = self.lot_size if sid == self.sid else 100
        md = int(d.get("moneyDigits") or (cpd or {}).get("moneyDigits") or 2)
        prof = int(cpd.get("grossProfit")) / (10.0 ** md) if cpd else 0.0
        vol = int((cpd or {}).get("closedVolume") or d.get("filledVolume") or d.get("volume") or 0)
        return TradeDeal(
            ticket=int(d.get("dealId")), order=int(d.get("orderId") or 0),
            time=srv_from_utc(int(d.get("executionTimestamp")) / 1000.0), time_msc=0,
            type=DEAL_TYPE_BUY if int(d.get("tradeSide")) == 1 else DEAL_TYPE_SELL,
            entry=DEAL_ENTRY_OUT if cpd else DEAL_ENTRY_IN, magic=self._magic_of(pid, sid),
            position_id=pid, reason=self._reason(d, pid) if cpd else DEAL_REASON_EXPERT,
            volume=vol / float(lot), price=float(d.get("executionPrice") or 0.0),
            commission=int(d.get("commission") or 0) / (10.0 ** md), swap=0.0, profit=round(prof, 2),
            fee=0.0, symbol=self._sid_name(sid), comment="", external_id="")

    def history_deals_get(self, date_from=None, date_to=None, group=None, position=None, ticket=None):
        with self.lock:
            if not self._ensure():
                return None
            try:
                if position is not None:
                    raw = self.link.deals_of(int(position))
                else:
                    f = utc_from_srv(_dt_to_srv(date_from)) * 1000
                    t = utc_from_srv(_dt_to_srv(date_to)) * 1000
                    p = self.link.request(2133, {"ctidTraderAccountId": self.link.account_id,
                                                 "fromTimestamp": int(f), "toTimestamp": int(t),
                                                 "maxRows": 5000}, 2134)
                    raw = p.get("deal") or []
                raw = [d for d in raw if int(d.get("dealStatus") or 0) in (2, 3)]
                self._learn_labels(raw)
                out = [self._deal_obj(d) for d in raw]
            except Exception as e:
                self.err = (-10004, "deals: %s" % e)
                return None
            out.sort(key=lambda x: (x.time, x.ticket))
            return tuple(out)

    def history_orders_get(self, date_from=None, date_to=None, group=None, position=None, ticket=None):
        """Apni positions ki khulne wali order (asal SL/TP ke saath) -- shim_orders.json se."""
        with self.lock:
            out = []
            lo = _dt_to_srv(date_from) if date_from is not None else None
            hi = _dt_to_srv(date_to) if date_to is not None else None
            for pid, b in sorted(self.book.items()):
                if position is not None and pid != int(position):
                    continue
                if lo is not None and not (lo <= b["time"] <= hi):
                    continue
                out.append(TradeOrder(ticket=pid, position_id=pid, magic=self.magic, symbol=self.sym,
                                      sl=b.get("sl") or 0.0, tp=b.get("tp") or 0.0, time_setup=b["time"],
                                      type=ORDER_TYPE_BUY if b.get("side") == "BUY" else ORDER_TYPE_SELL,
                                      volume_initial=b.get("volume", 0.0), price_open=b.get("price", 0.0),
                                      comment=b.get("comment", "")))
            return tuple(out)

    # ---------- bars / ticks ----------
    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        with self.lock:
            if not self._ensure():
                return None
            sid = self._name_to_sid(symbol)
            if not sid or timeframe not in _CT_PERIOD:
                self.err = (-2, "symbol / timeframe nahi")
                return None
            per, sec = _CT_PERIOD[timeframe]
            now = self.clock()
            need = int(count) + int(start_pos) + 1
            try:
                bars = self._bars_span(sid, per, need, now, (need + 5) * sec)
                if len(bars) < need:
                    bars = self._bars_span(sid, per, need, now, max(4 * 86400, 3 * (need + 5) * sec))
            except Exception as e:
                self.err = (-10004, "bars: %s" % e)
                return None
            cur0 = int(now // sec) * sec
            rows = [b for b in bars if b["time"] <= cur0]
            px = self._px(sid)
            if px and (not rows or rows[-1]["time"] < cur0):
                # MT5 jaisa: maujooda (bani hui) bar hamesha aakhri -- bot.py usay khud girata hai
                rows.append(dict(time=cur0, open=px[0], high=px[0], low=px[0], close=px[0], tick_volume=1))
            if start_pos:
                rows = rows[:-int(start_pos)] if int(start_pos) < len(rows) else []
            rows = rows[-int(count):]
            spread = 0
            if px:
                spread = int(round((px[1] - px[0]) / self.point))
            return _rows(RATES_DTYPE, [(srv_from_utc(b["time"]), b["open"], b["high"], b["low"], b["close"],
                                        int(b.get("tick_volume") or 0), spread, 0) for b in rows])

    def _bars_span(self, sid, per, need, now, span):
        from ctrader_link import decode_bars
        p = self.link.request(2137, {"ctidTraderAccountId": self.link.account_id, "symbolId": sid,
                                     "period": per, "count": 5000,
                                     "fromTimestamp": int((now - span) * 1000),
                                     "toTimestamp": int(now * 1000)}, 2138)
        return decode_bars(p.get("trendbar"))

    def copy_ticks_range(self, symbol, date_from, date_to, flags=COPY_TICKS_ALL):
        with self.lock:
            if not self._ensure():
                return None
            sid = self._name_to_sid(symbol)
            if not sid:
                return None
            f = int(utc_from_srv(_dt_to_srv(date_from)) * 1000)
            t = int(utc_from_srv(_dt_to_srv(date_to)) * 1000)
            try:
                side = {}
                for q in (1, 2):
                    p = self.link.request(2145, {"ctidTraderAccountId": self.link.account_id, "symbolId": sid,
                                                 "type": q, "fromTimestamp": f, "toTimestamp": t}, 2146)
                    side[q] = _decode_ticks(p.get("tickData"))
            except Exception as e:
                self.err = (-10004, "ticks: %s" % e)
                return None
            # aik hi lamhe ki bid + ask = AIK tick (MT5 jaisa), do nahi
            by_ts = {}
            for q in (1, 2):
                for ts, px in side[q]:
                    by_ts.setdefault(ts, {})[q] = px
            bid = ask = 0.0
            rows = []
            for ts in sorted(by_ts):
                bid = by_ts[ts].get(1, bid)
                ask = by_ts[ts].get(2, ask)
                if bid and ask:
                    srv_ms = srv_from_utc(ts / 1000.0) * 1000 + ts % 1000
                    rows.append((srv_ms // 1000, bid, ask, 0.0, 0, srv_ms, 6, 0.0))
            return _rows(TICKS_DTYPE, rows)

    # ---------- orders ----------
    def _res(self, code, comment="", **kw):
        r = OrderSendResult(retcode=code, deal=0, order=0, volume=0.0, price=0.0, bid=0.0, ask=0.0,
                            comment=comment, request_id=0, retcode_external=0)
        r.__dict__.update(kw)
        self.err = (1, "Success") if code == TRADE_RETCODE_DONE else (code, comment)
        return r

    def _find(self, pid):
        try:
            return [p for p in self.link.positions() if p.id == pid]
        except Exception:
            return None

    def order_send(self, request):
        with self.lock:
            if not self._ensure():
                self.err = (-10004, "cTrader raabta nahi")
                return None
            try:
                act = int(request.get("action", 0))
                if act == TRADE_ACTION_SLTP:
                    return self._send_sltp(request)
                if act == TRADE_ACTION_DEAL and request.get("position"):
                    return self._send_close(request)
                if act == TRADE_ACTION_DEAL:
                    return self._send_open(request)
                return self._res(TRADE_RETCODE_INVALID, "action %s nahi" % act)
            except Exception as e:
                self.err = (-10004, "order_send: %s: %s" % (type(e).__name__, e))
                self.log(self.err[1])
                return None

    def _send_open(self, rq):
        name = rq.get("symbol")
        if self._name_to_sid(name) != self.sid:
            return self._res(TRADE_RETCODE_INVALID, "sirf %s" % self.sym)
        if self.clock() < self.sl_block_until:
            return self._res(TRADE_RETCODE_MARKET_CLOSED, "pichhli trade par SL nahi lagi -- 5 min naya order nahi")
        side = "BUY" if int(rq["type"]) == ORDER_TYPE_BUY else "SELL"
        vol = int(round(float(rq["volume"]) * self.lot_size))
        price = float(rq.get("price") or 0.0)
        if not price:
            p = self._px(self.sid)
            price = (p[1] if side == "BUY" else p[0]) if p else 0.0
        sl, tp = float(rq.get("sl") or 0.0), float(rq.get("tp") or 0.0)
        rel_sl = abs(price - sl) if sl else 0.0
        rel_tp = abs(tp - price) if tp else 0.0
        comment = "%d|%s" % (int(rq.get("magic", self.magic)), uuid.uuid4().hex[:10])
        st, info = self.link.market_order(self.sid, side, vol, rel_sl, rel_tp, self.label, comment)
        if st == "REJECTED":
            code = _ERR_RETCODE.get(str(info), TRADE_RETCODE_REJECT)
            self.log("order RAD: %s -> retcode %d" % (info, code))
            return self._res(code, str(info))
        pos = None
        for _ in range(20 if st == "UNKNOWN" else 10):
            try:
                found = [p for p in self.link.positions() if p.comment == comment]
            except Exception:
                found = []
            if found:
                pos = found[0]
                break
            time.sleep(0.5)
        if pos is None:
            self.log("order %s -- position nazar nahi aayi (%s); bot.py khud tasdeeq karega" % (st, info))
            self.err = (-10004, "order ka jawab maloom nahi")
            return None
        self.book[pos.id] = dict(sl=sl, tp=tp, time=srv_from_utc(pos.open_ms / 1000.0) if pos.open_ms else
                                 srv_from_utc(self.clock()), side=side, volume=vol / float(self.lot_size),
                                 price=pos.price, comment=rq.get("comment", ""), by_us=False,
                                 last_sl=pos.sl, last_tp=pos.tp)
        self._save_book()
        digits = int(self.spec.get("digits") or 2)
        tol = 10 ** (-digits) * 1.5
        if (sl and abs(pos.sl - sl) > tol) or (tp and abs(pos.tp - tp) > tol):
            ok, why = self.link.amend_sltp(pos.id, round(sl, digits) if sl else 0, round(tp, digits) if tp else 0)
            cur = self._find(pos.id)
            if cur:
                pos = cur[0]
            if sl and not pos.sl:
                self.log("#%d par SL NAHI lagi (%s) -- FORAN band" % (pos.id, why))
                self.link.close_position(pos.id, pos.volume)
                self.book[pos.id]["by_us"] = True
                self._save_book()
                self.sl_block_until = self.clock() + SL_BLOCK_SEC
                return self._res(TRADE_RETCODE_INVALID_STOPS, "SL nahi lagi -- position #%d band ki" % pos.id)
            if abs(pos.sl - sl) > tol or abs(pos.tp - tp) > tol:
                self.log("#%d: SL/TP asal qeemat par nahi gayi (%s) -- broker par SL %.2f TP %.2f (trade jaari)"
                         % (pos.id, why, pos.sl, pos.tp))
        self.book[pos.id]["last_sl"], self.book[pos.id]["last_tp"] = pos.sl, pos.tp
        self._save_book()
        return self._res(TRADE_RETCODE_DONE, "Request executed", order=pos.id, deal=pos.id,
                         volume=vol / float(self.lot_size), price=pos.price)

    def _send_close(self, rq):
        pid = int(rq["position"])
        cur = self._find(pid)
        if cur is None:
            return None
        if not cur:
            return self._res(TRADE_RETCODE_POSITION_CLOSED, "position pehle se band")
        p = cur[0]
        lot = self.lot_size if p.symbol_id == self.sid else 100
        vol = min(int(round(float(rq.get("volume") or 0) * lot)) or p.volume, p.volume)
        if pid in self.book:
            self.book[pid]["by_us"] = True
            self._save_book()
        ok, why = self.link.close_position(pid, vol)
        for _ in range(10):
            now = self._find(pid)
            if now is not None and (not now or now[0].volume < p.volume):
                px = self._px(p.symbol_id)
                return self._res(TRADE_RETCODE_DONE, "Request executed", order=pid, volume=vol / float(lot),
                                 price=(px[0] if p.side == "BUY" else px[1]) if px else 0.0)
            if not ok:
                break
            time.sleep(0.5)
        if not ok:
            return self._res(_ERR_RETCODE.get(str(why), TRADE_RETCODE_REJECT), str(why))
        return None

    def _send_sltp(self, rq):
        pid = int(rq["position"])
        ok, why = self.link.amend_sltp(pid, float(rq.get("sl") or 0.0), float(rq.get("tp") or 0.0))
        if ok:
            if pid in self.book:
                self.book[pid]["last_sl"], self.book[pid]["last_tp"] = float(rq.get("sl") or 0), float(rq.get("tp") or 0)
                self._save_book()
            return self._res(TRADE_RETCODE_DONE, "Request executed", order=pid)
        if why in ("TIMEOUT", "DISCONNECTED", "NOT_CONNECTED"):
            return None
        return self._res(_ERR_RETCODE.get(str(why), TRADE_RETCODE_INVALID_STOPS), str(why))


def _decode_ticks(td):
    """GetTickDataRes: pehli tick asal (ms, qeemat), baad wali pichhli se FARQ. -> [(utc_ms, price)] purani pehle."""
    out = []
    t = p = None
    for k, x in enumerate(td or []):
        ts, px = int(x.get("timestamp")), int(x.get("tick"))
        if k == 0:
            t, p = ts, px
        else:
            t, p = t + ts, p + px
        out.append((t, p / 100000.0))
    out.sort()
    return out


def _default_folder():
    m = sys.modules.get("__main__")
    f = getattr(m, "__file__", None)
    return os.path.dirname(os.path.abspath(f)) if f else os.getcwd()


# ---------------------------------------------------------------- token: aik refresh, do process
try:
    import ctrader_trade as _T

    class _LockedTrader(_T.CtTrader):
        """Refresh se pehle taala + file dobara parhna: doosre process ne naya token likh diya
        ho to wahi lo, KHUD refresh mat karo (refresh purana token band karta hai)."""

        clock = staticmethod(time.time)

        def _dispatch(self, msg):
            """Spot ka waqt bot ki ghadi se (MT5 tick.time jaisa)."""
            _T.CtTrader._dispatch(self, msg)
            if _T._i(msg.get("payloadType")) == 2131 and not msg.get("clientMsgId"):
                sid = _T._i((msg.get("payload") or {}).get("symbolId"))
                s = self.spots.get(sid)
                if s:
                    self.spots[sid] = (s[0], s[1], self.clock())

        def refresh_token(self):
            lk = _FileLock(self.keys_path + ".lock")
            if not lk.acquire(blocking=True, timeout=30):
                raise _T.CtError("KEYS_LOCK", "ctrader_keys.json ka taala 30 s mein nahi mila")
            try:
                disk = _T.L.load_keys(self.keys_path)
                if disk.get("access_token") != self.keys.get("access_token"):
                    self.log("[CT] doosre process ne token naya kar diya -- wahi le raha, refresh NAHI")
                    self.keys = disk
                    return
                return _T.CtTrader.refresh_token(self)
            finally:
                lk.release()
except Exception:                                    # ctrader_trade na ho to (sirf tests mein)
    _LockedTrader = None


# ---------------------------------------------------------------- module-level (bot.py yahi bulata hai)
_shim = None


def _get():
    global _shim
    if _shim is None:
        _shim = Shim()
    return _shim


def initialize(*a, **kw):
    return _get().initialize(*a, **kw)


def shutdown():
    return _get().shutdown()


def last_error():
    return _get().last_error()


def account_info():
    return _get().account_info()


def symbol_info(name):
    return _get().symbol_info(name)


def symbol_info_tick(name):
    return _get().symbol_info_tick(name)


def symbol_select(name, enable=True):
    return True


def positions_get(**kw):
    return _get().positions_get(**kw)


def positions_total():
    return _get().positions_total()


def history_deals_get(*a, **kw):
    return _get().history_deals_get(*a, **kw)


def history_orders_get(*a, **kw):
    return _get().history_orders_get(*a, **kw)


def copy_rates_from_pos(symbol, timeframe, start_pos, count):
    return _get().copy_rates_from_pos(symbol, timeframe, start_pos, count)


def copy_ticks_range(symbol, date_from, date_to, flags=COPY_TICKS_ALL):
    return _get().copy_ticks_range(symbol, date_from, date_to, flags)


def order_send(request):
    return _get().order_send(request)
