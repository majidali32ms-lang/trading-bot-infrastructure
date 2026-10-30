# -*- coding: utf-8 -*-
"""
chat_id_nikalo.py -- 5 Oct 2026. Telegram GROUP ki chat id nikalo, NAYE VWAP bot ke token se.

- Token CHUPA hua maangta hai (screen par nahi dikhta), kahin likha / save NAHI hota.
- Purane SB bot ka token KABHI mat dein (woh chal raha hai -- getUpdates takrayega).
- Sirf PARHTA hai: getMe + getUpdates. Koi paighaam nahi bhejta, kuch nahi badalta.

Pehle: naya VWAP bot group mein add karein, phir group mein likhein:  /start@<naye_bot_ka_username>
Phir (PC terminal mein):  python chat_id_nikalo.py
"""
import getpass
import json
import sys
import urllib.error
import urllib.request

API = "https://api.telegram.org/bot%s/%s"


def call(token, method):
    """-> (ok, natija ya wajah). Ghalti ke paighaam mein token KABHI nahi aata."""
    try:
        with urllib.request.urlopen(API % (token, method), timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "token ghalat hai (401) -- BotFather se dobara copy karein"
        if e.code == 409:
            return False, "is bot par webhook / doosra getUpdates chal raha hai (409) -- yeh NAYA bot hona chahiye"
        return False, "Telegram ne HTTP %d diya" % e.code
    except urllib.error.URLError:
        return False, "internet / Telegram tak raabta nahi hua"
    except Exception as e:
        return False, "nakaam: %s" % type(e).__name__
    if not d.get("ok"):
        return False, "Telegram ne inkaar kiya: %s" % str(d.get("description", ""))[:100]
    return True, d.get("result")


def groups_from(updates):
    """getUpdates ke natije se group / supergroup chats: {id: (type, title)} + migrate notes."""
    found, moved = {}, []
    for u in updates or []:
        for key in ("message", "edited_message", "my_chat_member", "chat_member", "channel_post"):
            obj = u.get(key)
            if not isinstance(obj, dict):
                continue
            ch = obj.get("chat") or {}
            if ch.get("type") in ("group", "supergroup"):
                found[ch.get("id")] = (ch.get("type"), ch.get("title", ""))
            if obj.get("migrate_to_chat_id"):
                moved.append((ch.get("id"), obj["migrate_to_chat_id"]))
    return found, moved


def main(token=None, out=print):
    if token is None:
        token = getpass.getpass("NAYE VWAP bot ka token (screen par nahi dikhega): ").strip()
    if not token or ":" not in token:
        out("Token khaali / adhoora -- kuch nahi kiya.")
        return 1
    ok, me = call(token, "getMe")
    if not ok:
        out("getMe: " + me)
        return 1
    out("Bot: @%s  (yahi NAYA VWAP bot hona chahiye -- SB wala NAHI)" % me.get("username", "?"))
    ok, ups = call(token, "getUpdates")
    if not ok:
        out("getUpdates: " + ups)
        return 1
    found, moved = groups_from(ups)
    if not found:
        out("Koi group nahi mila. Bot ko group mein add karein, group mein likhein:")
        out("   /start@%s" % me.get("username", "<bot>"))
        out("phir yeh script dobara chalayein (Telegram sirf pichhle 24 ghante ke updates rakhta hai).")
        return 2
    out("\nGROUP(S):")
    for cid, (typ, title) in found.items():
        out("   chat id %s   | %s | %s" % (cid, typ, title))
    for old, new in moved:
        out("   DHYAN: group %s supergroup ban gaya -> NAYI id %s (yahi istemal karein)" % (old, new))
    out("\nconfig mein:  \"telegram_chat_id\": \"<upar wali id, manfi nishan ke saath>\"")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
