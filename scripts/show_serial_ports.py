#!/usr/bin/env python3
"""List serial ports in a beginner-friendly way."""

from serial.tools import list_ports


def main() -> None:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return

    print("Detected serial ports:\n")
    for port in ports:
        print(f"Device      : {port.device}")
        print(f"Description : {port.description}")
        print(f"HWID        : {port.hwid}")
        print("-" * 60)


if __name__ == "__main__":
    main()

