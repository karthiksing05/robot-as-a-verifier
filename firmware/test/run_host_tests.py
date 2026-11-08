"""Compile the actual sketches with hardware fakes, then validate their JSON logs."""
import json
import argparse
from pathlib import Path
import shutil
import subprocess
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", choices=("mc6", "mw1"), action="append", help="Check only this independent board")
    args = parser.parse_args()
    compiler = shutil.which("g++")
    if compiler is None:
        raise SystemExit("Install g++ (C++17) and add it to PATH")
    build = ROOT / ".pio" / "host-tests"
    build.mkdir(parents=True, exist_ok=True)
    cases = []
    for board in args.board or ("mc6", "mw1"):
        cases.append((board, board, None))
        if board == "mw1":
            sketch = (ROOT / "MW1_firmware/MW1_firmware.ino").read_text(encoding="utf-8")
            pattern = r"(\b(?:const\s+)?bool\s+requireDoorClosed\s*=\s*)(true|false)(\s*;)"
            matches = list(re.finditer(pattern, sketch))
            if len(matches) != 1:
                raise SystemExit("Expected one MW-1 requireDoorClosed boolean initializer")
            opposite = "false" if matches[0][2] == "true" else "true"
            variant = build / "mw1_opposite_door_setting.ino"
            variant.write_text(re.sub(pattern, lambda m: m[1] + opposite + m[3], sketch), encoding="utf-8")
            cases.append((board, "mw1_opposite_door_setting", variant))
    for board, label, variant in cases:
        executable = build / f"{label}_test.exe"
        flags = []
        if variant:
            flags = [f'-DMW1_TEST_SKETCH="{variant.as_posix()}"', "-I", str(ROOT / "MW1_firmware")]
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "test/host/fakes"),
                        *flags,
                        str(ROOT / f"test/host/{board}_test.cpp"),
                        "-o", str(executable)], check=True)
        result = subprocess.run([str(executable)], capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(f"{label}: {result.stderr}\n{result.stdout[-2000:]}")
        events = [json.loads(line) for line in result.stdout.splitlines()]
        assert events and all(isinstance(e, dict) and "ev" in e and "t" in e for e in events)
        heartbeats = [e for e in events if e["ev"] == "hb"]
        assert heartbeats and all(len(e["display"]) == 2 for e in heartbeats)
        assert any(e["ev"] == "hello" for e in events)
        assert any(e["ev"] == "cal" for e in events)
        for event in events:
            if event["ev"].startswith("btn_"):
                assert event["v"] in (0, 1)
            if event["ev"] in ("lid", "tube", "door"):
                assert event["v"] in (0, 1) and 0 <= event["raw"] <= 1023
        max_line = max(len(line) for line in result.stdout.splitlines())
        assert max_line < 500, "Keep serial transmission below the 50 ms window"
        print(f"{label}: {result.stderr.strip()}")
        print(f"  {len(events)} valid JSON events; longest line {max_line} bytes")

    wifi_test = build / "wifi_queue_test.exe"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "test/host/fakes"),
                    str(ROOT / "test/host/wifi_queue_test.cpp"), "-o", str(wifi_test)], check=True)
    subprocess.run([str(wifi_test)], check=True, stdout=subprocess.DEVNULL)
    print("Wi-Fi queue: 450 ms press and release survive an in-flight request")


if __name__ == "__main__":
    main()
