# Nakli cTrader server (JSON over WebSocket) -- ctrader_link.py ka imtihan.
import json, os, sys, threading, time, tempfile, io, contextlib
from websockets.sync.server import serve
import ctrader_link as C

P = C.PT
NOW = int(time.time())
BAR0 = (NOW // 300) * 300 - 62 * 300           # 62 band bars + 1 bani hui


class Fake:
    def __init__(self, strs=False, expired_first=False, spam=False, drop_after=None, two_demo=False):
        self.strs, self.expired, self.spam, self.drop_after, self.two_demo = strs, expired_first, spam, drop_after, two_demo
        self.token = "tok1"
        self.seen, self.heartbeats, self.n = [], 0, 0

    def v(self, x):
        return str(x) if self.strs else x                 # int64 string ki shakal mein

    def handle(self, ws):
        self.n = 0                                           # har connection ki apni ginti
        first = not getattr(self, "_had", False)
        self._had = True
        for raw in ws:
            m = json.loads(raw)
            pt, cid, p = m["payloadType"], m.get("clientMsgId"), m.get("payload", {})
            self.seen.append(pt)
            if pt == P["HEARTBEAT"]:
                self.heartbeats += 1
                continue
            self.n += 1
            if first and self.drop_after and self.n > self.drop_after:
                ws.close()
                return
            if self.spam:                                   # jawab se pehle event aur ghair-mutaliq msg
                ws.send(json.dumps({"payloadType": P["SPOT_EVENT"], "payload": {"ctidTraderAccountId": 9, "symbolId": self.v(101), "bid": self.v(4210050000)}}))
                ws.send(json.dumps({"payloadType": P["HEARTBEAT"], "payload": {}}))
                ws.send(json.dumps({"clientMsgId": "kisi-aur-ka", "payloadType": 2101, "payload": {}}))
            def reply(rpt, pay):
                ws.send(json.dumps({"clientMsgId": cid, "payloadType": rpt, "payload": pay}))
            def err(code):
                reply(P["OA_ERROR_RES"], {"errorCode": code, "description": "nakli"})
            if pt == P["APP_AUTH_REQ"]:
                reply(P["APP_AUTH_RES"], {}) if p.get("clientSecret") == "sec" else err("CH_CLIENT_AUTH_FAILURE")
            elif pt == P["ACCOUNTS_BY_TOKEN_REQ"]:
                if p["accessToken"] != self.token or self.expired:
                    err("CH_ACCESS_TOKEN_INVALID")
                    continue
                acc = [{"ctidTraderAccountId": self.v(9), "isLive": False, "traderLogin": self.v(5551), "brokerTitleShort": "ICM"},
                       {"ctidTraderAccountId": self.v(7), "isLive": True, "traderLogin": self.v(5550), "brokerTitleShort": "ICM"}]
                if self.two_demo:
                    acc.append({"ctidTraderAccountId": self.v(8), "isLive": False, "traderLogin": self.v(5552)})
                reply(P["ACCOUNTS_BY_TOKEN_RES"], {"accessToken": self.token, "ctidTraderAccount": acc})
            elif pt == P["REFRESH_TOKEN_REQ"]:
                self.expired = False
                self.token = "tok2"
                reply(P["REFRESH_TOKEN_RES"], {"accessToken": "tok2", "tokenType": "bearer", "expiresIn": self.v(2628000), "refreshToken": "ref2"})
            elif pt == P["ACC_AUTH_REQ"]:
                if C._i(p["ctidTraderAccountId"]) != 9:
                    err("WRONG_ACCOUNT")
                elif p["accessToken"] != self.token:
                    err("CH_ACCESS_TOKEN_INVALID")
                else:
                    reply(P["ACC_AUTH_RES"], {"ctidTraderAccountId": self.v(9)})
            elif pt == P["TRADER_REQ"]:
                reply(P["TRADER_RES"], {"ctidTraderAccountId": 9, "trader": {"ctidTraderAccountId": 9, "balance": self.v(10000000), "moneyDigits": 2, "traderLogin": self.v(5551), "brokerName": "IC Markets", "depositAssetId": 1}})
            elif pt == P["SYMBOLS_LIST_REQ"]:
                reply(P["SYMBOLS_LIST_RES"], {"ctidTraderAccountId": 9, "symbol": [{"symbolId": self.v(101), "symbolName": "US30"}, {"symbolId": self.v(102), "symbolName": "USTEC"}, {"symbolId": 1, "symbolName": "EURUSD"}]})
            elif pt == P["SYMBOL_BY_ID_REQ"]:
                reply(P["SYMBOL_BY_ID_RES"], {"ctidTraderAccountId": 9, "symbol": [{"symbolId": p["symbolId"][0], "digits": 2, "pipPosition": 0, "lotSize": self.v(100), "minVolume": self.v(1), "maxVolume": self.v(500000), "stepVolume": self.v(1)}]})
            elif pt == P["TRENDBARS_REQ"]:
                bars = []
                for k in range(63):                          # ULTI tarteeb, aakhri bani hui
                    t = BAR0 + k * 300
                    base = 4200000000 + k * 1000
                    bars.append({"volume": self.v(100 + k), "period": 5, "low": self.v(base), "deltaOpen": self.v(500), "deltaHigh": self.v(2000), "deltaClose": self.v(1500), "utcTimestampInMinutes": t // 60})
                reply(P["TRENDBARS_RES"], {"ctidTraderAccountId": 9, "period": 5, "symbolId": p["symbolId"], "trendbar": bars[::-1]})
            elif pt == P["SUBSCRIBE_SPOTS_REQ"]:
                reply(P["SUBSCRIBE_SPOTS_RES"], {"ctidTraderAccountId": 9})
                sid = p["symbolId"][0]
                ws.send(json.dumps({"payloadType": P["SPOT_EVENT"], "payload": {"ctidTraderAccountId": 9, "symbolId": self.v(sid), "bid": self.v(4206200000)}}))
                ws.send(json.dumps({"payloadType": P["SPOT_EVENT"], "payload": {"ctidTraderAccountId": 9, "symbolId": self.v(sid), "ask": self.v(4206270000)}}))
            else:
                err("UNKNOWN")


def start(f):
    srv = serve(f.handle, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "ws://127.0.0.1:%d" % srv.socket.getsockname()[1]


def keys(**extra):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "ctrader_keys.json")
    k = {"client_id": "id", "client_secret": "sec", "access_token": "tok1", "refresh_token": "ref1", "demo": True}
    k.update(extra)
    json.dump(k, open(p, "w"))
    return p


R = []
def ok(name, cond):
    R.append((name, bool(cond)))
    print(("PAAS " if cond else "FAIL ") + name, flush=True)


quiet = lambda *a: None

# 1. poora --check, int64 strings + beech mein spam events
for strs in (False, True):
    f = Fake(strs=strs, spam=True)
    srv, url = start(f)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = C.check(keys(), url=url, wait_spot=3)
    out = buf.getvalue()
    ok("check SAB THEEK (strings=%s)" % strs, res and "SAB THEEK" in out)
    ok("check: band bars 62 (bani hui nikal gayi) strings=%s" % strs, "band 62" in out)
    ok("check: faasla 300s HAAN strings=%s" % strs, "sab 300s? HAAN" in out)
    ok("check: spot dono taraf + paimana THEEK strings=%s" % strs, "spot bid 42062.00 ask 42062.70" in out and "THEEK" in out)
    ok("check: balance 100000.00 strings=%s" % strs, "balance 100000.00" in out)
    if strs:
        print(out)
    srv.shutdown()

# 2. bars ka hisaab + tarteeb
f = Fake(); srv, url = start(f)
L = C.CtraderLink(keys(), url=url, log=quiet).connect()
b = L.bars(101)
ok("bars purani pehle", all(b[i]["time"] < b[i + 1]["time"] for i in range(len(b) - 1)))
ok("bar decode O/H/L/C", abs(b[0]["low"] - 42000.0) < 1e-9 and abs(b[0]["open"] - 42000.005) < 1e-9
   and abs(b[0]["high"] - 42000.02) < 1e-9 and abs(b[0]["close"] - 42000.015) < 1e-9 and b[0]["tick_volume"] == 100)
cb = C.closed_only(b, time.time())
ok("closed_only: bani hui bar bahar", len(cb) == 62 and cb[-1]["time"] + 300 <= time.time())
ok("closed_only: bar theek band hone ke lamhe par andar", len(C.closed_only(b, b[-1]["time"] + 300)) == 63)
# 3. error -> CtError, connection zinda rehta hai
try:
    L.request(9999, {}, 1)
    ok("UNKNOWN error pakra", False)
except C.CtError as e:
    ok("UNKNOWN error pakra", e.code == "UNKNOWN")
ok("error ke baad bhi raabta", L.trader()["login"] == 5551)
# 4. heartbeat
C.HEARTBEAT_SEC = 0.3
L.close(); L.connect(); time.sleep(1.2)
ok("heartbeat ja raha hai", f.heartbeats >= 2)
C.HEARTBEAT_SEC = 10
# 5. parallel requests sahi jawab (clientMsgId)
res = {}
def w(i):
    res[i] = L.symbol_spec(101 if i % 2 else 102)
th = [threading.Thread(target=w, args=(i,)) for i in range(20)]
[t.start() for t in th]; [t.join() for t in th]
ok("20 saath requests, sab jawab", len(res) == 20 and all(r["lotSize"] == 100 for r in res.values()))
L.close(); srv.shutdown()

# 6. token expire -> refresh -> file update
f = Fake(expired_first=True); srv, url = start(f)
kp = keys()
L = C.CtraderLink(kp, url=url, log=quiet).connect()
k2 = json.load(open(kp))
ok("expired token: refresh + auth", L.alive and f.token == "tok2")
ok("naye token file mein", k2["access_token"] == "tok2" and k2["refresh_token"] == "ref2" and k2["token_expires_at"] > NOW)
ok("purani .tmp file nahi bachi", not os.path.exists(kp + ".tmp"))
L.close(); srv.shutdown()

# 7. ghalat secret -> saaf error, koi atkav nahi
f = Fake(); srv, url = start(f)
t0 = time.time()
try:
    C.CtraderLink(keys(client_secret="ghalat"), url=url, log=quiet).connect()
    ok("ghalat secret pakra", False)
except C.CtError as e:
    ok("ghalat secret pakra", e.code == "CH_CLIENT_AUTH_FAILURE" and time.time() - t0 < 3)
# 8. do demo account -> trader_login zaroori; diya ho to wahi
f2 = Fake(two_demo=True); srv2, url2 = start(f2)
try:
    C.CtraderLink(keys(), url=url2, log=quiet).connect()
    ok("do demo -> ACCOUNT_CHOICE", False)
except C.CtError as e:
    ok("do demo -> ACCOUNT_CHOICE", e.code == "ACCOUNT_CHOICE" and "5551/demo" in e.desc)
L = C.CtraderLink(keys(trader_login=5551), url=url2, log=quiet).connect()
ok("trader_login se sahi account (9)", L.account_id == 9)
L.close()
# 9. LIVE account kabhi khud nahi chunta (demo=true)
ok("live account (7) nahi chuna", L.account_id != 7)
srv2.shutdown()

# 10. server beech mein toote -> intezaar wala foran error, alive False
f = Fake(drop_after=4); srv, url = start(f)
L = C.CtraderLink(keys(), url=url, log=quiet, timeout=5).connect()
t0 = time.time()
try:
    L.trader(); L.symbols()
    ok("toota raabta -> error", False)
except C.CtError as e:
    ok("toota raabta -> DISCONNECTED foran", e.code == "DISCONNECTED" and time.time() - t0 < 2)
time.sleep(0.2)
ok("alive False", not L.alive)
L.connect()
ok("dobara connect", L.alive)
L.close(); srv.shutdown()
# 11. server hi nahi -> saaf naakaami
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = C.check(keys(), url="ws://127.0.0.1:1")
ok("server nahi -> check NAAKAAM, crash nahi", r is False and "NAAKAAM" in buf.getvalue())
# 12. chaabi adhoori
p = keys(); k = json.load(open(p)); del k["refresh_token"]; json.dump(k, open(p, "w"))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    r = C.check(p, url=url)
ok("adhoori chaabi -> naam ke saath", r is False and "refresh_token" in buf.getvalue())

print("\nKUL: %d / %d PAAS" % (sum(1 for _, c in R if c), len(R)))
sys.exit(0 if all(c for _, c in R) else 1)
