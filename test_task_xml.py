# -*- coding: utf-8 -*-
"""
test_task_xml.py -- 9 Oct 2026 (HANDOVER 262-D). vwap_task.xml ki jaanch: BOM, UTF-16 LE, CRLF, XML parse,
aur har setting ki ASAL value (file se parh kar) + matlooba se milaan. Koi Task NAHI banata.

    python test_task_xml.py [file]
"""
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
WANT = [
    ("Trigger: BootTrigger (At startup)", "t:Triggers/t:BootTrigger/t:Enabled", "true"),
    ("Principal UserId (SYSTEM)", "t:Principals/t:Principal/t:UserId", "S-1-5-18"),
    ("Principal RunLevel", "t:Principals/t:Principal/t:RunLevel", "HighestAvailable"),
    ("Action Command", "t:Actions/t:Exec/t:Command", r"C:\Program Files\Python311\python.exe"),
    ("Action Arguments", "t:Actions/t:Exec/t:Arguments", "run_vwap.py"),
    ("Action WorkingDirectory", "t:Actions/t:Exec/t:WorkingDirectory", r"C:\trading-bot-vwap"),
    ("MultipleInstancesPolicy", "t:Settings/t:MultipleInstancesPolicy", "IgnoreNew"),
    ("RestartOnFailure Interval", "t:Settings/t:RestartOnFailure/t:Interval", "PT1M"),
    ("RestartOnFailure Count", "t:Settings/t:RestartOnFailure/t:Count", "999"),
    ("ExecutionTimeLimit (PT0S = koi hadd nahi)", "t:Settings/t:ExecutionTimeLimit", "PT0S"),
    ("DisallowStartIfOnBatteries", "t:Settings/t:DisallowStartIfOnBatteries", "false"),
    ("StopIfGoingOnBatteries", "t:Settings/t:StopIfGoingOnBatteries", "false"),
    ("StartWhenAvailable", "t:Settings/t:StartWhenAvailable", "false"),
    ("Settings Enabled (bante hi BAND)", "t:Settings/t:Enabled", "false"),
    ("AllowStartOnDemand (qadam 6 par Run)", "t:Settings/t:AllowStartOnDemand", "true"),
    ("Priority (Windows default)", "t:Settings/t:Priority", "7"),
]


def check(path, out=print):
    res = []

    def ok(name, cond, extra=""):
        res.append(bool(cond))
        out(("PAAS " if cond else "FAIL ") + name + (("   [%s]" % extra) if extra else ""))

    raw = open(path, "rb").read()
    ok("BOM UTF-16 LE (FF FE)", raw[:2] == b"\xff\xfe", raw[:4].hex())
    try:
        text = raw[2:].decode("utf-16-le")
        dec = True
    except UnicodeDecodeError as e:
        text, dec = "", False
    ok("UTF-16 LE decode", dec)
    ok("line endings sirf CRLF (koi akela LF nahi)", text.count("\n") > 0 and text.count("\n") == text.count("\r\n"),
       "CRLF %d / LF %d" % (text.count("\r\n"), text.count("\n")))
    ok("declaration encoding=\"UTF-16\"", text.startswith('<?xml version="1.0" encoding="UTF-16"?>'))
    try:
        root = ET.fromstring(raw)
        ok("XML parse (task schema namespace)", root.tag == "{%s}Task" % NS["t"], root.tag)
    except ET.ParseError as e:
        ok("XML parse", False, str(e))
        return res
    out("\n   %-42s %-38s %s" % ("setting", "file mein ASAL value", "natija"))
    for name, xp, want in WANT:
        el = root.find(xp, NS)
        got = el.text if el is not None else None
        good = got == want
        res.append(good)
        out("   %-42s %-38s %s" % (name, got, "THEEK" if good else "*** GHALAT (chahiye %s) ***" % want))
    n_trig = len(list(root.find("t:Triggers", NS)))
    n_act = len(root.findall("t:Actions/t:Exec", NS))
    ok("sirf AIK trigger (BootTrigger) aur AIK action", n_trig == 1 and n_act == 1, "triggers %d actions %d" % (n_trig, n_act))
    ok("koi LogonType / Password NAHI (SYSTEM ko password nahi chahiye)",
       root.find("t:Principals/t:Principal/t:LogonType", NS) is None and "Password" not in text)
    ok("TradingBot / bot.py ka zikr NAHI (SB task se ALAG)", "TradingBot se ALAG" in text
       and "bot.py" not in text and "trading-bot\\" not in text.replace("trading-bot-vwap", ""))
    return res


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "vwap_task.xml")
    print("vwap_task.xml jaanch: %s" % p)
    r = check(p)
    print("\nKUL: %d / %d PAAS" % (sum(r), len(r)))
    sys.exit(0 if all(r) else 1)
