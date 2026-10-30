# -*- coding: utf-8 -*-
"""
ctrader_link.py -- 29 Sep 2026 (HANDOVER 252.5). cTrader Open API ka RAABTA.

KAAM 10 ka pehla hissa: sirf connection + parhna. ORDER KA KOI CODE NAHI.
Transport: JSON over WebSocket, port 5036 (help.ctrader.com "Proxies and
endpoints"). Twisted / protobuf NAHI -- kam RAM (VPS 2 GB), aik pip package:
    pip install websocket-client
Payload numbers / fields: spotware/openapi-proto-messages (asal .proto).

Chaabiyan CHAT ya git mein NAHI -- is folder mein `ctrader_keys.json`:
    {"client_id": "...", "client_secret": "...",
     "access_token": "...", "refresh_token": "...",
     "demo": true, "trader_login": 1234567}
(trader_login = demo account ka number; token refresh par file khud update.)

Pehla asal imtihan (sirf parhta hai, koi trade nahi):
    cd C:\\trading-bot-ctrader && (python ctrader_link.py --check) > ctrader_check.txt 2>&1 & notepad ctrader_check.txt
"""
import io
import itertools
import json
import os
import sys
import threading
import time

VERSION = "ctrader_link v1.1 -- 2 Oct (DE40 bhi dhoondta)"

# --- asal .proto se (OpenApiModelMessages / OpenApiCommonModelMessages) ---
PT = dict(
    ERROR_RES=50, HEARTBEAT=51,
    APP_AUTH_REQ=2100, APP_AUTH_RES=2101, ACC_AUTH_REQ=2102, ACC_AUTH_RES=2103,
    SYMBOLS_LIST_REQ=2114, SYMBOLS_LIST_RES=2115, SYMBOL_BY_ID_REQ=2116, SYMBOL_BY_ID_RES=2117,
    TRADER_REQ=2121, TRADER_RES=2122, EXECUTION_EVENT=2126,
    SUBSCRIBE_SPOTS_REQ=2127, SUBSCRIBE_SPOTS_RES=2128, SPOT_EVENT=2131, ORDER_ERROR_EVENT=2132,
    TRENDBARS_REQ=2137, TRENDBARS_RES=2138, OA_ERROR_RES=2142,
    TOKEN_INVALIDATED_EVENT=2147, CLIENT_DISCONNECT_EVENT=2148,
    ACCOUNTS_BY_TOKEN_REQ=2149, ACCOUNTS_BY_TOKEN_RES=2150,
    ACCOUNT_DISCONNECT_EVENT=2164, REFRESH_TOKEN_REQ=2173, REFRESH_TOKEN_RES=2174,
)
PRICE_SCALE = 100000.0          # qeemat 1/100000 unit mein (proto comments)
M5 = 5                          # ProtoOATrendbarPeriod.M5
HOSTS = {True: "wss://demo.ctraderapi.com:5036", False: "wss://live.ctraderapi.com:5036"}
HEARTBEAT_SEC = 10


class CtError(Exception):
    """Server ne ERROR_RES / OA_ERROR_RES diya, ya jawab waqt par nahi aaya."""

    def __init__(self, code, desc=""):
        Exception.__init__(self, "%s %s" % (code, desc))
        self.code, self.desc = code, desc


def _i(x, d=0):
    """int64 JSON mein number ya string -- dono qubool."""
    try:
        return int(x)
    except (TypeError, ValueError):
        return d


def load_keys(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        k = json.load(fh)
    miss = [n for n in ("client_id", "client_secret", "access_token", "refresh_token") if not k.get(n)]
    if miss:
        raise ValueError("ctrader_keys.json mein nahi: " + ", ".join(miss))
    return k


def save_keys(path, k):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(k, fh, indent=2)
    os.replace(tmp, path)                          # aadhi likhi file kabhi nahi


def decode_bars(trendbars):
    """ProtoOATrendbar -> [{time(UTC epoch s), open, high, low, close, tick_volume}] purani pehle."""
    out = []
    for b in trendbars or []:
        low = _i(b.get("low"))
        t = _i(b.get("utcTimestampInMinutes")) * 60
        out.append(dict(time=t,
                        open=(low + _i(b.get("deltaOpen"))) / PRICE_SCALE,
                        high=(low + _i(b.get("deltaHigh"))) / PRICE_SCALE,
                        low=low / PRICE_SCALE,
                        close=(low + _i(b.get("deltaClose"))) / PRICE_SCALE,
                        tick_volume=_i(b.get("volume"))))
    out.sort(key=lambda r: r["time"])
    return out


def closed_only(bars, now_utc, period_sec=300):
    """Sirf BAND bars: open + 5 min <= abhi. (Bani hui bar kabhi strategy ko nahi.)"""
    return [b for b in bars if b["time"] + period_sec <= now_utc]


class CtraderLink(object):
    def __init__(self, keys_path, url=None, timeout=15.0, log=print, ws_factory=None):
        self.keys_path = keys_path
        self.keys = load_keys(keys_path)
        self.url = url or HOSTS[bool(self.keys.get("demo", True))]
        self.timeout = timeout
        self.log = log
        self._ws_factory = ws_factory
        self._ws = None
        self._send_lock = threading.Lock()
        self._wait = {}                           # clientMsgId -> [Event, msg]
        self._wait_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._stop = threading.Event()
        self._alive = False
        self.account_id = _i(self.keys.get("account_id")) or None
        self.spots = {}                           # symbolId -> (bid, ask, t)
        self.on_event = None                      # execution / order error ke liye (aage)
        self.events = []                          # aakhri 200 event (jaanch ke liye)

    # ---------- transport ----------
    def _make_ws(self):
        if self._ws_factory:
            return self._ws_factory(self.url)
        import websocket                          # pip install websocket-client
        return websocket.create_connection(self.url, timeout=self.timeout)

    def connect(self):
        self.close()
        self._stop.clear()
        self._ws = self._make_ws()
        self._alive = True
        threading.Thread(target=self._reader, name="ct-reader", daemon=True).start()
        threading.Thread(target=self._beater, name="ct-heartbeat", daemon=True).start()
        self.request(PT["APP_AUTH_REQ"], {"clientId": self.keys["client_id"],
                                           "clientSecret": self.keys["client_secret"]}, PT["APP_AUTH_RES"])
        try:
            self._pick_and_auth()
        except CtError as e:
            if "TOKEN" not in e.code.upper():
                raise
            self.log("[CT] token masla (%s) -- refresh" % e.code)
            self.refresh_token()
            self._pick_and_auth()
        return self

    def _pick_and_auth(self):
        if not self.account_id:
            self.account_id = self.pick_account()
        self._acc_auth()

    def _acc_auth(self):
        self.request(PT["ACC_AUTH_REQ"], {"ctidTraderAccountId": self.account_id,
                                           "accessToken": self.keys["access_token"]}, PT["ACC_AUTH_RES"])

    def close(self):
        self._stop.set()
        self._alive = False
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        with self._wait_lock:                     # intezaar wale sab foran chhooten
            for cid, slot in list(self._wait.items()):
                slot[1] = {"payloadType": -1, "payload": {"errorCode": "DISCONNECTED"}}
                slot[0].set()

    def _send(self, obj):
        ws = self._ws
        if ws is None:
            raise CtError("NOT_CONNECTED")
        with self._send_lock:
            ws.send(json.dumps(obj))

    def _beater(self):
        while not self._stop.wait(HEARTBEAT_SEC):
            try:
                self._send({"payloadType": PT["HEARTBEAT"], "payload": {}})
            except Exception:
                return

    def _reader(self):
        ws = self._ws
        while not self._stop.is_set():
            try:
                raw = ws.recv()
            except Exception as e:
                if not self._stop.is_set():
                    self.log("[CT] raabta toota: %s" % e)
                break
            if not raw:
                if not self._stop.is_set():
                    self.log("[CT] server ne raabta band kiya")
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                self.log("[CT] ghalat JSON: %r" % raw[:120])
                continue
            self._dispatch(msg)
        self._alive = False
        with self._wait_lock:
            for cid, slot in list(self._wait.items()):
                slot[1] = {"payloadType": -1, "payload": {"errorCode": "DISCONNECTED"}}
                slot[0].set()

    def _dispatch(self, msg):
        pt = _i(msg.get("payloadType"))
        cid = msg.get("clientMsgId")
        if cid:
            with self._wait_lock:
                slot = self._wait.get(cid)
            if slot is not None:
                slot[1] = msg
                slot[0].set()
                return
        if pt == PT["HEARTBEAT"]:
            return
        p = msg.get("payload") or {}
        if pt == PT["SPOT_EVENT"]:
            sid = _i(p.get("symbolId"))
            old = self.spots.get(sid, (None, None, 0))
            bid = _i(p.get("bid")) / PRICE_SCALE if p.get("bid") is not None else old[0]
            ask = _i(p.get("ask")) / PRICE_SCALE if p.get("ask") is not None else old[1]
            self.spots[sid] = (bid, ask, time.time())   # aik taraf aaye to doosri purani
            return
        self.events.append(msg)
        del self.events[:-200]
        if pt in (PT["TOKEN_INVALIDATED_EVENT"], PT["CLIENT_DISCONNECT_EVENT"], PT["ACCOUNT_DISCONNECT_EVENT"]):
            self.log("[CT] server event %d: %s" % (pt, json.dumps(p)[:200]))
        if self.on_event:
            try:
                self.on_event(msg)
            except Exception as e:
                self.log("[CT] on_event crash: %s" % e)

    def request(self, pt, payload, expect, timeout=None):
        cid = "sb%d" % next(self._ids)
        slot = [threading.Event(), None]
        with self._wait_lock:
            self._wait[cid] = slot
        try:
            self._send({"clientMsgId": cid, "payloadType": pt, "payload": payload})
            if not slot[0].wait(timeout or self.timeout):
                raise CtError("TIMEOUT", "payloadType %d ka jawab nahi aaya" % pt)
        finally:
            with self._wait_lock:
                self._wait.pop(cid, None)
        msg = slot[1]
        rpt = _i(msg.get("payloadType"))
        p = msg.get("payload") or {}
        if rpt in (PT["OA_ERROR_RES"], PT["ERROR_RES"], -1):
            raise CtError(str(p.get("errorCode", "ERROR")), str(p.get("description", "")))
        if rpt != expect:
            raise CtError("UNEXPECTED", "chahiye %d, aaya %d" % (expect, rpt))
        return p

    @property
    def alive(self):
        return self._alive

    # ---------- account ----------
    def accounts(self):
        p = self.request(PT["ACCOUNTS_BY_TOKEN_REQ"], {"accessToken": self.keys["access_token"]},
                         PT["ACCOUNTS_BY_TOKEN_RES"])
        return [dict(id=_i(a.get("ctidTraderAccountId")), login=_i(a.get("traderLogin")),
                     live=bool(a.get("isLive", False)), broker=a.get("brokerTitleShort", ""))
                for a in p.get("ctidTraderAccount") or []]

    def pick_account(self):
        """trader_login diya ho to wahi; warna AIK hi demo account ho to wahi. LIVE kabhi khud nahi."""
        acc = self.accounts()
        want = _i(self.keys.get("trader_login"))
        demo_mode = bool(self.keys.get("demo", True))
        cand = [a for a in acc if a["live"] != demo_mode]
        if want:
            cand = [a for a in cand if a["login"] == want]
        if len(cand) != 1:
            raise CtError("ACCOUNT_CHOICE", "%d account mile (%s) -- ctrader_keys.json mein trader_login likhein"
                          % (len(cand), ", ".join("%d/%s" % (a["login"], "live" if a["live"] else "demo")
                                                  for a in acc)))
        return cand[0]["id"]

    def refresh_token(self):
        p = self.request(PT["REFRESH_TOKEN_REQ"], {"refreshToken": self.keys["refresh_token"]},
                         PT["REFRESH_TOKEN_RES"])
        self.keys["access_token"] = p["accessToken"]
        self.keys["refresh_token"] = p["refreshToken"]
        self.keys["token_expires_at"] = int(time.time()) + _i(p.get("expiresIn"))
        save_keys(self.keys_path, self.keys)
        self.log("[CT] token naya, file update (expires %ds)" % _i(p.get("expiresIn")))

    def trader(self):
        p = self.request(PT["TRADER_REQ"], {"ctidTraderAccountId": self.account_id}, PT["TRADER_RES"])
        t = p.get("trader") or {}
        md = _i(t.get("moneyDigits"), 2)
        return dict(balance=_i(t.get("balance")) / (10.0 ** md), login=_i(t.get("traderLogin")),
                    broker=t.get("brokerName", ""), money_digits=md)

    # ---------- symbols / bars / price ----------
    def symbols(self):
        p = self.request(PT["SYMBOLS_LIST_REQ"], {"ctidTraderAccountId": self.account_id}, PT["SYMBOLS_LIST_RES"])
        return {s.get("symbolName", ""): _i(s.get("symbolId")) for s in p.get("symbol") or []}

    def symbol_spec(self, symbol_id):
        p = self.request(PT["SYMBOL_BY_ID_REQ"], {"ctidTraderAccountId": self.account_id,
                                                   "symbolId": [symbol_id]}, PT["SYMBOL_BY_ID_RES"])
        s = (p.get("symbol") or [{}])[0]
        keys = ("digits", "pipPosition", "lotSize", "minVolume", "maxVolume", "stepVolume")
        return {k: _i(s.get(k), None) if s.get(k) is not None else None for k in keys}

    def bars(self, symbol_id, count=63, period=M5, now_ms=None):
        now_ms = now_ms or int(time.time() * 1000)
        p = self.request(PT["TRENDBARS_REQ"], {"ctidTraderAccountId": self.account_id, "symbolId": symbol_id,
                                                "period": period, "count": count,
                                                "fromTimestamp": now_ms - (count + 5) * 300 * 1000,
                                                "toTimestamp": now_ms}, PT["TRENDBARS_RES"])
        return decode_bars(p.get("trendbar"))

    def subscribe(self, symbol_id):
        self.request(PT["SUBSCRIBE_SPOTS_REQ"], {"ctidTraderAccountId": self.account_id,
                                                  "symbolId": [symbol_id]}, PT["SUBSCRIBE_SPOTS_RES"])

    def price(self, symbol_id, max_age=30.0):
        s = self.spots.get(symbol_id)
        if not s or s[0] is None or s[1] is None or time.time() - s[2] > max_age:
            return None
        return s[0], s[1]


# ---------- --check : pehla asal imtihan, sirf parhna ----------
WANT = (("US30", ("US30",), True),
        ("USTEC", ("USTEC", "NAS100", "US100", "USTECH"), True),
        ("DE40", ("DE40", "GER40", "DE30", "GER30"), False))     # DE40 = VWAP ka umeedwar (257.4); na mile to sirf khabar


def check(keys_path, url=None, want=WANT, ws_factory=None, wait_spot=10.0):
    pr = lambda *a: print(*a, flush=True)
    pr("=" * 70)
    pr(VERSION + "  --check  (sirf parhta hai, koi order NAHI)")
    pr("=" * 70)
    ok = True
    try:
        link = CtraderLink(keys_path, url=url, ws_factory=ws_factory, log=pr)
    except Exception as e:
        pr("chaabiyan: NAAKAAM -- %s" % e)
        return False
    pr("host: %s" % link.url)
    try:
        link.connect()
    except CtError as e:
        pr("connect / auth: NAAKAAM -- %s" % e)
        return False
    except Exception as e:
        pr("connect: NAAKAAM -- %s: %s" % (type(e).__name__, e))
        return False
    pr("1. app auth + account auth: THEEK  (ctidTraderAccountId %s)" % link.account_id)
    try:
        t = link.trader()
        pr("2. account: login %s | %s | balance %.2f" % (t["login"], t["broker"], t["balance"]))
        names = link.symbols()
        pr("3. symbols: %d" % len(names))
        now = time.time()
        for it in want:
            w, al, must = (it, (it,), True) if isinstance(it, str) else it
            hits = []
            for a in al:
                hits = sorted(n for n in names if n.upper().replace(".", "").startswith(a))
                if hits:
                    break
            if not hits:
                pr("   %-6s NAHI MILA %s (milte julte: %s)" % (w, "" if must else "(zaroori nahi -- sirf khabar)",
                   ", ".join(sorted(n for n in names if any(a[:3] in n.upper() for a in al))[:8]) or "-"))
                if must:
                    ok = False
                continue
            sid = names[hits[0]]
            spec = link.symbol_spec(sid)
            pr("   %-6s -> '%s' id %d | %s" % (w, hits[0], sid, spec))
            b = link.bars(sid)
            cb = closed_only(b, now)
            if not cb:
                pr("   bars: 0 -- NAAKAAM")
                ok = False
                continue
            last = cb[-1]
            pr("   bars: %d aayin, band %d | aakhri band %s UTC  O %.2f H %.2f L %.2f C %.2f"
               % (len(b), len(cb), time.strftime("%Y-%m-%d %H:%M", time.gmtime(last["time"])),
                  last["open"], last["high"], last["low"], last["close"]))
            gaps = [cb[i]["time"] - cb[i - 1]["time"] for i in range(1, len(cb))]
            pr("   bars ka faasla: sab 300s? %s" % ("HAAN" if gaps and all(g == 300 for g in gaps)
                                                 else "NAHI (weekend/break ho sakta hai) %s" % sorted(set(gaps))[:5]))
            link.subscribe(sid)
            t0 = time.time()
            while time.time() - t0 < wait_spot and link.price(sid) is None:
                time.sleep(0.2)
            px = link.price(sid)
            if px:
                far = abs(px[0] - last["close"]) / last["close"] * 100
                pr("   spot bid %.2f ask %.2f | spread %.2f | aakhri close se farq %.2f%% %s"
                   % (px[0], px[1], px[1] - px[0], far, "THEEK" if far < 2 else "*** qeemat paimana SHAK ***"))
            else:
                pr("   spot: %ds mein qeemat nahi aayi (market band?)" % wait_spot)
    except CtError as e:
        pr("NAAKAAM -- %s" % e)
        ok = False
    finally:
        link.close()
    pr("\nNATIJA: %s" % ("SAB THEEK" if ok else "KUCH NAAKAAM -- upar dekhein"))
    return ok


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--check" in sys.argv:
        kp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ctrader_keys.json")
        sys.exit(0 if check(kp) else 1)
    print(__doc__)
