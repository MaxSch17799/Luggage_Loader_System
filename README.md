# Steer Clear LiDAR Demo Repo

This repo is the starter workspace for the luggage-loader docking prototype.

Current contents:

- [PROJECT_REFERENCE_AND_ROADMAP.md](/home/max/Desktop/Steer_Clear/PROJECT_REFERENCE_AND_ROADMAP.md)
- [SURROUNDINGS_AND_WARNING_APPROACHES.md](/home/max/Desktop/Steer_Clear/SURROUNDINGS_AND_WARNING_APPROACHES.md)
- [GITHUB_SSH_SETUP.md](/home/max/Desktop/Steer_Clear/GITHUB_SSH_SETUP.md)
- [config/system_parameters.toml](/home/max/Desktop/Steer_Clear/config/system_parameters.toml)
- [scripts/lidar_web_ui.py](/home/max/Desktop/Steer_Clear/scripts/lidar_web_ui.py)
- [scripts/lidar_diagnostics.py](/home/max/Desktop/Steer_Clear/scripts/lidar_diagnostics.py)
- [scripts/self_check.py](/home/max/Desktop/Steer_Clear/scripts/self_check.py)
- [scripts/lidar_live_view.py](/home/max/Desktop/Steer_Clear/scripts/lidar_live_view.py)
- [scripts/show_serial_ports.py](/home/max/Desktop/Steer_Clear/scripts/show_serial_ports.py)
- [launch_demo.sh](/home/max/Desktop/Steer_Clear/launch_demo.sh)
- [Launch Steer Clear Demo.desktop](</home/max/Desktop/Steer_Clear/Launch Steer Clear Demo.desktop>)

## Why USB First Instead of 4-Pin UART?

Short version:

- the C1 serial link runs at `460800 baud`
- the Raspberry Pi GPIO UART is `3.3V` only
- the C1 documentation lists signal level up to `3.5V`
- long raw TTL UART wiring on a vehicle is less robust than USB

So for this first demo, USB is the safer and easier path.

Could 4-pin UART work on a short bench cable? Maybe, yes.
Do I recommend it for the first vehicle demo? No.

## Parameter Sheet

All editable geometry and tuning values live here:

- [config/system_parameters.toml](/home/max/Desktop/Steer_Clear/config/system_parameters.toml)

This is the main file you should tweak as you learn the real geometry.

Important sections:

- `[serial]`: LiDAR port and baud rate
- `[gps]`: UART GPS settings and stale-data handling
- `[lcd]`: I2C LCD settings and refresh rate
- `[mount]`: where the LiDAR sits on the loader
- `[lip]`: assumed lip geometry
- `[target]`: guessed opening position and width
- `[guidance]`: center/clearance logic and forward corridor
- `[visualization]`: graph limits and update speed
- `[simulation]`: fake scene settings for no-hardware testing

## First-Time Setup

Run these commands in the project folder:

```bash
cd /home/max/Desktop/Steer_Clear
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If `matplotlib` cannot open a window, install Tk support:

```bash
sudo apt update
sudo apt install python3-tk
```

## Find the LiDAR USB Port

With the virtual environment active:

```bash
python scripts/show_serial_ports.py
```

Look for something like `/dev/ttyUSB0`.

If needed, edit the port in:

- [config/system_parameters.toml](/home/max/Desktop/Steer_Clear/config/system_parameters.toml)

## Run Without Hardware

This is the easiest first test.

```bash
cd /home/max/Desktop/Steer_Clear
source .venv/bin/activate
python scripts/lidar_web_ui.py --simulate
```

What you should see:

- a browser tab opened to `http://127.0.0.1:8765`
- a parameter sidebar with editable fields
- a live scene plot in the browser
- cards showing center offset, left clearance, right clearance, and forward return
- a hardware status row for LiDAR, GPS, and LCD

Press `Ctrl+C` in the terminal to stop the server.

## Live Tuning Inside the Demo

The browser UI lists all editable parameters in grouped sections on the left.

Any change you make there is written straight back into:

- [config/system_parameters.toml](/home/max/Desktop/Steer_Clear/config/system_parameters.toml)

This means you can tune the geometry while the demo is running and keep the values for the next launch.

How it works:

- click into a numeric field
- type a new value
- press `Enter` or click away to apply it live
- booleans and enums appear as dropdowns
- each parameter now has a small `i` button for a more intuitive explanation
- `-` and `+` do fine nudges
- `--` and `++` do coarse nudges
- `Turn LiDAR On/Off` starts or stops the live LiDAR worker
- `Reload From TOML` reloads the file from disk
- `Clear Points` clears the current plot points
- `Close Demo` stops the demo server and requests LiDAR shutdown
- the plot now overlays the live forward-distance readout and GPS coordinates
- when enabled, the LCD shows forward distance plus latitude and longitude

Good first parameters to tune:

- `mount.sensor_x_m`
- `mount.sensor_y_m`
- `mount.scan_angle_offset_deg`
- `lip.center_x_m`
- `lip.width_m`
- `target.center_x_m`
- `target.opening_width_m`
- `target.forward_y_m`
- `guidance.corridor_center_x_m`
- `guidance.corridor_half_width_m`

## Folder Launcher

There are now two launcher files in the repo root:

- [launch_demo.sh](/home/max/Desktop/Steer_Clear/launch_demo.sh)
- [Launch Steer Clear Demo.desktop](</home/max/Desktop/Steer_Clear/Launch Steer Clear Demo.desktop>)

If you are in the file manager on Raspberry Pi OS, try double-clicking:

- `Launch Steer Clear Demo.desktop`

If that does not launch, open a terminal in the folder and run:

```bash
./launch_demo.sh
```

The launcher lets you choose:

- simulate browser demo
- live LiDAR browser demo
- run diagnostics
- show serial ports

Every launcher run now writes a log file into:

- `logs/`

If something fails, copy the path of the `.log` file or paste its contents back to me.

## Run With the Real LiDAR

1. Plug the RPLIDAR C1 into the Raspberry Pi by USB.
2. Activate the virtual environment.
3. Confirm the serial port.
4. Start the viewer:

```bash
cd /home/max/Desktop/Steer_Clear
source .venv/bin/activate
python scripts/lidar_web_ui.py
```

The browser page should open automatically. If it does not, go to:

- `http://127.0.0.1:8765`

If the dots look rotated incorrectly, edit:

- `mount.scan_angle_offset_deg`

in the browser UI or the parameter sheet.

## Useful Test Command

This runs the visualizer for only 5 seconds:

```bash
python scripts/lidar_web_ui.py --simulate
```

## Diagnostics

If live mode fails, run:

```bash
cd /home/max/Desktop/Steer_Clear
source .venv/bin/activate
python scripts/lidar_diagnostics.py
```

This checks:

- the configured serial port
- serial permissions
- pyserial open/close
- GPS UART visibility and NMEA traffic
- visible I2C buses and common LCD addresses
- a short live RPLIDAR protocol test

## GPS And LCD Notes

The browser demo now tries to use:

- `gps.port`, which defaults to `/dev/serial0`
- `lcd.i2c_bus`, which defaults to `1`
- `lcd.address`, which defaults to `39` (`0x27`)

Important Raspberry Pi setup note:

- if `scripts/lidar_diagnostics.py` says `i2c-1` is missing, enable `I2C` in `sudo raspi-config` and reboot
- if the GPS shows no NMEA sentences, enable the serial hardware UART in `sudo raspi-config`, keep the serial login shell disabled, and reboot

## Self-Check

Before calling the demo ready, this repo now includes a quick self-check:

```bash
cd /home/max/Desktop/Steer_Clear
source .venv/bin/activate
python scripts/self_check.py
```

This runs:

- Python syntax compile
- simulated viewer smoke test
- non-invasive diagnostics smoke test

## If You Get a Serial Permission Error

Try:

```bash
sudo usermod -a -G dialout $USER
```

Then log out and back in.

## Existing Code Used

This demo intentionally builds on existing code instead of reimplementing everything from scratch.

- SLAMTEC official SDK and docs for the device/protocol direction
- `rplidarc1` Python package for quick Python access to the C1 scan stream

## Git Workflow

The easiest long-term setup is SSH.

See:

- [GITHUB_SSH_SETUP.md](/home/max/Desktop/Steer_Clear/GITHUB_SSH_SETUP.md)

After SSH setup, the repo remote should be:

```bash
git remote set-url origin git@github.com:MaxSch17799/Luggage_Loader_System.git
```

Recommended habit:

- commit after each meaningful milestone
- push after each meaningful milestone

Typical commands:

```bash
git status
git add .
git commit -m "Describe the milestone"
git push origin main
```
