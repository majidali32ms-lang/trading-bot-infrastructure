@echo off
rem sab_chalu.bat v1 (8 Oct 2026, HANDOVER 262-C.3) -- poora jahaz chalu: SB + VWAP (DE40 + US30).
rem "VWAP watchdog" task DISABLE ho (qadam 6 se pehle) to us ki line ERROR degi -- theek hai, SB phir bhi chalega.
cd /d C:\trading-bot-vwap
echo ===== 1. SB chalu =====
schtasks /Run /TN "TradingBot"
timeout /t 10 /nobreak >nul
echo ===== 2. VWAP chalu =====
schtasks /Run /TN "VWAP watchdog"
timeout /t 20 /nobreak >nul
echo ===== 3. HAAL =====
"C:\Program Files\Python311\python.exe" run_vwap.py --status
wmic process where "name='python.exe'" get ProcessId,CommandLine
pause
