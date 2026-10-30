# -*- coding: utf-8 -*-
"""
ctrader_check.py -- 7 Oct 2026 (HANDOVER 262). cTrader keys + account ki PEHLI ASAL jaanch.
SIRF PARHTA HAI: koi order nahi; token REFRESH NAHI (expire ho to saaf FAIL -- naya token lo).
(ctrader_link.py --check ki jagah: woh USTEC bhi maangta hai aur scope nahi dikhata; ctrader_link.py
ka md5 352b526a pakka rakhna hai, is liye use chheda NAHI.)

  1 chaabiyan     ctrader_keys.json: chaaron bhari, demo, trader_login 1234567 (qeematein NAHI dikhti)
  2 app           client_id / client_secret sahi?
  3 SCOPE         token TRADE hai ya sirf VIEW -- VIEW = FAIL (bot order nahi de sakta)
  4 account       1234567 DEMO mila, live NAHI chuna; balance, broker, currency
  5 symbols       DE40 + US30 (broker ke naam), spec (lot / min / step), quote currency -> USD
  6 bars          62 band M5, faasla 300 s, aakhri bar kitni purani
  7 qeemat        spot bid / ask, spread (points, 0.01), aakhri close se farq

    cd C:\\trading-bot-vwap && (python ctrader_check.py) > ctrader_check.txt 2>&1 & notepad ctrader_check.txt
"""
import io
import json
import os
import sys
import time
from datetime import datetime

VERSION = "ctrader_check v1 -- 7 Oct 2026 (sirf parhta, refresh NAHI)"
HERE = os.path.dirname(os.path.abspath(__file__))
LOGIN = 1234567
SYMS = {"DE40": ["DE40", "GER40", "DE30", "GER30"], "US30": ["US30"]}


def pr(*a):
    print(*a, flush=True)


def scope_of(p):
    """permissionScope: 1 / 'SCOPE_TRADE' = TRADE; 0 / 'SCOPE_VIEW' / gayab (proto default) = VIEW."""
    v = p.get("permissionScope")
    if v in (1, "1", "SCOPE_TRADE"):
        return "TRADE"
    if v in (0, "0", "SCOPE_VIEW", None):
        return "VIEW" if v is not None else "VIEW (field nahi aaya = proto default VIEW)"
    return "NA-MALOOM (%r)" % (v,)


def main(link_factory=None, keys_path=None, wait_spot=10.0, out=pr):
    out("=" * 72)
    out(VERSION)
    out("=" * 72)
    fails = []
    kp = keys_path or os.path.join(HERE, "ctrader_keys.json")
    # 1 chaabiyan
    try:
        k = json.load(io.open(kp, encoding="utf-8-sig"))
    except Exception as e:
        out("1. chaabiyan: FAIL -- %s parh nahi saka (%s). Pehle: python keys_bharo.py" % (kp, type(e).__name__))
        return 1
    miss = [f for f in ("client_id", "client_secret", "access_token", "refresh_token") if not str(k.get(f, "")).strip()]
    out("1. chaabiyan: %s | demo %s | trader_login %s" % ("chaaron BHARI" if not miss else "KHAALI: " + ", ".join(miss),
                                                         k.get("demo"), k.get("trader_login")))
    if miss:
        fails.append("chaabiyan khaali: " + ", ".join(miss))
    if k.get("demo") is not True:
        fails.append("demo true nahi -- LIVE kabhi nahi")
    if int(k.get("trader_login") or 0) != LOGIN:
        fails.append("trader_login %s (chahiye %d)" % (k.get("trader_login"), LOGIN))
    if fails:
        out("\nNATIJA: FAIL -- " + " | ".join(fails))
        return 1
    sys.path.insert(0, os.path.join(HERE, "DE40"))
    import ctrader_trade as T
    PT = T.PT
    try:
        link = link_factory() if link_factory else T.CtTrader(kp, allow_refresh=False, log=lambda *a: None)
    except Exception as e:
        out("   link nahi bana: %s" % e)
        return 1
    try:
        # 2 + 3 app aur scope (account chunne se PEHLE)
        try:
            link.close()
            link._stop.clear()
            link._ws = link._make_ws()
            link._alive = True
            import threading
            threading.Thread(target=link._reader, daemon=True).start()
            link.request(PT["APP_AUTH_REQ"], {"clientId": k["client_id"], "clientSecret": k["client_secret"]},
                         PT["APP_AUTH_RES"])
            out("2. app (client_id / secret): THEEK")
        except T.CtError as e:
            out("2. app: FAIL -- %s (client_id / client_secret ghalat? app ACTIVE?)" % e.code)
            fails.append("app auth %s" % e.code)
            raise
        try:
            p = link.request(PT["ACCOUNTS_BY_TOKEN_REQ"], {"accessToken": k["access_token"]}, PT["ACCOUNTS_BY_TOKEN_RES"])
        except T.CtError as e:
            out("3. token: FAIL -- %s (expire / ghalat token -- Playground se naya, phir keys_bharo)" % e.code)
            fails.append("token %s" % e.code)
            raise
        sc = scope_of(p)
        if sc == "TRADE":
            out("3. token SCOPE: TRADE -- THEEK (order de sakta hai)")
        else:
            out("3. token SCOPE: %s -- *** FAIL ***: is token se bot ORDER NAHI de sakta. Playground mein scope "
                "\"Account info and trading\" chun kar NAYA token lo, phir keys_bharo.py." % sc)
            fails.append("token scope %s (TRADE chahiye)" % sc)
        accs = p.get("ctidTraderAccount") or []
        out("   is token ke accounts: %s" % ", ".join("%s/%s" % (a.get("traderLogin"), "LIVE" if a.get("isLive") else "demo")
                                                    for a in accs))
        link.close()
        # 4 account
        try:
            link.connect()
        except T.CtError as e:
            out("4. account: FAIL -- %s" % e)
            fails.append("account %s" % e.code)
            raise
        t = link.trader()
        ft = link.full_trader()
        dep = link.assets().get(T._i(ft.get("depositAssetId")), "?")
        mine = [a for a in accs if T._i(a.get("ctidTraderAccountId")) == link.account_id]
        live = bool(mine and mine[0].get("isLive"))
        out("4. account: login %s | %s | %s | balance %.2f %s" % (t["login"], "LIVE" if live else "DEMO", t["broker"],
                                                               t["balance"], dep))
        if live or t["login"] != LOGIN:
            fails.append("ghalat account (live %s, login %s)" % (live, t["login"]))
        if dep != "USD":
            fails.append("account currency %s (USD socha tha -- risk hisaab dekho)" % dep)
        # 5 symbols
        now = time.time()
        for sym, al in SYMS.items():
            nm, sid = link.find_symbol(al)
            if not sid:
                out("5. %s: FAIL -- broker par nahi mila (%s)" % (sym, "/".join(al)))
                fails.append("%s symbol nahi" % sym)
                continue
            sp = link.symbol_spec(sid)
            try:
                q, d, cn, cid, inv = link.quote_conversion(nm)
                conv = "quote %s -> %s %s" % (q, d, ("rate %s%s" % (cn, " (ulta)" if inv else "")) if cn else "(rate 1)")
            except T.CtError as e:
                conv = "FAIL %s" % e
                fails.append("%s currency %s" % (sym, e))
            out("5. %s -> '%s' id %d | digits %s lotSize %s min %s step %s max %s | %s"
                % (sym, nm, sid, sp.get("digits"), sp.get("lotSize"), sp.get("minVolume"), sp.get("stepVolume"),
                   sp.get("maxVolume"), conv))
            if not sp.get("lotSize") or not sp.get("stepVolume"):
                fails.append("%s spec adhoori" % sym)
            # 6 bars
            from ctrader_link import closed_only
            b = closed_only(link.bars(sid, count=63), now)
            if len(b) < 15:
                b = closed_only(link.bars(sid, count=1200), now)
            gaps = sorted(set(b[i]["time"] - b[i - 1]["time"] for i in range(1, len(b))))
            age = (now - b[-1]["time"] - 300) / 60.0 if b else None
            out("6. %s bars: %d band | faasla %s | aakhri band bar %s UTC (%s min purani)"
                % (sym, len(b), "sab 300s" if gaps == [300] else str(gaps[:4]),
                   datetime.utcfromtimestamp(b[-1]["time"]).strftime("%a %m-%d %H:%M") if b else "-",
                   "%.0f" % age if age is not None else "-"))
            if not b:
                fails.append("%s bars nahi" % sym)
            # 7 qeemat
            link.subscribe(sid)
            t0 = time.time()
            while time.time() - t0 < wait_spot and link.price(sid) is None:
                time.sleep(0.2)
            px = link.price(sid)
            if px and b:
                far = abs(px[0] - b[-1]["close"]) / b[-1]["close"] * 100
                out("7. %s spot bid %.2f ask %.2f | spread %.0f pts (%.2f) | aakhri close se %.2f%% %s"
                    % (sym, px[0], px[1], (px[1] - px[0]) / 0.01, px[1] - px[0], far,
                       "THEEK" if far < 2 else "*** paimana SHAK ***"))
                if far >= 2:
                    fails.append("%s qeemat ka paimana" % sym)
                if (px[1] - px[0]) / 0.01 > 250:
                    out("   DHYAN: spread > 250 pts -- bot is waqt trade NAHI lega (max_spread_points)")
            else:
                out("7. %s spot: %ds mein qeemat nahi (market band? weekend / raat theek)" % (sym, wait_spot))
        exp = link.token_expires_at()
        if exp:
            out("   token: %.1f din baqi" % ((exp - time.time()) / 86400.0))
    except Exception as e:
        if not fails:
            fails.append("%s: %s" % (type(e).__name__, e))
    finally:
        try:
            link.close()
        except Exception:
            pass
    out("\nNATIJA: %s" % ("SAB THEEK -- agla qadam: ct_backtest.py (WAPSI qadam 5)" if not fails
                          else "FAIL -- " + " | ".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
