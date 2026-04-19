#!/usr/bin/env python3
"""Run a quick local verification pass before claiming the demo is ready."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import tomllib
import importlib.util
import shutil


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


def check_parameter_autosave() -> None:
    module_path = PROJECT_ROOT / "scripts" / "lidar_live_view.py"
    spec = importlib.util.spec_from_file_location("lidar_live_view_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load lidar_live_view.py for autosave verification")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory(prefix="steer_clear_self_check_") as temp_dir:
        temp_config_path = pathlib.Path(temp_dir) / "system_parameters.toml"
        shutil.copy2(CONFIG_PATH, temp_config_path)

        original_config = module.load_config(temp_config_path)
        original_target = float(original_config["target"]["center_x_m"])
        new_target = round(original_target + 0.123, 6)

        module.save_config_value(temp_config_path, ("target", "center_x_m"), new_target)
        module.save_config_value(temp_config_path, ("mount", "side"), "left")

        updated_config = module.load_config(temp_config_path)

        if float(updated_config["target"]["center_x_m"]) != new_target:
            raise RuntimeError("target.center_x_m did not persist to the TOML file")
        if str(updated_config["mount"]["side"]) != "left":
            raise RuntimeError("mount.side toggle did not persist to the TOML file")


def main() -> int:
    try:
        print(f"[self-check] project root: {PROJECT_ROOT}")

        with CONFIG_PATH.open("rb") as config_file:
            config = tomllib.load(config_file)
        print(
            "[self-check] config loaded successfully for port "
            f"{config['serial']['port']}"
        )

        print("")
        print("[self-check] Parameter autosave smoke test")
        check_parameter_autosave()
        print("[self-check] parameter autosave works on a temporary config copy")

        run_step(
            "Python syntax compile",
            [
                sys.executable,
                "-m",
                "py_compile",
                "scripts/lidar_live_view.py",
                "scripts/lidar_web_ui.py",
                "scripts/show_serial_ports.py",
                "scripts/lidar_diagnostics.py",
                "scripts/self_check.py",
            ],
        )

        run_step(
            "Browser UI smoke test",
            [
                sys.executable,
                "scripts/lidar_web_ui.py",
                "--simulate",
                "--smoke-test",
                "--no-browser",
            ],
            env={**os.environ, "MPLBACKEND": "Agg"},
        )

        run_step(
            "Legacy viewer smoke test",
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
