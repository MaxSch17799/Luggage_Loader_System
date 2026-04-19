#!/usr/bin/env python3
"""Beginner-friendly diagnostics for the Steer Clear LiDAR setup."""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import platform
import sys
import tomllib
import traceback

import serial
from serial.tools import list_ports


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "system_parameters.toml"


def load_config(config_path: pathlib.Path) -> dict:
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


def print_header(title: str) -> None:
    print("")
    print("=" * 72)
    print(title)
    print("=" * 72)


def print_serial_ports() -> None:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    for port in ports:
        print(f"Device      : {port.device}")
        print(f"Description : {port.description}")
        print(f"HWID        : {port.hwid}")
        print("-" * 72)


async def collect_points_for_seconds(lidar, seconds: float) -> int:
    count = 0
    started = asyncio.get_running_loop().time()
    scan_task = asyncio.create_task(lidar.simple_scan())
    try:
        while (asyncio.get_running_loop().time() - started) < seconds:
            if scan_task.done():
                exception = scan_task.exception()
                if exception is not None:
                    raise exception
                break
            try:
                await asyncio.wait_for(lidar.output_queue.get(), timeout=0.25)
                count += 1
            except TimeoutError:
                pass
        return count
    finally:
        lidar.stop_event.set()
        await asyncio.sleep(0.2)
        scan_task.cancel()
        try:
            await scan_task
        except BaseException:
            pass


async def run_live_check(port: str, baudrate: int, timeout_s: float, seconds: float) -> int:
    from rplidarc1 import RPLidar

    lidar = RPLidar(port, baudrate, timeout=timeout_s)
    try:
        return await collect_points_for_seconds(lidar, seconds)
    finally:
        try:
            lidar.reset()
        except Exception:
            pass
        try:
            lidar.shutdown()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Steer Clear LiDAR diagnostics")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the TOML parameter file",
    )
    parser.add_argument(
        "--skip-live-check",
        action="store_true",
        help="Only run non-invasive checks",
    )
    parser.add_argument(
        "--live-check-seconds",
        type=float,
        default=2.0,
        help="How long to collect live LiDAR points",
    )
    args = parser.parse_args()

    try:
        config_path = pathlib.Path(args.config).expanduser().resolve()
        config = load_config(config_path)
        serial_cfg = config["serial"]
        port = str(serial_cfg["port"])
        baudrate = int(serial_cfg["baudrate"])
        timeout_s = float(serial_cfg["timeout_s"])

        print_header("Environment")
        print(f"Python               : {sys.version.split()[0]}")
        print(f"Platform             : {platform.platform()}")
        print(f"Config file          : {config_path}")
        print(f"Configured port      : {port}")
        print(f"Configured baudrate  : {baudrate}")
        print(f"Configured timeout   : {timeout_s}")

        print_header("Serial Ports")
        print_serial_ports()

        print_header("Configured Port Checks")
        print(f"Path exists          : {pathlib.Path(port).exists()}")
        print(f"Readable             : {os.access(port, os.R_OK)}")
        print(f"Writable             : {os.access(port, os.W_OK)}")

        print("")
        print("Trying basic pyserial open/close...")
        test_serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout_s)
        test_serial.close()
        print("Basic serial open/close succeeded.")

        if args.skip_live_check:
            print("")
            print("Skipped live LiDAR protocol check by request.")
            return 0

        print_header("Live LiDAR Protocol Check")
        print("Attempting RPLIDAR health/startup and a short point capture...")
        point_count = asyncio.run(
            run_live_check(
                port=port,
                baudrate=baudrate,
                timeout_s=timeout_s,
                seconds=args.live_check_seconds,
            )
        )
        print(f"Live point count     : {point_count}")
        if point_count <= 0:
            print("No live points were received during the check.")
            print("")
            print("Likely causes to investigate next:")
            print("- the sensor is detected as USB serial but not producing valid scan packets")
            print("- the sensor model/protocol behavior does not fully match the current Python package")
            print("- the sensor is powered but not actually scanning")
            print("- the baud rate or serial framing is wrong")
            print("- the USB/UART adapter path is adding corrupted bytes")
            return 2
        print("Live LiDAR check succeeded.")
        return 0

    except Exception:
        print("")
        print("Diagnostics failed with an exception.")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
