# -*- coding: utf-8 -*-
"""
run_vwap.py -- 6 Oct 2026 (HANDOVER 260). VWAP bots ka WATCHDOG (C:\\trading-bot-vwap).

Har symbol (DE40, US30) apna ALAG process: `python bot.py` us ke folder mein (bot.py bd901c0f
HOOBAHOO + MetaTrader5.py shim + strategy.py adapter). Aik gire to SIRF wahi dobara chalta hai;
doosra aur live SB bot (C:\\trading-bot) ko koi asar nahi. SB ko yeh file CHHOOTI BHI NAHI.

  * crash -> Telegram + dobara chalao; 10 min mein 5 crash -> 10 min ruko + Telegram
  * atka hua bot (last_alive.json 5 min purani) -> band kar ke dobara
  * aik waqt mein aik watchdog (run_vwap.lock); watchdog khud restart ho to CHALTE bots ko
    apna leta hai (PID + process ke shuru ka waqt) -- doosri copy KABHI nahi chalata
  * shuru se pehle md5: bot.py == bd901c0f aur engine files == MANIFEST.json, warna woh
    symbol NAHI chalta (+ Telegram)
  * 1 mahine ki hadd (HANDOVER 258.31): mahine ka R < stop_month_r -> us symbol ki config mein
    "strategy_enabled": false (bot.py har chakkar parhta hai -> nayi entry band, khuli trade
    apni SL/TP par) + Telegram. Dobara chalana Majid ka faisla: config mein true kar dein --
    usi mahine watchdog dobara band NAHI karega.

    python run_vwap.py            chalao (Task Scheduler: VPS start par)
    python run_vwap.py --status   kaun chal raha hai
    python run_vwap.py --stop     sab VWAP bots band (SB ko haath nahi)
"""
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

VERSION = "run_vwap v1 -- 6 Oct 2026"
ROOT = os.path.dirname(os.path.abspath(__file__))
BOT_MD5 = "bd901c0f"
ENGINE = ("MetaTrader5.py", "strategy.py", "ctrader_link.py", "ctrader_trade.py", "strategy_vwap.py")
OPTIONAL = ("news_shadow.py", "news_dates.txt")        # MANIFEST mein ho tabhi laazmi (bot.py ise na mile to chup chalta hai)
DEFAULTS = {"symbols": ["DE40", "US30"], "python": "", "check_sec": 10, "stale_alive_sec": 300,
            "crash_window_sec": 600, "crash_max": 5, "crash_pause_sec": 600, "month_check_sec": 300,
            "stop_month_r": {"DE40": -12.5, "US30": -14.4}}


def md5_8(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    except OSError:
        return None


def load_json(path, default=None):
    """Na ho, ya adhoori likhi ho (bot.py last_alive.json seedha likhta hai) -> default."""
    try:
        with io.open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------- processes (Windows + baqi)
def proc_start_time(pid):
    """Process ke shuru hone ka waqt (PID dobara istemal hone se bachao). Na ho -> None."""
    if not pid:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000 | 0x00100000, False, int(pid))  # QUERY_LIMITED | SYNCHRONIZE
        if not h:
            return None
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:
                return None
            c, e, k, u = (wintypes.FILETIME() for _ in range(4))
            if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
                return None
            return (c.dwHighDateTime << 32) | c.dwLowDateTime
        finally:
            k32.CloseHandle(h)
    try:
        with open("/proc/%d/stat" % int(pid)) as fh:
            return int(fh.read().rsplit(")", 1)[1].split()[19])
    except Exception:
        return None


def kill(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(int(pid), 9)
        except OSError:
            pass


class FileLock(object):
    def __init__(self, path):
        self.path, self.fh = path, None

    def acquire(self):
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self.fh = fh
        return True


# ---------------------------------------------------------------- watchdog
class Watchdog(object):
    def __init__(self, root=ROOT, conf=None, log=None, telegram=None, bot_md5=None, clock=time.time):
        self.root = root
        c = dict(DEFAULTS)
        c.update(conf if conf is not None else (load_json(os.path.join(root, "run_vwap.json"), {}) or {}))
        self.c = c
        self._log = log
        self._tg = telegram
        self.clock = clock
        self.python = c.get("python") or sys.executable
        self.state_path = os.path.join(root, "run_vwap_state.json")
        self.st = load_json(self.state_path, {}) or {}
        self.kids = {}                 # sym -> dict(pid, start, popen, restarts[], paused_until, bad)
        self.manifest = load_json(os.path.join(root, "MANIFEST.json"), {}) or {}
        # bot.py ka md5: MANIFEST se (bot.py patch -- v4.36 report -- par sirf MANIFEST badalta), warna bd901c0f
        self.bot_md5 = bot_md5 or self.manifest.get("bot.py") or BOT_MD5
        self.last_month = 0.0

    # ---------- log / telegram ----------
    def log(self, msg):
        line = "[%s] [WATCHDOG] %s" % (datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d %H:%M:%S"), msg)
        if self._log:
            self._log(line)
            return
        print(line, flush=True)
        try:
            with io.open(os.path.join(self.root, "run_vwap.log"), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    def telegram(self, sym, text):
        text = "[WATCHDOG %s] %s" % (sym, text)
        cfg = load_json(os.path.join(self.root, sym, "config.json"), {}) or {}
        if self._tg is not None:
            self._tg(sym, text, cfg.get("telegram_chat_id"))
            return
        tok, chat = cfg.get("telegram_token"), cfg.get("telegram_chat_id")
        if not tok or not chat:
            return
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data, timeout=10).read()
        except Exception as e:
            self.log("Telegram nahi gaya (%s): %s" % (sym, type(e).__name__))

    def save(self):
        try:
            save_json(self.state_path, self.st)
        except OSError as e:
            self.log("state likh nahi saka: %s" % e)

    # ---------- jaanch ----------
    def check_files(self, sym):
        """Masle ki fehrist -- khaali = chalao."""
        d = os.path.join(self.root, sym)
        bad = []
        if md5_8(os.path.join(d, "bot.py")) != self.bot_md5:
            bad.append("bot.py ka md5 %s (chahiye %s)" % (md5_8(os.path.join(d, "bot.py")), self.bot_md5))
        for f in ENGINE + tuple(o for o in OPTIONAL if o in self.manifest):
            want = self.manifest.get(f)
            got = md5_8(os.path.join(d, f))
            if got is None:
                bad.append("%s nahi mili" % f)
            elif want and got != want:
                bad.append("%s md5 %s (MANIFEST %s)" % (f, got, want))
        cfg = load_json(os.path.join(d, "config.json"))
        if cfg is None:
            bad.append("config.json nahi (config_NAMOONA.json se banayein)")
        else:
            if cfg.get("symbol") != sym:
                bad.append("config symbol %r -- folder %s" % (cfg.get("symbol"), sym))
            if int(cfg.get("magic_number", 0)) != 19990102:
                bad.append("magic %r -- 19990102 chahiye" % cfg.get("magic_number"))
            if not str(cfg.get("telegram_token", "")).strip():
                bad.append("telegram_token khaali -- VWAP %s bot ka token config.json mein daalein" % sym)
            if not str(cfg.get("secret_key", "")).strip():
                bad.append("secret_key khaali -- webhook ka raaz daalein (koi bhi lamba lafz)")
            if cfg.get("mt5_login"):
                bad.append("mt5_login bhara hai -- VWAP MT5 par NAHI chalta")
            if (cfg.get("ctrader") or {}).get("url") and not self.c.get("allow_test_url"):
                bad.append("ctrader.url sirf tests ke liye -- VPS par hata dein")
        return bad

    # ---------- process ----------
    def _pidfile(self, sym):
        return os.path.join(self.root, sym, "watchdog_pid.json")

    def adopt_or_start(self, sym):
        pf = load_json(self._pidfile(sym))
        if pf and pf.get("pid") and proc_start_time(pf["pid"]) == pf.get("start"):
            self.kids[sym] = dict(pid=pf["pid"], start=pf["start"], popen=None,
                                  restarts=self.kids.get(sym, {}).get("restarts", []), paused_until=0.0)
            self.log("%s pehle se chal raha (PID %s) -- apna liya, doosri copy NAHI" % (sym, pf["pid"]))
            return
        self.start(sym)

    def start(self, sym):
        bad = self.check_files(sym)
        k = self.kids.setdefault(sym, dict(pid=None, start=None, popen=None, restarts=[], paused_until=0.0))
        if bad:
            if not k.get("bad"):
                self.log("%s NAHI chalaya: %s" % (sym, "; ".join(bad)))
                self.telegram(sym, "bot NAHI chalaya -- " + "; ".join(bad))
            k["bad"] = bad
            return False
        k["bad"] = None
        d = os.path.join(self.root, sym)
        logf = open(os.path.join(d, "bot.log"), "ab")
        flags = 0x00000200 if os.name == "nt" else 0       # CREATE_NEW_PROCESS_GROUP
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        p = subprocess.Popen([self.python, "-u", "bot.py"], cwd=d, stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, creationflags=flags)
        logf.close()
        st = None
        for _ in range(50):
            st = proc_start_time(p.pid)
            if st:
                break
            time.sleep(0.05)
        k.update(pid=p.pid, start=st, popen=p, started_at=self.clock())
        save_json(self._pidfile(sym), {"pid": p.pid, "start": st, "since": self.clock()})
        self.log("%s chalaya (PID %d)" % (sym, p.pid))
        return True

    def alive(self, sym):
        k = self.kids.get(sym) or {}
        if not k.get("pid"):
            return False
        if k.get("popen") is not None and k["popen"].poll() is not None:
            return False
        return proc_start_time(k["pid"]) == k.get("start")

    def exit_code(self, sym):
        p = (self.kids.get(sym) or {}).get("popen")
        return p.poll() if p is not None else None

    def stale(self, sym):
        k = self.kids.get(sym) or {}
        p = os.path.join(self.root, sym, "last_alive.json")
        if os.path.exists(p) and load_json(p) is None:
            return False                       # adhoori likhi file -- agle chakkar dekho, faisla nahi
        a = load_json(p)
        try:
            ts = datetime.fromisoformat(a["ts"]).timestamp()
        except Exception:
            ts = None
        since = k.get("started_at") or 0
        ref = ts if (ts and ts >= since) else since
        return bool(ref) and self.clock() - ref > float(self.c["stale_alive_sec"])

    def restart(self, sym, why):
        k = self.kids[sym]
        now = self.clock()
        k["restarts"] = [t for t in k["restarts"] if now - t < float(self.c["crash_window_sec"])] + [now]
        if len(k["restarts"]) >= int(self.c["crash_max"]):
            k["paused_until"] = now + float(self.c["crash_pause_sec"])
            k["restarts"] = []
            self.log("%s: %d crash %d min mein -- %d min RUK raha" % (sym, int(self.c["crash_max"]),
                     int(self.c["crash_window_sec"]) // 60, int(self.c["crash_pause_sec"]) // 60))
            self.telegram(sym, "%s -- %d baar gira %d min mein. %d min ruk kar phir koshish. bot.log dekhein."
                          % (why, int(self.c["crash_max"]), int(self.c["crash_window_sec"]) // 60,
                             int(self.c["crash_pause_sec"]) // 60))
            return
        self.log("%s: %s -- dobara chala raha" % (sym, why))
        self.telegram(sym, "%s -- dobara chala raha hoon" % why)
        self.start(sym)

    def tick(self):
        now = self.clock()
        for sym in self.c["symbols"]:
            k = self.kids.get(sym)
            if k is None:
                self.adopt_or_start(sym)
                continue
            if k.get("bad"):
                if self.check_files(sym) == []:
                    self.start(sym)
                continue
            if now < k.get("paused_until", 0):
                continue
            if not self.alive(sym):
                code = self.exit_code(sym)
                self.restart(sym, "bot band ho gaya" + (" (exit %s)" % code if code is not None else ""))
            elif self.stale(sym):
                self.log("%s atka hua (last_alive purana) -- band kar raha" % sym)
                kill(k["pid"])
                time.sleep(1)
                self.restart(sym, "bot ATKA hua tha (5 min se zinda hone ka nishan nahi)")
        if now - self.last_month >= float(self.c["month_check_sec"]):
            self.last_month = now
            for sym in self.c["symbols"]:
                try:
                    self.month_check(sym)
                except Exception as e:
                    self.log("%s mahina jaanch nakaam: %s" % (sym, e))

    # ---------- 1 mahine ki hadd ----------
    def month_r(self, sym, month):
        p = os.path.join(self.root, sym, "trades.csv")
        if not os.path.exists(p):
            return 0.0
        tot = 0.0
        with io.open(p, newline="", encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                if str(r.get("closed_at", "")).startswith(month) and r.get("realized_r") not in ("", None):
                    try:
                        tot += float(r["realized_r"])
                    except ValueError:
                        pass
        return tot

    def month_check(self, sym):
        month = datetime.fromtimestamp(self.clock()).strftime("%Y-%m")
        lim = float((self.c.get("stop_month_r") or {}).get(sym, -999))
        mr = self.month_r(sym, month)
        done = self.st.setdefault("month_stop", {})
        if mr >= lim or done.get(sym) == month:
            return
        cp = os.path.join(self.root, sym, "config.json")
        cfg = load_json(cp)
        if cfg is None:
            return
        cfg["strategy_enabled"] = False
        save_json(cp, cfg)
        done[sym] = month
        self.save()
        self.log("%s: %s ka R %.1f < hadd %.1f -- strategy_enabled false" % (sym, month, mr, lim))
        self.telegram(sym, "[MAHINA HADD] %s ka R %.1f < hadd %.1f -- %s ki NAYI entry BAND (config "
                           "strategy_enabled false). Khuli trade apni SL/TP par. Dobara chalana Majid ka "
                           "faisla: config mein true kar dein." % (month, mr, lim, sym))

    # ---------- chalana ----------
    def run(self):
        lk = FileLock(os.path.join(self.root, "run_vwap.lock"))
        if not lk.acquire():
            print("run_vwap pehle se chal raha hai (run_vwap.lock) -- yeh copy band.")
            return 2
        self.log("%s shuru | symbols %s | python %s" % (VERSION, ", ".join(self.c["symbols"]), self.python))
        while True:
            try:
                self.tick()
            except Exception as e:
                self.log("tick crash: %s: %s" % (type(e).__name__, e))
            time.sleep(float(self.c["check_sec"]))

    def status(self):
        out = []
        for sym in self.c["symbols"]:
            pf = load_json(self._pidfile(sym)) or {}
            up = pf.get("pid") and proc_start_time(pf["pid"]) == pf.get("start")
            out.append("%-5s %s (PID %s) | md5 masle: %s" % (sym, "CHAL RAHA" if up else "BAND", pf.get("pid"),
                                                           "; ".join(self.check_files(sym)) or "koi nahi"))
        return out

    def stop_all(self):
        for sym in self.c["symbols"]:
            pf = load_json(self._pidfile(sym)) or {}
            if pf.get("pid") and proc_start_time(pf["pid"]) == pf.get("start"):
                kill(pf["pid"])
                self.log("%s band kiya (PID %s)" % (sym, pf["pid"]))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    w = Watchdog()
    if "--status" in sys.argv:
        print("\n".join(w.status()))
        return 0
    if "--stop" in sys.argv:
        w.stop_all()
        print("VWAP bots band (watchdog chal raha ho to woh bhi band karein: Task Scheduler).")
        return 0
    return w.run()


if __name__ == "__main__":
    sys.exit(main())
