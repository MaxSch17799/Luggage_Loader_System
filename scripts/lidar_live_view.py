#!/usr/bin/env python3
"""Live RPLIDAR C1 visualizer for the Steer Clear prototype."""

from __future__ import annotations

import argparse
import asyncio
import math
import pathlib
import queue
import random
import threading
import time
import traceback
import tomllib
from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "system_parameters.toml"


@dataclass
class Point2D:
    angle_deg: float
    x_m: float
    y_m: float
    quality: int
    timestamp_s: float


@dataclass
class GeometryMetrics:
    lip_left_x_m: float
    lip_right_x_m: float
    target_left_x_m: float
    target_right_x_m: float
    target_center_x_m: float
    target_forward_y_m: float
    center_offset_m: float
    left_clearance_m: float
    right_clearance_m: float
    live_forward_distance_m: float | None


class PointStore:
    """Keep the latest point for each angular bucket."""

    def __init__(self, ttl_s: float, bucket_deg: float) -> None:
        self.ttl_s = ttl_s
        self.bucket_deg = bucket_deg
        self._points: dict[int, Point2D] = {}

    def add(self, point: Point2D) -> None:
        bucket = int(round(point.angle_deg / self.bucket_deg))
        self._points[bucket] = point

    def active_points(self, now_s: float) -> list[Point2D]:
        return [
            point
            for point in self._points.values()
            if (now_s - point.timestamp_s) <= self.ttl_s
        ]


class RPLidarWorker(threading.Thread):
    """Background thread that reads LiDAR points and forwards them to a thread-safe queue."""

    def __init__(
        self,
        port: str,
        baudrate: int,
        timeout_s: float,
        output_queue: queue.Queue[dict[str, Any]],
        error_queue: queue.Queue[str],
    ) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.output_queue = output_queue
        self.error_queue = error_queue
        self.stop_requested = threading.Event()

    def stop(self) -> None:
        self.stop_requested.set()

    async def _copy_points(self, lidar: Any) -> None:
        while not lidar.stop_event.is_set():
            try:
                point = await asyncio.wait_for(lidar.output_queue.get(), timeout=0.2)
            except TimeoutError:
                continue
            self.output_queue.put(point)

    async def _watch_for_stop(self, lidar: Any) -> None:
        while not self.stop_requested.is_set():
            await asyncio.sleep(0.05)
        lidar.stop_event.set()

    async def _run_async(self) -> None:
        from rplidarc1 import RPLidar

        lidar = RPLidar(self.port, self.baudrate, timeout=self.timeout_s)
        try:
            async with asyncio.TaskGroup() as task_group:
                task_group.create_task(lidar.simple_scan())
                task_group.create_task(self._copy_points(lidar))
                task_group.create_task(self._watch_for_stop(lidar))
        finally:
            try:
                lidar.reset()
            except Exception:
                pass
            try:
                lidar.shutdown()
            except Exception:
                pass

    def run(self) -> None:
        try:
            asyncio.run(self._run_async())
        except Exception:
            self.error_queue.put(traceback.format_exc())


def load_config(config_path: pathlib.Path) -> dict[str, Any]:
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


def get_target_edges(config: dict[str, Any]) -> tuple[float, float]:
    target = config["target"]
    center = float(target["center_x_m"])
    half_width = float(target["opening_width_m"]) / 2.0
    left = center - half_width + float(target["left_edge_trim_m"])
    right = center + half_width + float(target["right_edge_trim_m"])
    return left, right


def compute_metrics(
    config: dict[str, Any],
    points: list[Point2D],
) -> GeometryMetrics:
    lip = config["lip"]
    guidance = config["guidance"]
    target = config["target"]

    lip_center_x = float(lip["center_x_m"])
    lip_left_x = lip_center_x - float(lip["width_m"]) / 2.0
    lip_right_x = lip_center_x + float(lip["width_m"]) / 2.0

    target_left_x, target_right_x = get_target_edges(config)
    target_center_x = float(target["center_x_m"])
    target_forward_y = float(target["forward_y_m"])

    center_offset = target_center_x - lip_center_x
    left_clearance = lip_left_x - target_left_x
    right_clearance = target_right_x - lip_right_x

    corridor_center = float(guidance["corridor_center_x_m"])
    corridor_half_width = float(guidance["corridor_half_width_m"])
    lip_tip_y = float(lip["tip_y_m"])

    live_forward_distance = None
    corridor_hits = [
        point.y_m - lip_tip_y
        for point in points
        if point.y_m >= lip_tip_y
        and abs(point.x_m - corridor_center) <= corridor_half_width
    ]
    if corridor_hits:
        live_forward_distance = min(corridor_hits)

    return GeometryMetrics(
        lip_left_x_m=lip_left_x,
        lip_right_x_m=lip_right_x,
        target_left_x_m=target_left_x,
        target_right_x_m=target_right_x,
        target_center_x_m=target_center_x,
        target_forward_y_m=target_forward_y,
        center_offset_m=center_offset,
        left_clearance_m=left_clearance,
        right_clearance_m=right_clearance,
        live_forward_distance_m=live_forward_distance,
    )


def status_label(center_offset_m: float, centered_band_m: float) -> str:
    if abs(center_offset_m) <= centered_band_m:
        return "CENTERED"
    if center_offset_m > 0:
        return "MOVE RIGHT"
    return "MOVE LEFT"


def transform_measurement_to_loader_frame(
    measurement: dict[str, Any],
    config: dict[str, Any],
    now_s: float,
) -> Point2D | None:
    filtering = config["filtering"]
    mount = config["mount"]

    distance_mm = measurement.get("d_mm")
    if distance_mm in (None, 0):
        return None

    quality = int(measurement.get("q", 0))
    if quality < int(filtering["min_quality"]):
        return None

    distance_m = float(distance_mm) / 1000.0
    if distance_m < float(filtering["min_range_m"]):
        return None
    if distance_m > float(filtering["max_range_m"]):
        return None

    angle_deg = float(measurement["a_deg"])
    angle_deg = (angle_deg + float(mount["scan_angle_offset_deg"])) % 360.0
    angle_rad = math.radians(angle_deg)

    sensor_x = float(mount["sensor_x_m"])
    sensor_y = float(mount["sensor_y_m"])

    x_m = sensor_x + distance_m * math.sin(angle_rad)
    y_m = sensor_y + distance_m * math.cos(angle_rad)

    return Point2D(
        angle_deg=angle_deg,
        x_m=x_m,
        y_m=y_m,
        quality=quality,
        timestamp_s=now_s,
    )


def simulate_points(config: dict[str, Any], now_s: float) -> list[Point2D]:
    mount = config["mount"]
    simulation = config["simulation"]
    visualization = config["visualization"]
    target = config["target"]

    sensor_x = float(mount["sensor_x_m"])
    sensor_y = float(mount["sensor_y_m"])
    target_left_x, target_right_x = get_target_edges(config)
    target_y = float(target["forward_y_m"])
    reveal_depth = float(simulation["reveal_depth_m"])
    spacing = float(simulation["wall_point_spacing_m"])
    noise = float(simulation["noise_m"])
    x_min = float(visualization["x_min_m"])
    x_max = float(visualization["x_max_m"])

    rng = random.Random(int(now_s * 10))
    points: list[Point2D] = []

    x_value = x_min
    while x_value <= x_max:
        if x_value < target_left_x or x_value > target_right_x:
            x_noisy = x_value + rng.uniform(-noise, noise)
            y_noisy = target_y + rng.uniform(-noise, noise)
            points.append(
                cartesian_to_point(
                    x_noisy,
                    y_noisy,
                    50,
                    now_s,
                    sensor_x,
                    sensor_y,
                )
            )
        x_value += spacing

    y_value = target_y
    while y_value <= (target_y + reveal_depth):
        left_noisy = target_left_x + rng.uniform(-noise, noise)
        right_noisy = target_right_x + rng.uniform(-noise, noise)
        y_noisy = y_value + rng.uniform(-noise, noise)
        points.append(
            cartesian_to_point(left_noisy, y_noisy, 55, now_s, sensor_x, sensor_y)
        )
        points.append(
            cartesian_to_point(right_noisy, y_noisy, 55, now_s, sensor_x, sensor_y)
        )
        y_value += spacing

    for _ in range(int(simulation["background_clutter_points"])):
        x_noisy = rng.uniform(x_min, x_max)
        y_noisy = rng.uniform(0.5, float(visualization["y_max_m"]))
        points.append(
            cartesian_to_point(x_noisy, y_noisy, 10, now_s, sensor_x, sensor_y)
        )

    return points


def cartesian_to_point(
    x_m: float,
    y_m: float,
    quality: int,
    now_s: float,
    sensor_x: float,
    sensor_y: float,
) -> Point2D:
    rel_x = x_m - sensor_x
    rel_y = y_m - sensor_y
    angle_deg = math.degrees(math.atan2(rel_x, rel_y)) % 360.0
    return Point2D(
        angle_deg=angle_deg,
        x_m=x_m,
        y_m=y_m,
        quality=quality,
        timestamp_s=now_s,
    )


def build_plot(config: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.canvas.manager.set_window_title("Steer Clear LiDAR Live View")

    visualization = config["visualization"]
    lip = config["lip"]
    guidance = config["guidance"]
    mount = config["mount"]

    ax.set_xlim(float(visualization["x_min_m"]), float(visualization["x_max_m"]))
    ax.set_ylim(float(visualization["y_min_m"]), float(visualization["y_max_m"]))
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("x (m)  positive = right side of belt")
    ax.set_ylabel("y (m)  positive = forward toward aircraft")
    ax.set_title("Steer Clear RPLIDAR C1 Visualizer")

    point_artist = ax.scatter([], [], s=int(visualization["point_size"]), alpha=0.8)
    sensor_artist = ax.scatter(
        [float(mount["sensor_x_m"])],
        [float(mount["sensor_y_m"])],
        marker="x",
        s=80,
        color="tab:red",
        label="LiDAR mount",
    )
    _ = sensor_artist

    lip_left_x = float(lip["center_x_m"]) - float(lip["width_m"]) / 2.0
    lip_right_x = float(lip["center_x_m"]) + float(lip["width_m"]) / 2.0
    lip_tip_y = float(lip["tip_y_m"])
    ax.plot(
        [lip_left_x, lip_right_x],
        [lip_tip_y, lip_tip_y],
        color="tab:green",
        linewidth=4,
        label="Loader lip",
    )

    target_left_x, target_right_x = get_target_edges(config)
    target_forward_y = float(config["target"]["forward_y_m"])
    ax.plot(
        [target_left_x, target_right_x],
        [target_forward_y, target_forward_y],
        color="tab:orange",
        linewidth=4,
        label="Configured target opening",
    )
    ax.axvline(
        float(config["target"]["center_x_m"]),
        color="tab:orange",
        linestyle="--",
        alpha=0.7,
        label="Target centerline",
    )
    ax.axvline(
        float(lip["center_x_m"]),
        color="tab:green",
        linestyle=":",
        alpha=0.7,
        label="Lip centerline",
    )

    corridor_center = float(guidance["corridor_center_x_m"])
    corridor_half_width = float(guidance["corridor_half_width_m"])
    corridor_patch = Rectangle(
        (corridor_center - corridor_half_width, lip_tip_y),
        2.0 * corridor_half_width,
        float(visualization["y_max_m"]) - lip_tip_y,
        fill=False,
        linestyle="--",
        linewidth=1.5,
        edgecolor="tab:blue",
        alpha=0.6,
        label="Forward-distance corridor",
    )
    ax.add_patch(corridor_patch)
    ax.legend(loc="upper right")

    text_artist = fig.text(0.02, 0.02, "", family="monospace", fontsize=10)
    return fig, ax, point_artist, text_artist


def format_metrics(metrics: GeometryMetrics, config: dict[str, Any]) -> str:
    centered_band_m = float(config["guidance"]["centered_band_m"])
    lines = [
        f"Status               : {status_label(metrics.center_offset_m, centered_band_m)}",
        f"Center offset        : {metrics.center_offset_m * 1000:7.1f} mm",
        f"Left clearance       : {metrics.left_clearance_m * 1000:7.1f} mm",
        f"Right clearance      : {metrics.right_clearance_m * 1000:7.1f} mm",
        f"Configured target y  : {metrics.target_forward_y_m * 1000:7.1f} mm",
    ]
    if metrics.live_forward_distance_m is None:
        lines.append("Live forward return  :    no hit in corridor")
    else:
        lines.append(
            f"Live forward return  : {metrics.live_forward_distance_m * 1000:7.1f} mm"
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Steer Clear RPLIDAR C1 live viewer")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the TOML parameter file",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run without hardware using the mock scene from the parameter sheet",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=0.0,
        help="Optional auto-stop duration for testing",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = pathlib.Path(args.config).expanduser().resolve()
    config = load_config(config_path)

    point_store = PointStore(
        ttl_s=float(config["visualization"]["point_ttl_s"]),
        bucket_deg=float(config["visualization"]["angle_bucket_deg"]),
    )

    measurement_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    error_queue: queue.Queue[str] = queue.Queue()
    worker: RPLidarWorker | None = None

    if not args.simulate:
        worker = RPLidarWorker(
            port=str(config["serial"]["port"]),
            baudrate=int(config["serial"]["baudrate"]),
            timeout_s=float(config["serial"]["timeout_s"]),
            output_queue=measurement_queue,
            error_queue=error_queue,
        )
        worker.start()

    fig, _ax, point_artist, text_artist = build_plot(config)
    plt.show(block=False)

    console_interval_s = float(config["console"]["print_interval_s"])
    update_period_s = float(config["visualization"]["update_period_s"])
    start_s = time.monotonic()
    last_console_print_s = 0.0

    try:
        while True:
            now_s = time.monotonic()

            if worker is not None and not error_queue.empty():
                raise RuntimeError(error_queue.get_nowait())

            if args.simulate:
                for point in simulate_points(config, now_s):
                    point_store.add(point)
            else:
                while True:
                    try:
                        measurement = measurement_queue.get_nowait()
                    except queue.Empty:
                        break
                    point = transform_measurement_to_loader_frame(
                        measurement,
                        config,
                        now_s,
                    )
                    if point is not None:
                        point_store.add(point)

            active_points = point_store.active_points(now_s)
            if active_points:
                point_artist.set_offsets([[p.x_m, p.y_m] for p in active_points])
            else:
                point_artist.set_offsets([])

            metrics = compute_metrics(config, active_points)
            metrics_text = format_metrics(metrics, config)
            text_artist.set_text(metrics_text)

            if (now_s - last_console_print_s) >= console_interval_s:
                print("")
                print(metrics_text)
                last_console_print_s = now_s

            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            plt.pause(update_period_s)

            if args.duration_seconds > 0 and (now_s - start_s) >= args.duration_seconds:
                break
            if not plt.fignum_exists(fig.number):
                break
    finally:
        if worker is not None:
            worker.stop()
            worker.join(timeout=2.0)


if __name__ == "__main__":
    main()

