#!/usr/bin/env python3
"""Lightweight GPS and LCD helpers for the Steer Clear browser demo."""

from __future__ import annotations

import pathlib
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any

import serial
from serial.tools import list_ports

try:
    from smbus2 import SMBus
except Exception:
    SMBus = None


COMMON_LCD_ADDRESSES = (0x27, 0x3F)


def detect_i2c_bus_numbers() -> list[int]:
    buses: list[int] = []
    for path in pathlib.Path("/dev").glob("i2c-*"):
        try:
            buses.append(int(path.name.split("-", 1)[1]))
        except Exception:
            continue
    return sorted(set(buses))


def format_i2c_address(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"0x{int(value):02X}"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _parse_nmea_degrees(value: str, hemisphere: str) -> float | None:
    if not value or not hemisphere:
        return None

    try:
        degree_digits = 2 if hemisphere in {"N", "S"} else 3
        degrees = float(value[:degree_digits])
        minutes = float(value[degree_digits:])
    except Exception:
        return None

    decimal = degrees + (minutes / 60.0)
    if hemisphere in {"S", "W"}:
        decimal *= -1.0
    return decimal


def _verify_nmea_checksum(sentence: str) -> bool:
    if not sentence.startswith("$"):
        return False
    if "*" not in sentence:
        return True

    body, checksum_text = sentence[1:].split("*", 1)
    checksum = 0
    for char in body:
        checksum ^= ord(char)

    try:
        expected = int(checksum_text[:2], 16)
    except ValueError:
        return False
    return checksum == expected


@dataclass
class GPSSnapshot:
    enabled: bool
    running: bool
    connected: bool
    port: str
    baudrate: int
    status: str
    error: str | None
    has_fix: bool
    latitude: float | None
    longitude: float | None
    altitude_m: float | None
    satellites: int | None
    fix_quality: int | None
    sentence_count: int
    last_sentence_age_s: float | None
    last_fix_age_s: float | None
    last_sentence_type: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "connected": self.connected,
            "port": self.port,
            "baudrate": self.baudrate,
            "status": self.status,
            "error": self.error,
            "hasFix": self.has_fix,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitudeM": self.altitude_m,
            "satellites": self.satellites,
            "fixQuality": self.fix_quality,
            "sentenceCount": self.sentence_count,
            "lastSentenceAgeS": self.last_sentence_age_s,
            "lastFixAgeS": self.last_fix_age_s,
            "lastSentenceType": self.last_sentence_type,
        }


class GPSWorker(threading.Thread):
    """Read NMEA sentences from a UART GPS without blocking the browser UI."""

    DEFAULT_CANDIDATE_PORTS = (
        "/dev/serial0",
        "/dev/ttyAMA10",
        "/dev/ttyAMA0",
        "/dev/ttyS0",
    )

    def __init__(self, gps_config: dict[str, Any], excluded_ports: set[str] | None = None) -> None:
        super().__init__(daemon=True)
        self.gps_config = gps_config
        self.excluded_ports = excluded_ports or set()
        self.stop_requested = threading.Event()
        self.lock = threading.RLock()

        self.running = False
        self.connected = False
        self.port = str(gps_config.get("port", "/dev/serial0"))
        self.baudrate = int(gps_config.get("baudrate", 9600))
        self.status = "GPS disabled."
        self.error: str | None = None
        self.has_fix = False
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.altitude_m: float | None = None
        self.satellites: int | None = None
        self.fix_quality: int | None = None
        self.sentence_count = 0
        self.last_sentence_monotonic: float | None = None
        self.last_fix_monotonic: float | None = None
        self.last_sentence_type: str | None = None

        if bool(self.gps_config.get("enabled", True)):
            self.status = f"Waiting for GPS data on {self.port}."

    def stop(self) -> None:
        self.stop_requested.set()

    def _snapshot_unlocked(self) -> GPSSnapshot:
        now_s = time.monotonic()
        last_sentence_age = None
        last_fix_age = None
        if self.last_sentence_monotonic is not None:
            last_sentence_age = max(0.0, now_s - self.last_sentence_monotonic)
        if self.last_fix_monotonic is not None:
            last_fix_age = max(0.0, now_s - self.last_fix_monotonic)

        return GPSSnapshot(
            enabled=bool(self.gps_config.get("enabled", True)),
            running=self.running,
            connected=self.connected,
            port=self.port,
            baudrate=self.baudrate,
            status=self.status,
            error=self.error,
            has_fix=self.has_fix,
            latitude=self.latitude,
            longitude=self.longitude,
            altitude_m=self.altitude_m,
            satellites=self.satellites,
            fix_quality=self.fix_quality,
            sentence_count=self.sentence_count,
            last_sentence_age_s=last_sentence_age,
            last_fix_age_s=last_fix_age,
            last_sentence_type=self.last_sentence_type,
        )

    def snapshot(self) -> GPSSnapshot:
        with self.lock:
            return self._snapshot_unlocked()

    def _candidate_ports(self) -> list[str]:
        preferred: list[str] = []
        configured = str(self.gps_config.get("port", "/dev/serial0")).strip()
        if configured:
            preferred.append(configured)
        preferred.extend(self.DEFAULT_CANDIDATE_PORTS)

        if bool(self.gps_config.get("auto_detect", True)):
            for port_info in list_ports.comports():
                preferred.append(port_info.device)

        unique_ports: list[str] = []
        seen: set[str] = set()
        for candidate in preferred:
            if not candidate or candidate in self.excluded_ports:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            unique_ports.append(candidate)
        return unique_ports

    def _set_status(self, message: str, error: str | None = None) -> None:
        with self.lock:
            self.status = message
            self.error = error

    def _update_fix_from_sentence(self, sentence_type: str, fields: list[str], now_s: float) -> None:
        with self.lock:
            self.last_sentence_monotonic = now_s
            self.last_sentence_type = sentence_type
            self.sentence_count += 1
            self.error = None

            if sentence_type.endswith("RMC") and len(fields) >= 7:
                status = fields[2]
                latitude = _parse_nmea_degrees(fields[3], fields[4])
                longitude = _parse_nmea_degrees(fields[5], fields[6])
                if latitude is not None and longitude is not None:
                    self.latitude = latitude
                    self.longitude = longitude
                if status == "A" and latitude is not None and longitude is not None:
                    self.has_fix = True
                    self.last_fix_monotonic = now_s
                    satellites = self.satellites or 0
                    self.status = f"GPS fix on {self.port} ({satellites} sats)."
                else:
                    self.status = f"GPS connected on {self.port}. Waiting for satellite fix."

            if sentence_type.endswith("GGA") and len(fields) >= 10:
                latitude = _parse_nmea_degrees(fields[2], fields[3])
                longitude = _parse_nmea_degrees(fields[4], fields[5])
                fix_quality = int(fields[6] or "0")
                satellites = int(fields[7] or "0")
                altitude = _safe_float(fields[9])

                if latitude is not None and longitude is not None:
                    self.latitude = latitude
                    self.longitude = longitude
                self.fix_quality = fix_quality
                self.satellites = satellites
                self.altitude_m = altitude

                if fix_quality > 0 and self.latitude is not None and self.longitude is not None:
                    self.has_fix = True
                    self.last_fix_monotonic = now_s
                    self.status = f"GPS fix on {self.port} ({satellites} sats)."
                else:
                    self.has_fix = False
                    self.status = f"GPS connected on {self.port}. Waiting for satellite fix."

    def _mark_sentence_stale(self) -> None:
        stale_after_s = float(self.gps_config.get("stale_after_s", 3.0))
        with self.lock:
            if self.last_sentence_monotonic is None:
                return
            if (time.monotonic() - self.last_sentence_monotonic) < stale_after_s:
                return
            self.connected = False
            self.has_fix = False
            self.status = f"GPS data on {self.port} went stale. Reconnecting."

    def _read_from_port(self, port: str) -> None:
        stale_after_s = float(self.gps_config.get("stale_after_s", 3.0))
        timeout_s = float(self.gps_config.get("timeout_s", 0.5))
        baudrate = int(self.gps_config.get("baudrate", 9600))
        no_data_deadline = time.monotonic() + max(1.0, stale_after_s)
        got_sentence = False

        with serial.Serial(port=port, baudrate=baudrate, timeout=timeout_s) as serial_handle:
            with self.lock:
                self.connected = True
                self.port = port
                self.baudrate = baudrate
                self.status = f"Listening for GPS sentences on {port}."
                self.error = None

            while not self.stop_requested.is_set():
                raw = serial_handle.readline()
                now_s = time.monotonic()

                if not raw:
                    if not got_sentence and now_s >= no_data_deadline:
                        raise TimeoutError(f"No GPS NMEA sentences detected on {port}.")
                    self._mark_sentence_stale()
                    continue

                got_sentence = True
                text = raw.decode("ascii", errors="ignore").strip()
                if not text or not text.startswith("$"):
                    continue
                if not _verify_nmea_checksum(text):
                    continue

                body = text[1:].split("*", 1)[0]
                fields = body.split(",")
                sentence_type = fields[0]
                self._update_fix_from_sentence(sentence_type, fields, now_s)

    def run(self) -> None:
        if not bool(self.gps_config.get("enabled", True)):
            with self.lock:
                self.running = False
                self.connected = False
                self.status = "GPS disabled in the parameter sheet."
            return

        with self.lock:
            self.running = True

        try:
            while not self.stop_requested.is_set():
                candidate_ports = self._candidate_ports()
                if not candidate_ports:
                    self._set_status("No GPS serial ports found on this Pi.")
                    time.sleep(1.0)
                    continue

                connected_once = False
                for candidate in candidate_ports:
                    if self.stop_requested.is_set():
                        break
                    try:
                        self._read_from_port(candidate)
                        connected_once = True
                    except TimeoutError as exc:
                        self._set_status(str(exc))
                    except FileNotFoundError:
                        self._set_status(f"GPS port {candidate} does not exist right now.")
                    except serial.SerialException as exc:
                        self._set_status(f"Could not open GPS port {candidate}.", str(exc))
                    except Exception:
                        self._set_status(
                            f"GPS reader hit an unexpected error on {candidate}.",
                            traceback.format_exc(),
                        )

                    with self.lock:
                        self.connected = False

                if not connected_once and not self.stop_requested.is_set():
                    time.sleep(1.0)
        finally:
            with self.lock:
                self.running = False
                self.connected = False
                if self.stop_requested.is_set():
                    self.status = "GPS reader stopped."


@dataclass
class LCDSnapshot:
    enabled: bool
    connected: bool
    bus_number: int | None
    address: int | None
    status: str
    error: str | None
    last_update_age_s: float | None
    last_lines: list[str]
    detected_buses: list[int]

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "busNumber": self.bus_number,
            "address": self.address,
            "addressHex": format_i2c_address(self.address),
            "status": self.status,
            "error": self.error,
            "lastUpdateAgeS": self.last_update_age_s,
            "lastLines": list(self.last_lines),
            "detectedBuses": list(self.detected_buses),
        }


class HD44780I2CDisplay:
    """Minimal HD44780-over-PCF8574 driver for the common 20x4 I2C backpack."""

    LCD_CHR = 0x01
    LCD_CMD = 0x00
    LCD_BACKLIGHT = 0x08
    ENABLE = 0x04

    ROW_OFFSETS = (0x00, 0x40, 0x14, 0x54)

    def __init__(self, bus: Any, address: int, columns: int, rows: int) -> None:
        self.bus = bus
        self.address = address
        self.columns = columns
        self.rows = rows
        self.backlight = self.LCD_BACKLIGHT
        self._initialize()

    def _expander_write(self, data: int) -> None:
        self.bus.write_byte(self.address, data | self.backlight)

    def _pulse_enable(self, data: int) -> None:
        self._expander_write(data | self.ENABLE)
        time.sleep(0.0005)
        self._expander_write(data & ~self.ENABLE)
        time.sleep(0.0001)

    def _write4bits(self, bits: int) -> None:
        self._expander_write(bits)
        self._pulse_enable(bits)

    def _send(self, value: int, mode: int) -> None:
        high = mode | (value & 0xF0)
        low = mode | ((value << 4) & 0xF0)
        self._write4bits(high)
        self._write4bits(low)

    def command(self, value: int) -> None:
        self._send(value, self.LCD_CMD)

    def write_char(self, value: str) -> None:
        self._send(ord(value), self.LCD_CHR)

    def _initialize(self) -> None:
        time.sleep(0.05)
        self._write4bits(0x30)
        time.sleep(0.005)
        self._write4bits(0x30)
        time.sleep(0.001)
        self._write4bits(0x30)
        time.sleep(0.001)
        self._write4bits(0x20)
        time.sleep(0.001)

        self.command(0x28)
        self.command(0x0C)
        self.command(0x06)
        self.clear()

    def clear(self) -> None:
        self.command(0x01)
        time.sleep(0.002)

    def set_cursor(self, row: int, column: int = 0) -> None:
        row_index = max(0, min(self.rows - 1, row))
        column_index = max(0, min(self.columns - 1, column))
        self.command(0x80 | (self.ROW_OFFSETS[row_index] + column_index))

    def write_line(self, row: int, text: str) -> None:
        visible = (text or "")[: self.columns].ljust(self.columns)
        self.set_cursor(row, 0)
        for char in visible:
            self.write_char(char)

    def write_lines(self, lines: list[str]) -> None:
        normalized = list(lines[: self.rows])
        while len(normalized) < self.rows:
            normalized.append("")
        for row_index, text in enumerate(normalized):
            self.write_line(row_index, text)


class LCDController:
    """Keep a small 20x4 LCD updated with forward distance and GPS coordinates."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.enabled = False
        self.connected = False
        self.bus_number: int | None = None
        self.address: int | None = None
        self.status = "LCD disabled."
        self.error: str | None = None
        self.last_update_monotonic: float | None = None
        self.last_lines: list[str] = []
        self.driver: HD44780I2CDisplay | None = None
        self.bus_handle: Any | None = None

    def invalidate(self) -> None:
        with self.lock:
            self._close_driver(clear=False)
            self.status = "LCD settings changed. Reconnecting on next refresh."
            self.error = None

    def snapshot(self) -> LCDSnapshot:
        with self.lock:
            age_s = None
            if self.last_update_monotonic is not None:
                age_s = max(0.0, time.monotonic() - self.last_update_monotonic)
            return LCDSnapshot(
                enabled=self.enabled,
                connected=self.connected,
                bus_number=self.bus_number,
                address=self.address,
                status=self.status,
                error=self.error,
                last_update_age_s=age_s,
                last_lines=list(self.last_lines),
                detected_buses=detect_i2c_bus_numbers(),
            )

    def _close_driver(self, clear: bool) -> None:
        if self.driver is not None:
            try:
                if clear:
                    self.driver.clear()
            except Exception:
                pass
        if self.bus_handle is not None:
            try:
                self.bus_handle.close()
            except Exception:
                pass
        self.driver = None
        self.bus_handle = None
        self.connected = False

    def shutdown(self, clear: bool = True) -> None:
        with self.lock:
            self._close_driver(clear=clear)
            if clear:
                self.status = "LCD cleared and disconnected."

    def _candidate_buses(self, lcd_config: dict[str, Any]) -> list[int]:
        configured = int(lcd_config.get("i2c_bus", 1))
        candidates = [configured]
        if bool(lcd_config.get("auto_detect", True)):
            candidates.extend(detect_i2c_bus_numbers())
        unique: list[int] = []
        seen: set[int] = set()
        for bus_number in candidates:
            if bus_number in seen:
                continue
            seen.add(bus_number)
            unique.append(bus_number)
        return unique

    def _candidate_addresses(self, lcd_config: dict[str, Any]) -> list[int]:
        configured = int(lcd_config.get("address", 39))
        candidates = [configured]
        if bool(lcd_config.get("auto_detect", True)):
            candidates.extend(COMMON_LCD_ADDRESSES)
        unique: list[int] = []
        seen: set[int] = set()
        for address in candidates:
            if address in seen:
                continue
            seen.add(address)
            unique.append(address)
        return unique

    def _connect(self, lcd_config: dict[str, Any]) -> None:
        if SMBus is None:
            self.status = "Python package smbus2 is unavailable."
            self.error = "Install requirements.txt again to add LCD support."
            return

        columns = int(lcd_config.get("columns", 20))
        rows = int(lcd_config.get("rows", 4))
        last_error: str | None = None

        for bus_number in self._candidate_buses(lcd_config):
            if not pathlib.Path(f"/dev/i2c-{bus_number}").exists():
                last_error = f"/dev/i2c-{bus_number} is missing. Enable I2C and reboot the Pi."
                continue

            for address in self._candidate_addresses(lcd_config):
                bus_handle: Any | None = None
                try:
                    bus_handle = SMBus(bus_number)
                    bus_handle.read_byte(address)
                    driver = HD44780I2CDisplay(
                        bus=bus_handle,
                        address=address,
                        columns=columns,
                        rows=rows,
                    )
                    driver.write_lines(
                        [
                            "Steer Clear ready",
                            f"Bus i2c-{bus_number} {format_i2c_address(address)}",
                            "",
                            "",
                        ]
                    )
                    self.driver = driver
                    self.bus_handle = bus_handle
                    self.connected = True
                    self.bus_number = bus_number
                    self.address = address
                    self.status = f"LCD connected on i2c-{bus_number} at {format_i2c_address(address)}."
                    self.error = None
                    return
                except Exception as exc:
                    last_error = f"Could not use i2c-{bus_number} at {format_i2c_address(address)}: {exc}"
                    if bus_handle is not None:
                        try:
                            bus_handle.close()
                        except Exception:
                            pass

        self.connected = False
        self.bus_number = None
        self.address = None
        self.status = "LCD not detected yet."
        self.error = last_error

    def _format_forward_line(self, forward_distance_m: float | None) -> str:
        if forward_distance_m is None:
            return "FWD NO HIT"
        return f"FWD {round(forward_distance_m * 1000.0):.0f}mm"

    def _format_gps_lines(self, gps_snapshot: GPSSnapshot) -> tuple[str, str, str]:
        if gps_snapshot.has_fix and gps_snapshot.latitude is not None and gps_snapshot.longitude is not None:
            satellites = gps_snapshot.satellites or 0
            return (
                f"LAT {gps_snapshot.latitude:.5f}",
                f"LON {gps_snapshot.longitude:.5f}",
                f"GPS FIX {satellites:02d} SAT",
            )

        if gps_snapshot.connected:
            return ("LAT --", "LON --", "GPS SEARCHING")
        return ("LAT --", "LON --", "GPS OFFLINE")

    def update(
        self,
        lcd_config: dict[str, Any],
        forward_distance_m: float | None,
        gps_snapshot: GPSSnapshot,
    ) -> None:
        with self.lock:
            self.enabled = bool(lcd_config.get("enabled", True))
            if not self.enabled:
                self.status = "LCD disabled in the parameter sheet."
                self.error = None
                self._close_driver(clear=False)
                return

            refresh_interval_s = float(lcd_config.get("refresh_interval_s", 1.0))
            now_s = time.monotonic()
            if (
                self.last_update_monotonic is not None
                and (now_s - self.last_update_monotonic) < refresh_interval_s
            ):
                return

            if self.driver is None or self.bus_handle is None:
                self._connect(lcd_config)
                if self.driver is None:
                    self.last_update_monotonic = now_s
                    return

            line2, line3, line4 = self._format_gps_lines(gps_snapshot)
            lines = [
                self._format_forward_line(forward_distance_m),
                line2,
                line3,
                line4,
            ]

            if lines == self.last_lines:
                self.last_update_monotonic = now_s
                return

            try:
                assert self.driver is not None
                self.driver.write_lines(lines)
                self.last_lines = lines
                self.last_update_monotonic = now_s
                self.connected = True
                self.status = (
                    f"LCD updated on i2c-{self.bus_number} at {format_i2c_address(self.address)}."
                )
                self.error = None
            except Exception:
                self.error = traceback.format_exc()
                self.status = "LCD write failed. Will retry automatically."
                self._close_driver(clear=False)
