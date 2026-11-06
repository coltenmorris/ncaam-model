"""
Set up (or remove) the automatic daily runs in Windows Task Scheduler.

Run this ONCE from PyCharm (right-click > Run 'setup_daily_tasks'), using the
same project interpreter you use for main.py. It creates one task per time in
config.DAILY_RUN_TIMES under Task Scheduler > Task Scheduler Library > NCAAM Model.

  python setup_daily_tasks.py            create / update the daily tasks
  python setup_daily_tasks.py --status   show when they last ran / run next
  python setup_daily_tasks.py --run-now  run the model once right now via the task
  python setup_daily_tasks.py --remove   delete the daily tasks

Notes
- Runs only while you're signed in to Windows (no password needed).
- If the computer was off or asleep at a run time, the task runs as soon as
  it's back on.
- Each run writes a log to output/logs. The dashboard is
  output/NCAAM_Dashboard.xlsx. If it's open in Excel during a run, that
  update is saved as a separate timestamped copy.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402

FOLDER = "NCAAM Model"


def task_name(t: str) -> str:
    return f"\\{FOLDER}\\Daily {t.replace(':', '')}"


def pythonw() -> str:
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def task_xml(t: str) -> str:
    hh, mm = t.split(":")
    main_py = ROOT / "main.py"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>NCAAM Model daily update ({escape(t)}): grades picks, pulls ratings, schedule and odds, updates the dashboard.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{date.today():%Y-%m-%d}T{int(hh):02d}:{int(mm):02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(pythonw())}</Command>
      <Arguments>"{escape(str(main_py))}" --scheduled</Arguments>
      <WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def schtasks(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True)


def create() -> None:
    for t in config.DAILY_RUN_TIMES:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
            f.write(task_xml(t))
            xml_path = f.name
        r = schtasks("/Create", "/TN", task_name(t), "/XML", xml_path, "/F")
        Path(xml_path).unlink(missing_ok=True)
        if r.returncode == 0:
            print(f"Scheduled daily run at {t}  ({task_name(t)})")
        else:
            print(f"Could not create the {t} task:\n{r.stderr or r.stdout}")
    print(f"\nPython used: {pythonw()}")
    print(f"Project:     {ROOT}")
    print("Dashboard:   output\\NCAAM_Dashboard.xlsx    Logs: output\\logs")


def remove() -> None:
    r = schtasks("/Query", "/FO", "CSV", "/NH")
    names = {line.split('","')[0].strip('"') for line in r.stdout.splitlines()
             if f"\\{FOLDER}\\" in line}
    for t in config.DAILY_RUN_TIMES:
        names.add(task_name(t))
    for n in sorted(names):
        r = schtasks("/Delete", "/TN", n, "/F")
        print(("Removed " if r.returncode == 0 else "Not found: ") + n)


def status() -> None:
    for t in config.DAILY_RUN_TIMES:
        r = schtasks("/Query", "/TN", task_name(t), "/V", "/FO", "LIST")
        if r.returncode != 0:
            print(f"{task_name(t)}: not set up")
            continue
        keep = ("TaskName", "Next Run Time", "Last Run Time", "Last Result", "Status")
        for line in r.stdout.splitlines():
            if line.split(":")[0].strip() in keep:
                print("  " + line.strip())
        print()
    print("Last Result 0 = success. Details for each run are in output\\logs.")


def run_now() -> None:
    t = config.DAILY_RUN_TIMES[0]
    r = schtasks("/Run", "/TN", task_name(t))
    print(r.stdout or r.stderr)
    print("Started. Check output\\logs and output\\NCAAM_Dashboard.xlsx in a minute.")


def main() -> int:
    if not sys.platform.startswith("win"):
        print("This setup script is for Windows Task Scheduler.")
        return 1
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--run-now", action="store_true")
    a = ap.parse_args()
    if a.remove:
        remove()
    elif a.status:
        status()
    elif a.run_now:
        run_now()
    else:
        create()
    return 0


if __name__ == "__main__":
    sys.exit(main())
