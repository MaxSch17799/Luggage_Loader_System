#!/usr/bin/env python3
"""Run a quick local verification pass before claiming the demo is ready."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tomllib


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "system_parameters.toml"


def run_step(name: str, command: list[str], env: dict[str, str] | None = None) -> None:
    print("")
    print(f"[self-check] {name}")
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {name}")


def main() -> int:
    try:
        print(f"[self-check] project root: {PROJECT_ROOT}")

        with CONFIG_PATH.open("rb") as config_file:
            config = tomllib.load(config_file)
        print(
            "[self-check] config loaded successfully for port "
            f"{config['serial']['port']}"
        )

        run_step(
            "Python syntax compile",
            [
                sys.executable,
                "-m",
                "py_compile",
                "scripts/lidar_live_view.py",
                "scripts/show_serial_ports.py",
                "scripts/lidar_diagnostics.py",
                "scripts/self_check.py",
            ],
        )

        run_step(
            "Simulated viewer smoke test",
            [
                sys.executable,
                "scripts/lidar_live_view.py",
                "--simulate",
                "--duration-seconds",
                "1",
            ],
            env={**os.environ, "MPLBACKEND": "Agg"},
        )

        run_step(
            "Diagnostics smoke test",
            [
                sys.executable,
                "scripts/lidar_diagnostics.py",
                "--skip-live-check",
            ],
        )

        print("")
        print("[self-check] all checks passed")
        return 0
    except Exception as exc:
        print("")
        print(f"[self-check] failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
