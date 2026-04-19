#!/usr/bin/env python3
"""Browser-based Steer Clear LiDAR demo UI."""

from __future__ import annotations

import argparse
import pathlib
import queue
import threading
import time
import traceback
import webbrowser
from typing import Any

from flask import Flask, jsonify, render_template, request

from lidar_live_view import (
    DEFAULT_CONFIG_PATH,
    LiveParameterEditor,
    PointStore,
    RPLidarWorker,
    compute_metrics,
    format_value_for_display,
    get_config_value,
    get_target_edges,
    load_config,
    preflight_live_port,
    simulate_points,
    status_label,
    transform_measurement_to_loader_frame,
)


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "web_ui" / "templates"
STATIC_DIR = PROJECT_ROOT / "web_ui" / "static"


class DemoSession:
    """Shared live session backing the browser UI."""

    def __init__(self, config_path: pathlib.Path, simulate: bool) -> None:
        self.config_path = config_path
        self.simulate = simulate
        self.mode_label = "Simulation" if simulate else "Live LiDAR"
        self.lock = threading.RLock()
        self.editor = LiveParameterEditor(
            config_path=config_path,
            config=load_config(config_path),
        )
        self.editor.panel_enabled = False
        self.editor.status_message = "Browser UI ready. Changes autosave to the TOML file."

        self.point_store = PointStore(
            ttl_s=float(self.editor.config["visualization"]["point_ttl_s"]),
            bucket_deg=float(self.editor.config["visualization"]["angle_bucket_deg"]),
        )
        self.measurement_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.error_queue: queue.Queue[str] = queue.Queue()
        self.worker: RPLidarWorker | None = None
        self.last_worker_error: str | None = None

        if not simulate:
            preflight_live_port(self.editor.config)
            self.worker = RPLidarWorker(
                port=str(self.editor.config["serial"]["port"]),
                baudrate=int(self.editor.config["serial"]["baudrate"]),
                timeout_s=float(self.editor.config["serial"]["timeout_s"]),
                output_queue=self.measurement_queue,
                error_queue=self.error_queue,
            )
            self.worker.start()

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker.join(timeout=2.0)

    def schema_payload(self) -> dict[str, Any]:
        with self.lock:
            sections: dict[str, list[dict[str, Any]]] = {}
            for spec in self.editor.specs:
                current = get_config_value(self.editor.config, spec.path)
                if spec.allowed_values:
                    kind = "enum"
                elif isinstance(current, bool):
                    kind = "boolean"
                elif isinstance(current, int) and not isinstance(current, bool):
                    kind = "integer"
                elif isinstance(current, float):
                    kind = "number"
                else:
                    kind = "string"

                sections.setdefault(spec.section, []).append(
                    {
                        "section": spec.section,
                        "key": spec.key,
                        "path": f"{spec.section}.{spec.key}",
                        "description": spec.description,
                        "helpText": spec.help_text,
                        "kind": kind,
                        "fineStep": spec.fine_step,
                        "coarseStep": spec.coarse_step,
                        "allowedValues": spec.allowed_values,
                        "displayValue": format_value_for_display(current),
                    }
                )

            return {
                "configPath": str(self.config_path),
                "mode": self.mode_label,
                "sections": [
                    {"name": name, "items": items}
                    for name, items in sections.items()
                ],
            }

    def _drain_live_measurements(self, now_s: float) -> None:
        while True:
            try:
                measurement = self.measurement_queue.get_nowait()
            except queue.Empty:
                break
            point = transform_measurement_to_loader_frame(
                measurement,
                self.editor.config,
                now_s,
            )
            if point is not None:
                self.point_store.add(point)

    def _poll_worker_errors(self) -> None:
        if self.worker is None:
            return
        if not self.error_queue.empty():
            self.last_worker_error = self.error_queue.get_nowait()
            self.editor.status_message = (
                "LiDAR worker reported an error. Check the terminal log for traceback details."
            )

    def _current_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in self.editor.specs:
            values[f"{spec.section}.{spec.key}"] = get_config_value(
                self.editor.config,
                spec.path,
            )
        return values

    def _build_plot_payload(self, active_points: list[Any]) -> dict[str, Any]:
        config = self.editor.config
        visualization = config["visualization"]
        mount = config["mount"]
        lip = config["lip"]
        target = config["target"]
        guidance = config["guidance"]

        target_left_x, target_right_x = get_target_edges(config)
        lip_left_x = float(lip["center_x_m"]) - float(lip["width_m"]) / 2.0
        lip_right_x = float(lip["center_x_m"]) + float(lip["width_m"]) / 2.0
        lip_tip_y = float(lip["tip_y_m"])
        target_forward_y = float(target["forward_y_m"])
        corridor_center = float(guidance["corridor_center_x_m"])
        corridor_half_width = float(guidance["corridor_half_width_m"])

        max_points = 1800
        stride = max(1, len(active_points) // max_points) if active_points else 1
        sampled_points = active_points[::stride]

        return {
            "xMin": float(visualization["x_min_m"]),
            "xMax": float(visualization["x_max_m"]),
            "yMin": float(visualization["y_min_m"]),
            "yMax": float(visualization["y_max_m"]),
            "sensor": {
                "x": float(mount["sensor_x_m"]),
                "y": float(mount["sensor_y_m"]),
            },
            "lip": {
                "left": lip_left_x,
                "right": lip_right_x,
                "y": lip_tip_y,
                "center": float(lip["center_x_m"]),
            },
            "target": {
                "left": target_left_x,
                "right": target_right_x,
                "y": target_forward_y,
                "center": float(target["center_x_m"]),
            },
            "corridor": {
                "left": corridor_center - corridor_half_width,
                "right": corridor_center + corridor_half_width,
                "bottom": lip_tip_y,
                "top": float(visualization["y_max_m"]),
            },
            "points": [
                {"x": round(point.x_m, 4), "y": round(point.y_m, 4)}
                for point in sampled_points
            ],
            "pointCount": len(active_points),
            "renderedPointCount": len(sampled_points),
        }

    def state_payload(self) -> dict[str, Any]:
        with self.lock:
            now_s = time.monotonic()
            config = self.editor.config

            self.point_store.ttl_s = float(config["visualization"]["point_ttl_s"])
            self.point_store.bucket_deg = float(config["visualization"]["angle_bucket_deg"])

            self._poll_worker_errors()
            if self.simulate:
                for point in simulate_points(config, now_s):
                    self.point_store.add(point)
            else:
                self._drain_live_measurements(now_s)

            active_points = self.point_store.active_points(now_s)
            metrics = compute_metrics(config, active_points)
            centered_band_m = float(config["guidance"]["centered_band_m"])

            return {
                "mode": self.mode_label,
                "configPath": str(self.config_path),
                "statusMessage": self.editor.status_message,
                "workerError": self.last_worker_error,
                "parameterValues": self._current_values(),
                "metrics": {
                    "status": status_label(metrics.center_offset_m, centered_band_m),
                    "centerOffsetMm": round(metrics.center_offset_m * 1000.0, 1),
                    "leftClearanceMm": round(metrics.left_clearance_m * 1000.0, 1),
                    "rightClearanceMm": round(metrics.right_clearance_m * 1000.0, 1),
                    "configuredTargetYmm": round(metrics.target_forward_y_m * 1000.0, 1),
                    "liveForwardReturnMm": None
                    if metrics.live_forward_distance_m is None
                    else round(metrics.live_forward_distance_m * 1000.0, 1),
                },
                "plot": self._build_plot_payload(active_points),
            }

    def set_parameter(self, section: str, key: str, raw_value: str) -> tuple[bool, str]:
        with self.lock:
            changed = self.editor.set_value_from_text((section, key), raw_value)
            if changed:
                self.point_store.clear()
            return changed, self.editor.status_message

    def nudge_parameter(
        self,
        section: str,
        key: str,
        direction: int,
        coarse: bool,
    ) -> tuple[bool, str]:
        with self.lock:
            changed = self.editor.adjust_path((section, key), direction, coarse)
            if changed:
                self.point_store.clear()
            return changed, self.editor.status_message

    def reload_from_disk(self) -> str:
        with self.lock:
            self.editor.reload_from_file()
            self.point_store.clear()
            return self.editor.status_message

    def clear_points(self) -> str:
        with self.lock:
            self.point_store.clear()
            self.editor.status_message = "Cleared plotted points from the browser UI."
            return self.editor.status_message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browser-based Steer Clear LiDAR demo UI")
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
        "--host",
        default="127.0.0.1",
        help="Host/interface to bind the local web server to",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the local web server",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open the browser",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Initialize the web session, build one state payload, then exit",
    )
    return parser.parse_args()


def create_app(session: DemoSession) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(TEMPLATE_DIR),
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html",
            bootstrap={
                "mode": session.mode_label,
                "configPath": str(session.config_path),
            },
        )

    @app.get("/api/schema")
    def api_schema() -> Any:
        return jsonify(session.schema_payload())

    @app.get("/api/state")
    def api_state() -> Any:
        return jsonify(session.state_payload())

    @app.post("/api/parameter")
    def api_parameter() -> Any:
        payload = request.get_json(force=True)
        changed, message = session.set_parameter(
            section=str(payload["section"]),
            key=str(payload["key"]),
            raw_value=str(payload["value"]),
        )
        return jsonify({"ok": changed, "message": message})

    @app.post("/api/nudge")
    def api_nudge() -> Any:
        payload = request.get_json(force=True)
        changed, message = session.nudge_parameter(
            section=str(payload["section"]),
            key=str(payload["key"]),
            direction=int(payload["direction"]),
            coarse=bool(payload["coarse"]),
        )
        return jsonify({"ok": changed, "message": message})

    @app.post("/api/reload")
    def api_reload() -> Any:
        return jsonify({"ok": True, "message": session.reload_from_disk()})

    @app.post("/api/clear-points")
    def api_clear_points() -> Any:
        return jsonify({"ok": True, "message": session.clear_points()})

    return app


def maybe_open_browser(url: str, enabled: bool) -> None:
    if not enabled:
        return

    def _open() -> None:
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass

    timer = threading.Timer(1.0, _open)
    timer.daemon = True
    timer.start()


def main() -> int:
    args = parse_args()
    config_path = pathlib.Path(args.config).expanduser().resolve()
    session = DemoSession(config_path=config_path, simulate=args.simulate)

    try:
        if args.smoke_test:
            app = create_app(session)
            payload = session.state_payload()
            with app.test_client() as client:
                index_response = client.get("/")
                schema_response = client.get("/api/schema")
                state_response = client.get("/api/state")

            if index_response.status_code != 200:
                raise RuntimeError("Index route failed during smoke test")
            if schema_response.status_code != 200:
                raise RuntimeError("Schema route failed during smoke test")
            if state_response.status_code != 200:
                raise RuntimeError("State route failed during smoke test")

            print(f"Mode: {payload['mode']}")
            print(f"Config: {payload['configPath']}")
            print(f"Status: {payload['statusMessage']}")
            print(f"Rendered points: {payload['plot']['renderedPointCount']}")
            return 0

        app = create_app(session)
        url = f"http://{args.host}:{args.port}"

        print(f"Steer Clear browser UI: {url}")
        print("Press Ctrl+C in this terminal to stop the server.")
        print(f"Config file: {config_path}")
        print(f"Mode: {session.mode_label}")

        maybe_open_browser(url, enabled=not args.no_browser)
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)
        return 0
    finally:
        session.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nSteer Clear browser UI stopped by user.")
        raise SystemExit(130)
    except Exception:
        print("")
        print("Steer Clear browser UI failed with an exception.")
        print("Copy the traceback below and send it back to me.")
        print("")
        print(traceback.format_exc())
        raise SystemExit(1)
