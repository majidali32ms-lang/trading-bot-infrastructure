# fix_start_bat.py  v1  (8 Oct 2026, HANDOVER 262-C.3)
# SB ka start_bot.bat har "bot.py" wala python maarta hai -- VWAP bots (python -u bot.py) bhi.
# Yeh SIRF us aik wmic line ko badalta hai: "-u bot.py" wale (VWAP) ko chhor do.
# Bina --apply: sirf dikhata.  --apply: backup start_bot.bat.bak_vwap -> likhna -> dobara parh kar jaanch.
import sys, os, hashlib, shutil
VERSION = "fix_start_bat v1"
PATH = r"C:\trading-bot\start_bot.bat"
OLD = b"wmic process where \"CommandLine like '%%bot.py%%'\" delete >nul 2>&1"
NEW = (b"rem --- 8 Oct 2026: VWAP bots (python -u bot.py, C:\\trading-bot-vwap) ko na maaro -- HANDOVER 262-C.3\r\n"
       b"wmic process where \"CommandLine like '%%bot.py%%' and not CommandLine like '%%-u bot.py%%'\" delete >nul 2>&1")
def md5(b): return hashlib.md5(b).hexdigest()[:8]
def main():
    me = open(os.path.abspath(__file__), "rb").read()
    print(VERSION, "| script md5", md5(me))
    path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--file" else PATH
    apply = "--apply" in sys.argv
    if not os.path.exists(path):
        print("RUKA: file nahi mili:", path); return 2
    raw = open(path, "rb").read()
    print("file:", path, "| md5", md5(raw), "| satrein", raw.count(b"\n"))
    crlf = b"\r\n" in raw
    nl = b"\r\n" if crlf else b"\n"
    new = NEW if crlf else NEW.replace(b"\r\n", b"\n")
    if b"not CommandLine like" in raw:
        print("PEHLE SE LAGI HUI -- kuch nahi kiya."); return 0
    n = raw.count(OLD)
    if n != 1:
        print("RUKA: purani line %d baar mili (1 chahiye) -- kuch nahi badla." % n); return 3
    out = raw.replace(OLD, new)
    print("\nPURANI:\n  " + OLD.decode())
    print("NAYI:\n  " + new.decode().replace(nl.decode(), "\n  "))
    if not apply:
        print("\nDIKHAWA -- kuch nahi badla. Lagane ke liye: python fix_start_bat.py --apply"); return 0
    bak = path + ".bak_vwap"
    shutil.copy2(path, bak)
    open(path, "wb").write(out)
    chk = open(path, "rb").read()
    ok = (chk == out and chk.replace(new, OLD) == raw and open(bak, "rb").read() == raw)
    if not ok:
        shutil.copy2(bak, path); print("JAANCH FAIL -- backup wapas laga diya."); return 4
    print("\nLAGI. backup:", bak, "| nayi md5", md5(chk), "| jaanch PAAS (baqi file hoobahoo)")
    return 0
if __name__ == "__main__":
    sys.exit(main())
