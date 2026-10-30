# -*- coding: utf-8 -*-
"""
keys_bharo.py -- 7 Oct 2026 (HANDOVER 262). C:\\trading-bot-vwap\\ctrader_keys.json bharta hai.

Chaaron cheezein CHHUPE input se (screen par nahi dikhtin): client_id, client_secret, access_token,
refresh_token. Sirf is folder ki ctrader_keys.json mein likhta hai -- koi backup, koi log, koi aur file
NAHI; screen par sirf "bhara / khaali" (qeemat ya lambai kabhi nahi). demo = true, trader_login 1234567.
Token: openapi.ctrader.com -> Applications -> Sandbox (Playground), scope "Account info and trading".

    cd C:\\trading-bot-vwap && python keys_bharo.py
(Notepad mein mat kholo, output file mein mat bhejo -- seedha cmd mein chalao; paste ke baad Enter.)
Phir: cd C:\\trading-bot-vwap && (python ctrader_check.py) > ctrader_check.txt 2>&1 & notepad ctrader_check.txt
"""
import getpass
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "ctrader_keys.json")
LOGIN = 1234567
FIELDS = (("client_id", "Client ID"), ("client_secret", "Client Secret"),
          ("access_token", "Access token"), ("refresh_token", "Refresh token"))


def ask(prompt, secret_input=getpass.getpass, plain_input=input):
    vals = {}
    for k, nm in FIELDS:
        for _ in range(3):
            v = (secret_input("%s (chhupa -- paste kar ke Enter): " % nm) or "").strip().strip('"').strip("'")
            if v and " " not in v and len(v) >= 8:
                vals[k] = v
                print("   %s: bhara" % nm)
                break
            print("   %s: khaali / ghalat shakl (space ya bohot chhota) -- dobara" % nm)
        else:
            return None
    if vals["access_token"] == vals["refresh_token"]:
        print("   Access aur Refresh token EK jaise -- ghalat paste? kuch nahi likha.")
        return None
    return vals


def main(secret_input=getpass.getpass, plain_input=input, path=PATH):
    print("keys_bharo.py -- %s" % path)
    print("Qeematein screen par NAHI dikhengi. Chat / notepad mein KABHI mat daalna.\n")
    if os.path.exists(path):
        a = (plain_input("ctrader_keys.json pehle se hai -- NAYI se badal doon? (haan / nahi): ") or "").strip().lower()
        if a not in ("haan", "h", "yes", "y"):
            print("Kuch nahi badla.")
            return 1
    vals = ask("", secret_input, plain_input)
    if vals is None:
        print("Kuch nahi likha.")
        return 1
    keys = dict(vals, demo=True, trader_login=LOGIN)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keys, fh, indent=2)
    os.replace(tmp, path)
    for k in list(vals):
        vals[k] = None
    print("\nLIKH DIYA: %s (demo, trader_login %d)." % (path, LOGIN))
    print("Agla: cd C:\\trading-bot-vwap && (python ctrader_check.py) > ctrader_check.txt 2>&1 & notepad ctrader_check.txt")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
