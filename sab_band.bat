@echo off
rem sab_band.bat v1 (8 Oct 2026, HANDOVER 262-C.3) -- poora jahaz band: VWAP (DE40 + US30) + SB.
rem Sirf tab chalayein jab koi trade KHULI NA HO. Task DISABLE nahi karta (VPS restart par dono khud uthenge).
cd /d C:\trading-bot-vwap
echo ===== 1. VWAP band =====
schtasks /End /TN "VWAP watchdog"
"C:\Program Files\Python311\python.exe" run_vwap.py --stop
echo ===== 2. SB band =====
schtasks /End /TN "TradingBot"
wmic process where "CommandLine like '%%bot.py%%' and not CommandLine like '%%-u bot.py%%'" delete
timeout /t 3 /nobreak >nul
echo ===== 3. HAAL -- koi bot.py python nahi bacha hona chahiye =====
"C:\Program Files\Python311\python.exe" run_vwap.py --status
wmic process where "name='python.exe'" get ProcessId,CommandLine
pause
