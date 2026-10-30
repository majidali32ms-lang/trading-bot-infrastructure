# -*- coding: utf-8 -*-
"""
make_task_xml.py -- 9 Oct 2026 (HANDOVER 262-D). "VWAP watchdog" Task ki XML banata hai: vwap_task.xml
(UTF-16 LE + BOM, CRLF -- schtasks /XML yahi shakl leta hai). SIRF file banata hai, koi Task NAHI banata.

  Trigger   BootTrigger (At startup)
  Principal SYSTEM (S-1-5-18), HighestAvailable  -- "run whether logged on or not", password nahi
  Action    C:\\Program Files\\Python311\\python.exe  run_vwap.py   (Start in C:\\trading-bot-vwap)
  Settings  IgnoreNew | RestartOnFailure PT1M x 999 | ExecutionTimeLimit PT0S (warna 72 ghante baad band) |
            batteries false | StartWhenAvailable false | Enabled FALSE (qadam 6 tak band)

    python make_task_xml.py        -> vwap_task.xml (+ vps_vwap\\vwap_task.xml)
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = r"C:\Program Files\Python311\python.exe"
WORKDIR = r"C:\trading-bot-vwap"

XML = r"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>VWAP watchdog -- run_vwap.py (DE40 + US30 cTrader demo). HANDOVER 260 / 262-D. TradingBot se ALAG.</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>false</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>%s</Command>
      <Arguments>run_vwap.py</Arguments>
      <WorkingDirectory>%s</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
""" % (PYTHON, WORKDIR)


def build(path):
    data = XML.replace("\r\n", "\n").replace("\n", "\r\n")
    with open(path, "wb") as fh:
        fh.write(b"\xff\xfe" + data.encode("utf-16-le"))
    return path


if __name__ == "__main__":
    p = build(os.path.join(HERE, "vwap_task.xml"))
    out = os.path.join(HERE, "vps_vwap")
    if os.path.isdir(out):
        shutil.copy(p, os.path.join(out, "vwap_task.xml"))
    print("bana:", p)
    sys.exit(0)
