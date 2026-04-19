# Steer Clear LiDAR Demo Repo

This repo is the starter workspace for the luggage-loader docking prototype.

Current contents:

- [PROJECT_REFERENCE_AND_ROADMAP.md](/home/max/Desktop/Steer_Clear/PROJECT_REFERENCE_AND_ROADMAP.md)
- [SURROUNDINGS_AND_WARNING_APPROACHES.md](/home/max/Desktop/Steer_Clear/SURROUNDINGS_AND_WARNING_APPROACHES.md)
- [GITHUB_SSH_SETUP.md](/home/max/Desktop/Steer_Clear/GITHUB_SSH_SETUP.md)
- [config/system_parameters.toml](/home/max/Desktop/Steer_Clear/config/system_parameters.toml)
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
python scripts/lidar_live_view.py --simulate
```

What you should see:

- a graph window
- LiDAR dots
- the LiDAR mount position
- the loader lip line
- the configured target opening line
- a text readout showing:
  - center offset
  - left clearance
  - right clearance
  - configured forward target
  - live forward return inside the corridor

Close the window or press `Ctrl+C` to stop it.

## Live Tuning Inside the Demo

The demo now opens a separate clickable parameter panel window.

Any change you make there is written straight back into:

- [config/system_parameters.toml](/home/max/Desktop/Steer_Clear/config/system_parameters.toml)

This means you can tune the geometry while the demo is running and keep the values for the next launch.

How it works:

- click into a numeric field
- type a new value
- press `Enter` or click away to apply it live
- boolean or enum values appear as dropdowns
- `-` and `+` buttons do fine nudges
- `--` and `++` buttons do coarse nudges
- `Reload From TOML` reloads the file from disk
- `Clear Points` clears the current plot points

Keyboard fallback still exists, but it is no longer the main way to edit values.

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

- simulate demo
- live LiDAR demo
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
python scripts/lidar_live_view.py
```

If the dots look rotated incorrectly, edit:

- `mount.scan_angle_offset_deg`

in the parameter sheet and run the script again.

## Useful Test Command

This runs the visualizer for only 5 seconds:

```bash
python scripts/lidar_live_view.py --simulate --duration-seconds 5
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
- a short live RPLIDAR protocol test

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
