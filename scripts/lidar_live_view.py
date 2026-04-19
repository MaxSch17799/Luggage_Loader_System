#!/usr/bin/env python3
"""Live RPLIDAR C1 visualizer for the Steer Clear prototype."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import pathlib
import queue
import random
import re
import threading
import time
import traceback
import tomllib
from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.backend_bases import KeyEvent
from matplotlib.patches import Rectangle
import numpy as np
import serial

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:
    tk = None
    ttk = None


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "system_parameters.toml"


PARAMETER_ORDER = [
    ("mount", "side"),
    ("mount", "sensor_x_m"),
    ("mount", "sensor_y_m"),
    ("mount", "sensor_z_m"),
    ("mount", "scan_angle_offset_deg"),
    ("mount", "pitch_deg"),
    ("lip", "center_x_m"),
    ("lip", "tip_y_m"),
    ("lip", "width_m"),
    ("target", "center_x_m"),
    ("target", "opening_width_m"),
    ("target", "forward_y_m"),
    ("target", "left_edge_trim_m"),
    ("target", "right_edge_trim_m"),
    ("guidance", "corridor_center_x_m"),
    ("guidance", "corridor_half_width_m"),
    ("guidance", "centered_band_m"),
    ("filtering", "min_quality"),
    ("filtering", "min_range_m"),
    ("filtering", "max_range_m"),
    ("visualization", "x_min_m"),
    ("visualization", "x_max_m"),
    ("visualization", "y_min_m"),
    ("visualization", "y_max_m"),
    ("visualization", "point_ttl_s"),
    ("visualization", "angle_bucket_deg"),
    ("visualization", "update_period_s"),
    ("visualization", "point_size"),
    ("console", "print_interval_s"),
    ("simulation", "enabled"),
    ("simulation", "reveal_depth_m"),
    ("simulation", "wall_point_spacing_m"),
    ("simulation", "noise_m"),
    ("simulation", "background_clutter_points"),
]


PARAMETER_METADATA: dict[tuple[str, str], dict[str, Any]] = {
    ("mount", "side"): {
        "allowed_values": ["left", "right"],
        "description": "Informational mount side label for the LiDAR position.",
    },
    ("mount", "sensor_x_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "LiDAR position left/right. Positive is right of belt centerline.",
    },
    ("mount", "sensor_y_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.10,
        "description": "LiDAR position fore/aft. Negative is behind the lip tip plane.",
    },
    ("mount", "sensor_z_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "LiDAR height above the belt.",
    },
    ("mount", "scan_angle_offset_deg"): {
        "fine_step": 0.5,
        "coarse_step": 5.0,
        "description": "Rotates the scan into the loader frame.",
    },
    ("mount", "pitch_deg"): {
        "fine_step": 0.5,
        "coarse_step": 2.0,
        "description": "Placeholder pitch parameter for future 3D-aware logic.",
    },
    ("lip", "center_x_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "Lip centerline in the loader frame.",
    },
    ("lip", "tip_y_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "Lip tip plane in the loader frame.",
    },
    ("lip", "width_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "Usable lip width.",
    },
    ("target", "center_x_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "Target opening centerline.",
    },
    ("target", "opening_width_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "Opening width for the mock docking target.",
    },
    ("target", "forward_y_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.10,
        "description": "Forward target distance from the lip tip plane.",
    },
    ("target", "left_edge_trim_m"): {
        "fine_step": 0.005,
        "coarse_step": 0.02,
        "description": "Asymmetric trim for the left target edge.",
    },
    ("target", "right_edge_trim_m"): {
        "fine_step": 0.005,
        "coarse_step": 0.02,
        "description": "Asymmetric trim for the right target edge.",
    },
    ("guidance", "corridor_center_x_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "Center of the forward-distance corridor.",
    },
    ("guidance", "corridor_half_width_m"): {
        "fine_step": 0.01,
        "coarse_step": 0.05,
        "description": "Half-width of the forward-distance corridor.",
    },
    ("guidance", "centered_band_m"): {
        "fine_step": 0.005,
        "coarse_step": 0.02,
        "description": "How close to zero offset counts as CENTERED.",
    },
    ("simulation", "enabled"): {
        "description": "Enable or disable fake scene generation in simulate mode.",
    },
}


SECTION_RE = re.compile(r"^\s*\[(?P<section>[^\]]+)\]\s*$")
ASSIGNMENT_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_]+)(?P<eq>\s*=\s*).*$")


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


@dataclass
class ParameterSpec:
    section: str
    key: str
    description: str
    fine_step: float | int | None
    coarse_step: float | int | None
    allowed_values: list[Any] | None = None

    @property
    def path(self) -> tuple[str, str]:
        return self.section, self.key

    @property
    def label(self) -> str:
        return f"{self.section}.{self.key}"


class PointStore:
    """Keep the latest point for each angular bucket."""

    def __init__(self, ttl_s: float, bucket_deg: float) -> None:
        self.ttl_s = ttl_s
        self.bucket_deg = bucket_deg
        self._points: dict[int, Point2D] = {}

    def clear(self) -> None:
        self._points.clear()

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


class LiveParameterEditor:
    """Live parameter browser/editor that writes changes back to the TOML sheet."""

    def __init__(self, config_path: pathlib.Path, config: dict[str, Any]) -> None:
        self.config_path = config_path
        self.config = config
        self.specs = build_parameter_specs(config)
        self.index = 0
        self.show_help = True
        self.panel_enabled = False
        self.status_message = "Editor ready. Changes autosave to the TOML file."
        self.last_saved_path: tuple[str, str] | None = None

    def selected_spec(self) -> ParameterSpec:
        return self.specs[self.index]

    def move_selection(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.specs)
        self.status_message = f"Selected {self.selected_spec().label}"

    def reload_from_file(self) -> None:
        self.config = load_config(self.config_path)
        self.specs = build_parameter_specs(self.config)
        self.index = min(self.index, len(self.specs) - 1)
        self.status_message = "Reloaded parameter sheet from disk."

    def select_path(self, path: tuple[str, str]) -> None:
        for index, spec in enumerate(self.specs):
            if spec.path == path:
                self.index = index
                return

    def toggle_help(self) -> None:
        self.show_help = not self.show_help
        self.status_message = "Toggled editor help."

    def toggle_selected(self) -> bool:
        spec = self.selected_spec()
        current = get_config_value(self.config, spec.path)
        if spec.allowed_values:
            allowed = spec.allowed_values
            current_index = allowed.index(current)
            new_value = allowed[(current_index + 1) % len(allowed)]
        elif isinstance(current, bool):
            new_value = not current
        else:
            self.status_message = f"{spec.label} is numeric. Use arrows to edit it."
            return False

        self._save_value(spec, new_value)
        return True

    def adjust_selected(self, direction: int, coarse: bool) -> bool:
        spec = self.selected_spec()
        current = get_config_value(self.config, spec.path)

        if spec.allowed_values or isinstance(current, bool):
            self.status_message = f"{spec.label} is toggle-based. Press t to toggle."
            return False

        step = spec.coarse_step if coarse else spec.fine_step
        if step is None:
            self.status_message = f"{spec.label} has no step configured."
            return False

        if isinstance(current, int) and not isinstance(current, bool):
            new_value = int(current + int(step) * direction)
        elif isinstance(current, float):
            new_value = round(current + float(step) * direction, 6)
        else:
            self.status_message = f"{spec.label} is not editable with arrows."
            return False

        self._save_value(spec, new_value)
        return True

    def _save_value(self, spec: ParameterSpec, value: Any) -> None:
        set_config_value(self.config, spec.path, value)
        save_config_value(self.config_path, spec.path, value)
        self.select_path(spec.path)
        self.last_saved_path = spec.path
        self.status_message = f"Saved {spec.label} = {format_value_for_display(value)}"

    def adjust_path(self, path: tuple[str, str], direction: int, coarse: bool) -> bool:
        self.select_path(path)
        return self.adjust_selected(direction, coarse)

    def set_value_from_text(self, path: tuple[str, str], raw_text: str) -> bool:
        self.select_path(path)
        spec = self.selected_spec()
        current = get_config_value(self.config, spec.path)
        text = raw_text.strip()

        try:
            if spec.allowed_values:
                normalized_lookup = {str(value).lower(): value for value in spec.allowed_values}
                candidate = normalized_lookup[text.lower()]
            elif isinstance(current, bool):
                bool_lookup = {
                    "true": True,
                    "false": False,
                    "1": True,
                    "0": False,
                    "yes": True,
                    "no": False,
                    "on": True,
                    "off": False,
                }
                candidate = bool_lookup[text.lower()]
            elif isinstance(current, int) and not isinstance(current, bool):
                candidate = int(text)
            elif isinstance(current, float):
                candidate = float(text)
            else:
                candidate = text
        except Exception:
            self.status_message = (
                f"Could not parse {spec.label} from '{raw_text}'. "
                "Check the value format and try again."
            )
            return False

        self._save_value(spec, candidate)
        return True

    def render_text(self) -> str:
        spec = self.selected_spec()
        selected_value = get_config_value(self.config, spec.path)

        lines = [
            "Parameter Editing",
            "Autosave: ON",
            f"Config: {self.config_path.name}",
            "",
        ]

        if self.panel_enabled:
            lines.extend(
                [
                    "Use the separate Parameter Panel window.",
                    "Click fields, type values, and press Enter",
                    "or click away to apply changes live.",
                    "",
                    f"Last edited: {spec.label}",
                    f"Value      : {format_value_for_display(selected_value)}",
                    "",
                    "Fallback keys still work if needed:",
                    "[ ]  previous/next",
                    "left/right or a/d  fine -/+",
                    "down/up or s/w     coarse -/+",
                    "t toggle, r reload, c clear",
                ]
            )
        else:
            lines.extend(
                [
                    "Parameter panel window was not opened.",
                    "Keyboard fallback is active.",
                    "",
                    f"Selected: {spec.label}",
                    f"Value   : {format_value_for_display(selected_value)}",
                    f"Fine    : {format_step(spec.fine_step)}",
                    f"Coarse  : {format_step(spec.coarse_step)}",
                    "",
                    "Keys",
                    "[ ] , . p n   previous / next parameter",
                    "left/right a d - +   fine - / +",
                    "down/up w s         coarse - / +",
                    "t             toggle bool/enum",
                    "r             reload TOML from disk",
                    "c             clear plotted points",
                ]
            )

        lines.extend(["", f"Last action: {self.status_message}"])
        return "\n".join(lines)


class LiveParameterPanel:
    """Clickable Tk-based parameter form that edits the live TOML-backed config."""

    def __init__(self, editor: LiveParameterEditor, point_store: PointStore) -> None:
        self.editor = editor
        self.point_store = point_store
        self.window: Any | None = None
        self.enabled = False
        self.closed = False
        self._last_sync_s = 0.0
        self._suspend_widget_events = False
        self.field_vars: dict[tuple[str, str], Any] = {}
        self.field_widgets: dict[tuple[str, str], Any] = {}
        self.status_var: Any | None = None

        if tk is None or ttk is None:
            self.editor.panel_enabled = False
            self.editor.status_message = (
                "Tk parameter panel unavailable on this system. Keyboard fallback active."
            )
            return

        if "agg" in plt.get_backend().lower():
            self.editor.panel_enabled = False
            self.editor.status_message = (
                "Clickable parameter panel skipped on non-interactive matplotlib backend."
            )
            return

        try:
            parent = getattr(tk, "_default_root", None)
            if parent is None:
                self.window = tk.Tk()
            else:
                self.window = tk.Toplevel(parent)
            self.window.title("Steer Clear Live Parameter Panel")
            self.window.geometry("1080x820")
            self.window.minsize(860, 480)
            self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        except Exception:
            self.editor.panel_enabled = False
            self.editor.status_message = (
                "Could not open the clickable parameter panel. Keyboard fallback active."
            )
            self.window = None
            return

        self._build_ui()
        self.sync_from_editor(force=True)
        self.enabled = True
        self.editor.panel_enabled = True
        self.editor.status_message = (
            "Clickable parameter panel opened. Edit fields there; changes autosave live."
        )

    def _on_close(self) -> None:
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
        self.enabled = False
        self.closed = True
        self.editor.panel_enabled = False
        self.editor.status_message = "Parameter panel closed. Keyboard fallback is still available."

    def _bind_mousewheel(self, widget: Any, canvas: Any) -> None:
        def on_mousewheel(event: Any) -> None:
            if hasattr(event, "delta") and event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")
            elif getattr(event, "num", None) == 4:
                canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(1, "units")

        widget.bind("<MouseWheel>", on_mousewheel)
        widget.bind("<Button-4>", on_mousewheel)
        widget.bind("<Button-5>", on_mousewheel)

    def _build_ui(self) -> None:
        assert self.window is not None

        outer = ttk.Frame(self.window, padding=10)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 8))

        ttk.Label(
            header,
            text="Steer Clear Live Parameters",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(side="left")

        ttk.Button(header, text="Reload From TOML", command=self.reload_from_disk).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(header, text="Clear Points", command=self.clear_points).pack(
            side="right", padx=(8, 0)
        )

        ttk.Label(
            outer,
            text=(
                "Click into any field, edit the value, then press Enter or click away. "
                "Changes apply live and are written to config/system_parameters.toml."
            ),
            wraplength=1000,
            justify="left",
        ).pack(fill="x", pady=(0, 8))

        canvas_frame = ttk.Frame(outer)
        canvas_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._bind_mousewheel(canvas, canvas)
        self._bind_mousewheel(scrollable, canvas)

        specs_by_section: dict[str, list[ParameterSpec]] = {}
        for spec in self.editor.specs:
            specs_by_section.setdefault(spec.section, []).append(spec)

        for section_name, section_specs in specs_by_section.items():
            section_frame = ttk.LabelFrame(
                scrollable,
                text=section_name,
                padding=10,
            )
            section_frame.pack(fill="x", expand=True, pady=(0, 8))
            section_frame.columnconfigure(5, weight=1)

            row_index = 0
            for spec in section_specs:
                current_value = get_config_value(self.editor.config, spec.path)
                var = tk.StringVar(value=format_value_for_input(current_value))
                self.field_vars[spec.path] = var

                ttk.Label(
                    section_frame,
                    text=spec.key,
                    width=24,
                ).grid(row=row_index, column=0, sticky="w", padx=(0, 8), pady=(2, 2))

                if spec.allowed_values or isinstance(current_value, bool):
                    values = (
                        [str(value) for value in spec.allowed_values]
                        if spec.allowed_values
                        else ["true", "false"]
                    )
                    widget = ttk.Combobox(
                        section_frame,
                        textvariable=var,
                        values=values,
                        state="readonly",
                        width=16,
                    )
                    widget.bind(
                        "<<ComboboxSelected>>",
                        lambda _event, path=spec.path: self.apply_path(path),
                    )
                    widget.grid(row=row_index, column=1, sticky="w", padx=(0, 8))
                else:
                    widget = ttk.Entry(section_frame, textvariable=var, width=18)
                    widget.bind(
                        "<Return>",
                        lambda _event, path=spec.path: self.apply_path(path),
                    )
                    widget.bind(
                        "<FocusOut>",
                        lambda _event, path=spec.path: self.apply_path(path),
                    )
                    widget.grid(row=row_index, column=1, sticky="w", padx=(0, 8))

                    ttk.Button(
                        section_frame,
                        text="-",
                        width=3,
                        command=lambda path=spec.path: self.nudge_path(path, -1, False),
                    ).grid(row=row_index, column=2, padx=(0, 4))
                    ttk.Button(
                        section_frame,
                        text="+",
                        width=3,
                        command=lambda path=spec.path: self.nudge_path(path, 1, False),
                    ).grid(row=row_index, column=3, padx=(0, 4))
                    ttk.Button(
                        section_frame,
                        text="--",
                        width=4,
                        command=lambda path=spec.path: self.nudge_path(path, -1, True),
                    ).grid(row=row_index, column=4, padx=(0, 4))
                    ttk.Button(
                        section_frame,
                        text="++",
                        width=4,
                        command=lambda path=spec.path: self.nudge_path(path, 1, True),
                    ).grid(row=row_index, column=5, sticky="w", padx=(0, 8))

                self.field_widgets[spec.path] = widget

                ttk.Label(
                    section_frame,
                    text=spec.description,
                    wraplength=700,
                    justify="left",
                    foreground="#555555",
                ).grid(
                    row=row_index + 1,
                    column=0,
                    columnspan=6,
                    sticky="w",
                    padx=(0, 8),
                    pady=(0, 8),
                )
                row_index += 2

        self.status_var = tk.StringVar(value=self.editor.status_message)
        ttk.Label(
            outer,
            textvariable=self.status_var,
            wraplength=1000,
            justify="left",
        ).pack(fill="x", pady=(8, 0))

    def clear_points(self) -> None:
        self.point_store.clear()
        self.editor.status_message = "Cleared all plotted points from the parameter panel."

    def reload_from_disk(self) -> None:
        self.editor.reload_from_file()
        self.point_store.clear()
        self.sync_from_editor(force=True)

    def apply_path(self, path: tuple[str, str]) -> None:
        if self._suspend_widget_events:
            return

        variable = self.field_vars[path]
        raw_text = str(variable.get())
        if self.editor.set_value_from_text(path, raw_text):
            self.point_store.clear()
            self.sync_from_editor(force=True)
        elif self.status_var is not None:
            self.status_var.set(self.editor.status_message)

    def nudge_path(self, path: tuple[str, str], direction: int, coarse: bool) -> None:
        if self.editor.adjust_path(path, direction, coarse):
            self.point_store.clear()
            self.sync_from_editor(force=True)

    def sync_from_editor(self, force: bool = False) -> None:
        if not self.enabled or self.window is None:
            return

        self._suspend_widget_events = True
        try:
            for spec in self.editor.specs:
                path = spec.path
                if path not in self.field_vars:
                    continue
                widget = self.field_widgets[path]
                try:
                    focused_widget = self.window.focus_get()
                except Exception:
                    focused_widget = None

                if not force and focused_widget is widget:
                    continue

                current_value = get_config_value(self.editor.config, path)
                self.field_vars[path].set(format_value_for_input(current_value))
        finally:
            self._suspend_widget_events = False

        if self.status_var is not None:
            self.status_var.set(self.editor.status_message)

    def poll(self) -> None:
        if not self.enabled or self.window is None:
            return

        now_s = time.monotonic()
        if (now_s - self._last_sync_s) >= 0.25:
            self.sync_from_editor(force=False)
            self._last_sync_s = now_s

        try:
            self.window.update_idletasks()
            self.window.update()
        except Exception:
            self.enabled = False
            self.closed = True
            self.editor.panel_enabled = False
            self.editor.status_message = (
                "Parameter panel closed or failed. Keyboard fallback remains available."
            )


def load_config(config_path: pathlib.Path) -> dict[str, Any]:
    with config_path.open("rb") as config_file:
        return tomllib.load(config_file)


def iter_leaf_paths(config: dict[str, Any]) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    for section_name, section_values in config.items():
        if not isinstance(section_values, dict):
            continue
        for key in section_values:
            paths.append((section_name, key))
    return paths


def heuristic_steps(key: str, value: Any) -> tuple[float | int | None, float | int | None]:
    if isinstance(value, bool):
        return None, None
    if isinstance(value, int):
        return 1, 5
    if isinstance(value, float):
        if key.endswith("_deg"):
            return 0.5, 5.0
        if key.endswith("_s"):
            return 0.05, 0.25
        if key.endswith("_m"):
            return 0.01, 0.10
        return 0.10, 0.50
    return None, None


def build_parameter_specs(config: dict[str, Any]) -> list[ParameterSpec]:
    config_paths = iter_leaf_paths(config)
    ordered_paths = [path for path in PARAMETER_ORDER if path in config_paths]
    remaining_paths = sorted(path for path in config_paths if path not in PARAMETER_ORDER)
    combined_paths = ordered_paths + remaining_paths

    specs: list[ParameterSpec] = []
    for section, key in combined_paths:
        if section in {"metadata", "serial"}:
            continue
        value = config[section][key]
        metadata = PARAMETER_METADATA.get((section, key), {})
        fine_step, coarse_step = heuristic_steps(key, value)
        specs.append(
            ParameterSpec(
                section=section,
                key=key,
                description=metadata.get(
                    "description",
                    f"Editable value for {section}.{key}.",
                ),
                fine_step=metadata.get("fine_step", fine_step),
                coarse_step=metadata.get("coarse_step", coarse_step),
                allowed_values=metadata.get("allowed_values"),
            )
        )
    return specs


def get_config_value(config: dict[str, Any], path: tuple[str, str]) -> Any:
    section, key = path
    return config[section][key]


def set_config_value(config: dict[str, Any], path: tuple[str, str], value: Any) -> None:
    section, key = path
    config[section][key] = value


def format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        formatted = f"{value:.6f}".rstrip("0").rstrip(".")
        if "." not in formatted:
            formatted += ".0"
        return formatted
    raise TypeError(f"Unsupported TOML value type: {type(value)!r}")


def save_config_value(config_path: pathlib.Path, path: tuple[str, str], value: Any) -> None:
    section_name, key_name = path
    lines = config_path.read_text(encoding="utf-8").splitlines()
    current_section: str | None = None

    for index, line in enumerate(lines):
        section_match = SECTION_RE.match(line)
        if section_match:
            current_section = section_match.group("section")
            continue

        if current_section != section_name:
            continue

        assignment_match = ASSIGNMENT_RE.match(line)
        if assignment_match and assignment_match.group("key") == key_name:
            lines[index] = (
                f"{assignment_match.group('indent')}"
                f"{key_name}"
                f"{assignment_match.group('eq')}"
                f"{format_toml_value(value)}"
            )
            config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

    raise KeyError(f"Could not find {section_name}.{key_name} in {config_path}")


def format_value_for_display(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def format_value_for_input(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def format_step(value: float | int | None) -> str:
    if value is None:
        return "toggle"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


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
    if not bool(config["simulation"]["enabled"]):
        return []

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


def build_plot(config: dict[str, Any]) -> tuple[Any, Any, dict[str, Any]]:
    fig, ax = plt.subplots(figsize=(13, 8))
    if hasattr(fig.canvas.manager, "set_window_title"):
        fig.canvas.manager.set_window_title("Steer Clear LiDAR Live View")
    fig.subplots_adjust(left=0.08, right=0.76, bottom=0.08, top=0.92)

    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.3)
    ax.set_xlabel("x (m)  positive = right side of belt")
    ax.set_ylabel("y (m)  positive = forward toward aircraft")
    ax.set_title("Steer Clear RPLIDAR C1 Visualizer")

    artists: dict[str, Any] = {}
    artists["points"] = ax.scatter(
        [],
        [],
        s=int(config["visualization"]["point_size"]),
        alpha=0.8,
    )
    artists["sensor"] = ax.scatter(
        [0.0],
        [0.0],
        marker="x",
        s=80,
        color="tab:red",
        label="LiDAR mount",
    )
    (artists["lip_line"],) = ax.plot(
        [],
        [],
        color="tab:green",
        linewidth=4,
        label="Loader lip",
    )
    (artists["target_line"],) = ax.plot(
        [],
        [],
        color="tab:orange",
        linewidth=4,
        label="Configured target opening",
    )
    artists["target_centerline"] = ax.axvline(
        0.0,
        color="tab:orange",
        linestyle="--",
        alpha=0.7,
        label="Target centerline",
    )
    artists["lip_centerline"] = ax.axvline(
        0.0,
        color="tab:green",
        linestyle=":",
        alpha=0.7,
        label="Lip centerline",
    )
    corridor_patch = Rectangle(
        (0.0, 0.0),
        0.1,
        0.1,
        fill=False,
        linestyle="--",
        linewidth=1.5,
        edgecolor="tab:blue",
        alpha=0.6,
        label="Forward-distance corridor",
    )
    artists["corridor"] = corridor_patch
    ax.add_patch(corridor_patch)
    artists["metrics_text"] = fig.text(
        0.02,
        0.02,
        "",
        family="monospace",
        fontsize=10,
        va="bottom",
        bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "#dddddd"},
    )
    artists["editor_text"] = fig.text(
        0.79,
        0.10,
        "",
        family="monospace",
        fontsize=9,
        va="bottom",
        bbox={"facecolor": "white", "alpha": 0.90, "edgecolor": "#cccccc"},
    )
    artists["status_text"] = fig.text(
        0.79,
        0.95,
        "",
        family="monospace",
        fontsize=9,
        va="top",
        color="tab:blue",
        bbox={"facecolor": "white", "alpha": 0.90, "edgecolor": "#cccccc"},
    )
    ax.legend(loc="upper right")
    update_geometry_artists(ax, artists, config)
    return fig, ax, artists


def update_geometry_artists(ax: Any, artists: dict[str, Any], config: dict[str, Any]) -> None:
    visualization = config["visualization"]
    lip = config["lip"]
    target = config["target"]
    guidance = config["guidance"]
    mount = config["mount"]

    ax.set_xlim(float(visualization["x_min_m"]), float(visualization["x_max_m"]))
    ax.set_ylim(float(visualization["y_min_m"]), float(visualization["y_max_m"]))

    artists["sensor"].set_offsets(
        [[float(mount["sensor_x_m"]), float(mount["sensor_y_m"])]]
    )

    lip_left_x = float(lip["center_x_m"]) - float(lip["width_m"]) / 2.0
    lip_right_x = float(lip["center_x_m"]) + float(lip["width_m"]) / 2.0
    lip_tip_y = float(lip["tip_y_m"])
    artists["lip_line"].set_data([lip_left_x, lip_right_x], [lip_tip_y, lip_tip_y])

    target_left_x, target_right_x = get_target_edges(config)
    target_forward_y = float(target["forward_y_m"])
    artists["target_line"].set_data(
        [target_left_x, target_right_x],
        [target_forward_y, target_forward_y],
    )

    target_center_x = float(target["center_x_m"])
    lip_center_x = float(lip["center_x_m"])
    artists["target_centerline"].set_xdata([target_center_x, target_center_x])
    artists["lip_centerline"].set_xdata([lip_center_x, lip_center_x])

    corridor_center = float(guidance["corridor_center_x_m"])
    corridor_half_width = float(guidance["corridor_half_width_m"])
    artists["corridor"].set_x(corridor_center - corridor_half_width)
    artists["corridor"].set_y(lip_tip_y)
    artists["corridor"].set_width(2.0 * corridor_half_width)
    artists["corridor"].set_height(
        max(0.001, float(visualization["y_max_m"]) - lip_tip_y)
    )


def format_metrics(metrics: GeometryMetrics, config: dict[str, Any]) -> str:
    centered_band_m = float(config["guidance"]["centered_band_m"])
    lines = [
        "Guidance Readout",
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


def empty_offsets() -> np.ndarray:
    return np.empty((0, 2), dtype=float)


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


def preflight_live_port(config: dict[str, Any]) -> None:
    port = pathlib.Path(str(config["serial"]["port"]))
    if not port.exists():
        raise FileNotFoundError(
            f"Configured serial port does not exist: {port}\n"
            "Run scripts/show_serial_ports.py or the launcher diagnostics first."
        )
    if not os.access(port, os.R_OK | os.W_OK):
        raise PermissionError(
            f"Configured serial port exists but is not readable/writable: {port}"
        )
    probe = serial.Serial(
        port=str(port),
        baudrate=int(config["serial"]["baudrate"]),
        timeout=float(config["serial"]["timeout_s"]),
    )
    probe.close()


def handle_key_event(
    event: KeyEvent,
    editor: LiveParameterEditor,
    point_store: PointStore,
) -> None:
    key = event.key
    if key is None:
        return

    if key in {"[", ",", "pageup", "p"}:
        editor.move_selection(-1)
        return
    if key in {"]", ".", "pagedown", "n"}:
        editor.move_selection(1)
        return
    if key in {"left", "a", "-", "_"}:
        if editor.adjust_selected(-1, coarse=False):
            point_store.clear()
        return
    if key in {"right", "d", "+", "=", "plus"}:
        if editor.adjust_selected(1, coarse=False):
            point_store.clear()
        return
    if key in {"down", "s"}:
        if editor.adjust_selected(-1, coarse=True):
            point_store.clear()
        return
    if key in {"up", "w"}:
        if editor.adjust_selected(1, coarse=True):
            point_store.clear()
        return
    if key == "t":
        if editor.toggle_selected():
            point_store.clear()
        return
    if key == "r":
        editor.reload_from_file()
        point_store.clear()
        return
    if key == "c":
        point_store.clear()
        editor.status_message = "Cleared all plotted points."
        return
    if key in {"h", "?"}:
        editor.toggle_help()


def main() -> int:
    args = parse_args()
    config_path = pathlib.Path(args.config).expanduser().resolve()
    editor = LiveParameterEditor(config_path=config_path, config=load_config(config_path))

    print(f"Using config file: {config_path}")
    print(f"Matplotlib backend: {plt.get_backend()}")
    print(f"Configured serial port: {editor.config['serial']['port']}")
    print("Parameter panel: click fields in the separate window when available.")
    print("Keyboard fallback: [ ] , . p n left/right a d - + up/down w s t r c h")

    point_store = PointStore(
        ttl_s=float(editor.config["visualization"]["point_ttl_s"]),
        bucket_deg=float(editor.config["visualization"]["angle_bucket_deg"]),
    )

    measurement_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    error_queue: queue.Queue[str] = queue.Queue()
    worker: RPLidarWorker | None = None

    if not args.simulate:
        preflight_live_port(editor.config)
        worker = RPLidarWorker(
            port=str(editor.config["serial"]["port"]),
            baudrate=int(editor.config["serial"]["baudrate"]),
            timeout_s=float(editor.config["serial"]["timeout_s"]),
            output_queue=measurement_queue,
            error_queue=error_queue,
        )
        worker.start()

    fig, ax, artists = build_plot(editor.config)
    fig.canvas.mpl_connect(
        "key_press_event",
        lambda event: handle_key_event(event, editor, point_store),
    )
    plt.show(block=False)
    parameter_panel = LiveParameterPanel(editor, point_store)

    start_s = time.monotonic()
    last_console_print_s = 0.0

    try:
        while True:
            now_s = time.monotonic()
            config = editor.config

            parameter_panel.poll()

            point_store.ttl_s = float(config["visualization"]["point_ttl_s"])
            point_store.bucket_deg = float(config["visualization"]["angle_bucket_deg"])
            console_interval_s = float(config["console"]["print_interval_s"])
            update_period_s = float(config["visualization"]["update_period_s"])

            if worker is not None and not error_queue.empty():
                raise RuntimeError(
                    "LiDAR worker crashed.\n\n" + error_queue.get_nowait()
                )

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
                artists["points"].set_offsets([[p.x_m, p.y_m] for p in active_points])
            else:
                artists["points"].set_offsets(empty_offsets())
            artists["points"].set_sizes(
                np.full(max(1, len(active_points)), float(config["visualization"]["point_size"]))
            )

            update_geometry_artists(ax, artists, config)

            metrics = compute_metrics(config, active_points)
            metrics_text = format_metrics(metrics, config)
            artists["metrics_text"].set_text(metrics_text)
            artists["editor_text"].set_text(editor.render_text())
            artists["status_text"].set_text(editor.status_message)

            if (now_s - last_console_print_s) >= console_interval_s:
                print("")
                print(metrics_text)
                print(f"Selected parameter: {editor.selected_spec().label}")
                last_console_print_s = now_s

            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            plt.pause(update_period_s)

            if args.duration_seconds > 0 and (now_s - start_s) >= args.duration_seconds:
                break
            if not plt.fignum_exists(fig.number):
                break
        return 0
    finally:
        if worker is not None:
            worker.stop()
            worker.join(timeout=2.0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        raise SystemExit(130)
    except Exception:
        print("")
        print("Steer Clear live viewer failed with an exception.")
        print("Copy the traceback below and send it back to me.")
        print("")
        print(traceback.format_exc())
        raise SystemExit(1)
