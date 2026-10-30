# -*- coding: utf-8 -*-
"""
ctrader_trade.py -- 3 Oct 2026 (HANDOVER 259). cTrader ka ORDER wala hissa.

ctrader_link.py (v1.1, 352b526a) ko HAATH NAHI lagaya -- yeh us ki class ke
upar aik patli tah hai: order, SL/TP badalna, band karna, khuli positions,
deals, account ka equity, asset / currency.

Payload numbers + fields: spotware/openapi-proto-messages (asal .proto,
3 Oct ko dobara parhe):
  2106 NEW_ORDER_REQ          (MARKET par sirf relativeStopLoss/TakeProfit)
  2110 AMEND_POSITION_SLTP    (absolute stopLoss / takeProfit)
  2111 CLOSE_POSITION_REQ     (positionId + volume)
  2124/2125 RECONCILE         (khuli positions, label + comment ke saath)
  2126 EXECUTION_EVENT, 2132 ORDER_ERROR_EVENT
  2179/2180 DEAL_LIST_BY_POSITION_ID  (band hone ka munafa: closePositionDetail)
  2187/2188 POSITION_UNREALIZED_PNL   (equity = balance + floating)
  2112/2113 ASSET_LIST        (DE40 ki quote currency EUR -> USD rate)

TOKEN: `allow_refresh=False` (routine / jurwa) -> token kabhi refresh NAHI.
Refresh purana token band kar deta hai, is liye SIRF bot refresh karta hai
(HANDOVER 252.5 design note, 258.10).
"""
import json
import threading
import time

import ctrader_link as L
from ctrader_link import CtError, _i, PRICE_SCALE

VERSION = "ctrader_trade v1 -- 3 Oct"

PT = dict(L.PT)
PT.update(
    NEW_ORDER_REQ=2106, AMEND_POSITION_SLTP_REQ=2110, CLOSE_POSITION_REQ=2111,
    ASSET_LIST_REQ=2112, ASSET_LIST_RES=2113,
    RECONCILE_REQ=2124, RECONCILE_RES=2125,
    DEAL_LIST_BY_POSITION_ID_REQ=2179, DEAL_LIST_BY_POSITION_ID_RES=2180,
    UNREALIZED_PNL_REQ=2187, UNREALIZED_PNL_RES=2188,
)
BUY, SELL = 1, 2                     # ProtoOATradeSide
MARKET = 1                           # ProtoOAOrderType
EXEC_FILLED, EXEC_REJECTED = 3, 7    # ProtoOAExecutionType
SIDE_NAME = {BUY: "BUY", SELL: "SELL"}
SILENT_DEAD_SEC = 90                 # itni der server se KUCH na aaye -> raabta mara hua


class Position(object):
    """ProtoOAPosition ka saada roop (qeematein price units mein)."""
    __slots__ = ("id", "symbol_id", "side", "volume", "price", "sl", "tp",
                 "label", "comment", "open_ms")

    def __init__(self, p):
        td = p.get("tradeData") or {}
        self.id = _i(p.get("positionId"))
        self.symbol_id = _i(td.get("symbolId"))
        self.side = SIDE_NAME.get(_i(td.get("tradeSide")), "?")
        self.volume = _i(td.get("volume"))           # 0.01 unit
        self.price = float(p.get("price") or 0.0)
        self.sl = float(p["stopLoss"]) if p.get("stopLoss") is not None else 0.0
        self.tp = float(p["takeProfit"]) if p.get("takeProfit") is not None else 0.0
        self.label = td.get("label") or ""
        self.comment = td.get("comment") or ""
        self.open_ms = _i(td.get("openTimestamp"))

    def __repr__(self):
        return "Position(#%d %s vol %d @%.2f sl %.2f tp %.2f %s)" % (
            self.id, self.side, self.volume, self.price, self.sl, self.tp, self.label)


class CtTrader(L.CtraderLink):
    def __init__(self, keys_path, allow_refresh=False, **kw):
        L.CtraderLink.__init__(self, keys_path, **kw)
        self.allow_refresh = bool(allow_refresh)
        self.money_digits = 2
        self._names = None            # symbolName -> LightSymbol dict
        self._assets = None           # assetId -> name

    # ---------- reader: chup rehna = toota NAHI ----------
    def _reader(self):
        """ctrader_link._reader jaisa, aik farq ke saath (3 Oct, test_bot_vwap ne pakra):

        websocket-client ka `timeout` (15 s) recv par bhi lagta hai. Server 15 s
        chup rahe (weekend, spot nahi) to v1.1 use "raabta toota" maan leta --
        bot har 15 s dobara jurta. Yahan recv ka timeout sirf INTEZAAR hai;
        SILENT_DEAD_SEC tak kuch na aaye tab mara hua maano (heartbeat hum 10 s
        par bhejte hain, server ka jawab / spot na aaye to raabta mashkook).
        """
        ws = self._ws
        self.last_rx = time.time()
        while not self._stop.is_set():
            try:
                raw = ws.recv()
            except Exception as e:
                if "imeout" in type(e).__name__ and time.time() - self.last_rx < SILENT_DEAD_SEC:
                    continue
                if not self._stop.is_set():
                    self.log("[CT] raabta toota: %s" % e)
                break
            if not raw:
                if not self._stop.is_set():
                    self.log("[CT] server ne raabta band kiya")
                break
            self.last_rx = time.time()
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

    # ---------- token: sirf bot ----------
    def refresh_token(self):
        if not self.allow_refresh:
            raise CtError("REFRESH_NOT_ALLOWED",
                          "yeh process token refresh nahi karta (sirf bot) -- bot chalne dein")
        return L.CtraderLink.refresh_token(self)

    def token_expires_at(self):
        return _i(self.keys.get("token_expires_at"))

    # ---------- jawab: kayi qism ka ----------
    def request_any(self, pt, payload, expect, timeout=None):
        """request() jaisa, magar kayi jawab qubool -> (payloadType, payload).

        ORDER_ERROR_EVENT / execution event bhi jawab hain (ghalti nahi).
        Server ka ERROR_RES / raabta toota -> CtError (bulane wala tay kare).
        """
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
        if rpt not in expect:
            raise CtError("UNEXPECTED", "chahiye %s, aaya %d" % (sorted(expect), rpt))
        return rpt, p

    # ---------- account ----------
    def trader(self):
        t = L.CtraderLink.trader(self)
        self.money_digits = t["money_digits"]
        return t

    def full_trader(self):
        p = self.request(PT["TRADER_REQ"], {"ctidTraderAccountId": self.account_id}, PT["TRADER_RES"])
        return p.get("trader") or {}

    def equity(self, balance=None):
        """balance + sab khuli positions ka floating (deposit currency)."""
        if balance is None:
            balance = self.trader()["balance"]
        p = self.request(PT["UNREALIZED_PNL_REQ"], {"ctidTraderAccountId": self.account_id},
                         PT["UNREALIZED_PNL_RES"])
        md = _i(p.get("moneyDigits"), 2)
        fl = sum(_i(u.get("grossUnrealizedPnL")) for u in p.get("positionUnrealizedPnL") or [])
        return balance + fl / (10.0 ** md)

    # ---------- symbols / currency ----------
    def light_symbols(self, refresh=False):
        if self._names is None or refresh:
            p = self.request(PT["SYMBOLS_LIST_REQ"], {"ctidTraderAccountId": self.account_id},
                             PT["SYMBOLS_LIST_RES"])
            self._names = {s.get("symbolName", ""): s for s in p.get("symbol") or []}
        return self._names

    def assets(self):
        if self._assets is None:
            p = self.request(PT["ASSET_LIST_REQ"], {"ctidTraderAccountId": self.account_id},
                             PT["ASSET_LIST_RES"])
            self._assets = {_i(a.get("assetId")): a.get("name", "") for a in p.get("asset") or []}
        return self._assets

    def find_symbol(self, aliases):
        """aliases (DE40, GER40, ...) mein se pehla jo broker ke paas ho -> (naam, id)."""
        names = self.light_symbols()
        for a in aliases:
            hits = sorted(n for n in names if n.upper().replace(".", "").startswith(a.upper()))
            if hits:
                return hits[0], _i(names[hits[0]].get("symbolId"))
        return None, None

    def quote_conversion(self, symbol_name):
        """Symbol ki quote currency -> account (deposit) currency.

        Lautata: (quote, deposit, conv_name, conv_id, invert)
          quote == deposit       -> conv_name None (rate 1)
          QUOTEDEP (EURUSD)      -> rate = us ka bid
          DEPQUOTE (USDEUR)      -> rate = 1 / ask
        Na mile -> CtError (us symbol par trade NAHI).
        """
        names = self.light_symbols()
        s = names[symbol_name]
        assets = self.assets()
        quote = assets.get(_i(s.get("quoteAssetId")), "")
        dep = assets.get(_i(self.full_trader().get("depositAssetId")), "")
        if not quote or not dep:
            raise CtError("CURRENCY", "%s: quote/deposit asset maloom nahi (%r/%r)" % (symbol_name, quote, dep))
        if quote == dep:
            return quote, dep, None, None, False
        for nm, inv in ((quote + dep, False), (dep + quote, True)):
            if nm in names:
                return quote, dep, nm, _i(names[nm].get("symbolId")), inv
        raise CtError("CURRENCY", "%s -> %s ka rate symbol nahi mila" % (quote, dep))

    def spot_age(self, symbol_id):
        s = self.spots.get(symbol_id)
        return (time.time() - s[2]) if s else None

    # ---------- positions ----------
    def positions(self):
        """Sab khuli positions (Position list). Jawab na aaye -> CtError (MALOOM NAHI)."""
        p = self.request(PT["RECONCILE_REQ"], {"ctidTraderAccountId": self.account_id},
                         PT["RECONCILE_RES"])
        return [Position(x) for x in p.get("position") or []]

    def deals_of(self, position_id, from_ms=None, to_ms=None):
        now = int(time.time() * 1000)
        p = self.request(PT["DEAL_LIST_BY_POSITION_ID_REQ"],
                         {"ctidTraderAccountId": self.account_id, "positionId": position_id,
                          "fromTimestamp": from_ms if from_ms is not None else now - 8 * 86400 * 1000,
                          "toTimestamp": to_ms if to_ms is not None else now + 60000},
                         PT["DEAL_LIST_BY_POSITION_ID_RES"])
        return p.get("deal") or []

    # ---------- orders ----------
    def market_order(self, symbol_id, side, volume, rel_sl, rel_tp, label, comment, timeout=None):
        """MARKET order, SL/TP ke saath (relative, 1/100000).

        Lautata: ("SENT", payload) | ("REJECTED", code) | ("UNKNOWN", wajah)
          SENT     = server ne execution event diya (fill ki tasdeeq positions se)
          REJECTED = server ne SAAF inkaar kiya -> kuch nahi bana
          UNKNOWN  = jawab nahi / raabta toota -> PATA NAHI (dobara mat bhejo)
        """
        pay = {"ctidTraderAccountId": self.account_id, "symbolId": symbol_id,
               "orderType": MARKET, "tradeSide": BUY if side == "BUY" else SELL,
               "volume": int(volume), "label": label, "comment": comment,
               "relativeStopLoss": int(round(rel_sl * PRICE_SCALE)),
               "relativeTakeProfit": int(round(rel_tp * PRICE_SCALE))}
        try:
            rpt, p = self.request_any(PT["NEW_ORDER_REQ"], pay,
                                      (PT["EXECUTION_EVENT"], PT["ORDER_ERROR_EVENT"]), timeout)
        except CtError as e:
            if e.code in ("TIMEOUT", "DISCONNECTED", "NOT_CONNECTED"):
                return "UNKNOWN", e.code
            return "REJECTED", e.code                # ERROR_RES: request hi rad
        except Exception as e:                       # socket toota (send par)
            return "UNKNOWN", "%s: %s" % (type(e).__name__, e)
        if rpt == PT["ORDER_ERROR_EVENT"]:
            return "REJECTED", str(p.get("errorCode", "ORDER_ERROR"))
        if _i(p.get("executionType")) == EXEC_REJECTED:
            return "REJECTED", str(p.get("errorCode", "ORDER_REJECTED"))
        return "SENT", p

    def amend_sltp(self, position_id, sl, tp, timeout=None):
        """SL/TP absolute. True = server ne qubool kiya (tasdeeq bulane wala positions se kare)."""
        pay = {"ctidTraderAccountId": self.account_id, "positionId": position_id}
        if sl:
            pay["stopLoss"] = float(sl)
        if tp:
            pay["takeProfit"] = float(tp)
        try:
            rpt, p = self.request_any(PT["AMEND_POSITION_SLTP_REQ"], pay,
                                      (PT["EXECUTION_EVENT"], PT["ORDER_ERROR_EVENT"]), timeout)
        except Exception as e:
            return False, getattr(e, "code", str(e))
        if rpt == PT["ORDER_ERROR_EVENT"] or _i(p.get("executionType")) == EXEC_REJECTED:
            return False, str(p.get("errorCode", "REJECTED"))
        return True, "OK"

    def close_position(self, position_id, volume, timeout=None):
        pay = {"ctidTraderAccountId": self.account_id, "positionId": position_id, "volume": int(volume)}
        try:
            rpt, p = self.request_any(PT["CLOSE_POSITION_REQ"], pay,
                                      (PT["EXECUTION_EVENT"], PT["ORDER_ERROR_EVENT"]), timeout)
        except Exception as e:
            return False, getattr(e, "code", str(e))
        if rpt == PT["ORDER_ERROR_EVENT"] or _i(p.get("executionType")) == EXEC_REJECTED:
            return False, str(p.get("errorCode", "REJECTED"))
        return True, "OK"


def close_summary(deals, money_digits_default=2):
    """Band hui position ke deals -> (pnl, exit_price, close_ms, open_ms, entry_price).

    pnl = closePositionDetail.grossProfit ka jor (MT5 ke d.profit jaisa: swap /
    commission ALAG) -- bot.py ka realized_r isi par tha.
    """
    pnl, exit_px, close_ms, open_ms, entry_px = 0.0, None, 0, None, None
    for d in sorted(deals, key=lambda x: _i(x.get("executionTimestamp"))):
        if _i(d.get("dealStatus")) not in (2, 3):          # FILLED / PARTIALLY_FILLED
            continue
        cpd = d.get("closePositionDetail")
        ts = _i(d.get("executionTimestamp"))
        if cpd:
            md = _i(cpd.get("moneyDigits"), _i(d.get("moneyDigits"), money_digits_default))
            pnl += _i(cpd.get("grossProfit")) / (10.0 ** md)
            exit_px = float(d.get("executionPrice") or 0.0)
            close_ms = max(close_ms, ts)
        elif open_ms is None:
            open_ms = ts
            entry_px = float(d.get("executionPrice") or 0.0)
    return pnl, exit_px, close_ms, open_ms, entry_px
