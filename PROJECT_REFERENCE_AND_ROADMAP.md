# Steer Clear Prototype Sensor System

## Purpose of This Document

This document is the working reference for the current Steer Clear luggage-loader docking prototype. It captures:

- the business context
- the prototype goal
- the mounting geometry known so far
- hardware facts that have been checked against current documentation
- key engineering implications
- a practical roadmap toward a working system

This is a living document and should be updated as new measurements, tests, and decisions come in.

## Company / Product Context

- Company: Steer Clear
- Focus: custom sensor- and data-based solutions for airport operations
- Main current theme: collision avoidance and close-range docking support for airport ground vehicles
- Broader product direction:
  - safer docking and maneuvering
  - adaptable systems for different airport applications
  - vehicle tracking
  - operational data collection
  - process insight and data-driven improvement
- Development stage: ongoing, currently around the second prototype level rather than a finished product

One-sentence summary:

Steer Clear develops adaptable airport sensor systems for safer docking and maneuvering, while also building toward vehicle tracking and operational data analysis.

## Current Prototype Goal

Build a Raspberry Pi 5 based prototype that uses a Slamtec RPLIDAR C1 to help a luggage-loader operator dock the belt lip into an aircraft cargo door opening.

The first useful system should provide:

- left/right alignment information
- forward distance information
- a stable geometric estimate of where the loader lip is relative to the cargo door opening

For now, the output can be a raw readout or developer-facing display. A polished operator interface comes later.

## User-Confirmed Project Inputs

The following details were provided on April 19, 2026 and should be treated as the current working assumptions.

### Loader / Mounting Geometry

- The LiDAR will be attached on the railing running parallel to the loader belt.
- The LiDAR will be on the right side of the belt, opposite the cockpit.
- The sensor is expected to sit about 75 cm above the belt.
- The sensor position is expected to be about 1.5 to 2.0 meters behind the lip end of the loader.
- The sensor mount is intended to be fixed relative to the loader geometry.
- The preferred aim is slightly above the loader lip, so the sensor still has a clear view while allowing the lip position to be inferred from fixed geometry.

### Prototype Behavior

- The system should be as universal as possible rather than tailored to only one aircraft type.
- The first priority is left/right alignment.
- The first prototype should also provide forward distance measurement.
- The target ambition is roughly centimeter-level guidance.
- For now, the desired output is simply left, right, and forward distance/readout.
- More developed user outputs can be added later.

### Integration Direction

- The LiDAR is not yet connected to the Raspberry Pi 5.
- USB connection is available.
- There is also interest in understanding whether the raw 4-wire interface could be connected directly to Raspberry Pi GPIO/UART.
- There is interest in placing the Raspberry Pi in the cockpit and the sensor remotely on the other side of the vehicle, implying a cable run of roughly 6 meters.

### Later Product Direction

Future expansion should include:

- SIM-based internet connectivity for the Pi
- GPS position logging
- periodic and, when possible, live upload of GPS coordinates and LiDAR-derived readouts to a database
- remote monitoring
- later operational data analysis

This telemetry work is not the first implementation milestone, but the architecture should leave room for it.

### Current Development Decisions

- Real aircraft-specific tuning is not needed yet because the first tests can use a mock setup.
- Operation below minus 10 C is not a requirement for the current phase.
- The first readout should expose:
  - center offset
  - left clearance
  - right clearance
  - forward distance
- All main geometric assumptions should live in one editable parameter sheet so they can be tuned quickly without changing code.

## Photo Review Notes

The reference photos in the workspace were reviewed together with the images supplied in chat.

Key observations from the photos:

- The suggested railing mount location is realistic and visible on the loader.
- There appears to be enough physical structure to mount a protected LiDAR enclosure on the upper side railing near the front half of the loader.
- The cockpit appears to have enough room for a Raspberry Pi, power conversion, and a temporary debug display.
- The use case includes real ramp conditions:
  - night operation
  - rain / wet ramp
  - winter / snow conditions
- The image set shows at least two aircraft geometry families:
  - Boeing 737 MAX 8 style lower cargo door area
  - regional jet / rear-fuselage cargo hold geometry with the engine above the loader region

Engineering implication from the photos:

- A long-term universal system is possible as a goal, but the geometry is clearly not identical across aircraft families.
- The first version should therefore be geometry-based and calibration-aware, not based on one hardcoded aircraft silhouette.
- Even so, the first successful milestone will likely be easier if initial testing starts on one loader and one aircraft family before generalizing.

## Core Technical Problem

The prototype needs to solve a real-time perception-and-guidance task:

1. Acquire LiDAR scans on the Raspberry Pi 5
2. Express the scan in a loader-fixed coordinate frame
3. Use the fixed mount geometry to know where the loader lip is
4. Detect the aircraft-side geometry relevant to docking
5. Estimate left/right offset between lip center and door target zone
6. Estimate forward distance to the docking target
7. Present a stable readout that is useful during approach

## Important Geometric Insight

The RPLIDAR C1 is fundamentally a 2D LiDAR, not a 3D sensor. That means it measures a thin scanning plane rather than a full volume.

This has a major consequence for the project:

- the exact sensor height matters
- the exact tilt matters
- the scan plane must intersect useful geometric features

For this prototype, the scan plane likely needs to intersect some combination of:

- the left and right boundaries of the cargo door opening
- the nearby fuselage boundary
- a known reference geometry tied to the loader lip

If the scan plane passes too high or too low, the system may miss the door edges entirely even if the sensor is otherwise working correctly.

## Validated Hardware Facts: RPLIDAR C1

The following points were checked against current SLAMTEC documentation.

- Sensor: SLAMTEC RPLIDAR C1
- Type: 360-degree 2D triangulation LiDAR
- Range:
  - up to 12 m on objects with 80% reflectivity
  - up to 6 m on objects with 10% reflectivity
- Typical ranging accuracy: plus/minus 30 mm
- Distance resolution: less than 15 mm
- Sample rate: 5 kHz
- Typical scan frequency: 10 Hz
- Supported scan frequency range: 8 to 12 Hz
- Angular resolution at 10 Hz: about 0.72 degrees
- Supply voltage: 5 V
- Startup current can be high, about 800 mA peak
- Typical current after startup is about 230 to 260 mA
- Communication:
  - UART
  - 460800 baud
  - logic level listed as 0 to 3.5 V
- Software support:
  - Windows
  - Linux
  - ROS / SDK support
  - ARM Linux is supported, which is relevant for Raspberry Pi
- Operating temperature: minus 10 C to plus 40 C
- Allowed ambient light: up to 40,000 lux
- Ingress rating: IP54

## Engineering Meaning of Those Specs

### Accuracy and Resolution Reality Check

The spec sheet gives a typical range accuracy of plus/minus 30 mm. That is already larger than a strict 10 mm absolute target.

That does not automatically mean the project is impossible. It means:

- raw single-point absolute accuracy is not centimeter-class
- centimeter-class guidance may still be approached through filtering, frame averaging, edge fitting, and fixed known loader geometry
- the safest way to describe the first target is:
  - robust alignment guidance with approximately centimeter-scale usefulness in controlled geometry
  - not guaranteed 10 mm raw metrology on every scan

### Weather / Daylight / Temperature Risks

The environmental limits matter for airport use:

- minus 10 C lower operating limit is a concern for northern winter operations
- 40,000 lux ambient-light limit is a concern for bright daylight and snow-reflection conditions
- IP54 is not the same as a fully rugged vehicle-mounted outdoor enclosure

Conclusion:

- the sensor likely needs a real enclosure strategy
- cold-weather validation is important
- if winter operations go below minus 10 C, sensor heating or a different sensor class may be required

### System Architecture Implication

This sensor is a good candidate for a proof-of-concept and geometry experiment.

It is not yet proven to be the final production sensor for all airport environments and all seasons.

## Angular Resolution and Lateral Spacing Calculation

You asked for a concrete estimate of what the sensor's angular resolution means at roughly 2 to 3 meters.

### Why This Calculation Matters

The LiDAR measures distance along many angular directions. Even if the range reading itself is good, the left/right spacing between adjacent rays becomes wider as distance increases.

That lateral spacing can be approximated as:

`lateral_spacing = distance * tan(angle_step)`

This is useful because it tells us how finely the sensor samples the cargo-door geometry across left/right space.

### At Typical 10 Hz Operation

At 10 Hz, the C1 is specified at about 0.72 degrees angular resolution.

| Distance from target | Approximate spacing between adjacent rays |
| --- | --- |
| 2.0 m | 25.1 mm |
| 2.5 m | 31.4 mm |
| 3.0 m | 37.7 mm |

### Scan-Rate Tradeoff

The C1 supports about 8 to 12 Hz. Because the sample rate is 5 kHz, slower rotation gives more points per revolution and therefore finer angular spacing.

| Scan rate | Angular resolution | 2.0 m spacing | 2.5 m spacing | 3.0 m spacing |
| --- | --- | --- | --- | --- |
| 8 Hz | 0.576 degrees | 20.1 mm | 25.1 mm | 30.2 mm |
| 10 Hz | 0.72 degrees | 25.1 mm | 31.4 mm | 37.7 mm |
| 12 Hz | 0.864 degrees | 30.2 mm | 37.7 mm | 45.2 mm |

### Practical Interpretation

- At 2 to 3 meters, the raw angular sampling of the scene is on the order of 2 to 4 cm between adjacent rays.
- The ranging accuracy is on the order of plus/minus 3 cm.
- Therefore, a strict 1 cm absolute measurement claim would be too optimistic if based on raw scan points alone.
- However, if the cargo door edges create stable multi-point geometry and the lip position is known from rigid mount geometry, the final guidance estimate may still become more stable than a single raw point measurement.

Working conclusion:

- centimeter-level guidance may be possible as a filtered system behavior
- strict centimeter-level raw sensor accuracy should not be assumed

## Loader Lip Strategy

Your current idea is good:

- keep the sensor aimed slightly above the lip
- treat the lip location as known from the fixed mount geometry rather than trying to see every part of the lip directly

That is likely the right first approach because:

- it simplifies perception
- it avoids depending on direct visibility of the lip under all conditions
- it uses the fact that the sensor is rigidly mounted to the loader

This means the early system can focus on:

1. calibration between LiDAR frame and loader frame
2. estimating cargo-door target geometry in the LiDAR frame
3. converting that to lip-relative left/right and forward distance

## Electrical / Wiring Notes

### RPLIDAR C1 4-Wire Interface

The SLAMTEC C1 manual lists the standard cable colors as:

- red: VCC 5V
- black: GND
- yellow: TX
- green: RX

Other checked communication facts:

- UART baud rate: 460800
- logic level: 0 to 3.5 V

### Can It Be Wired Directly to Raspberry Pi GPIO?

Possible in principle, but not my recommendation for this project.

Why:

- Raspberry Pi GPIO is 3.3 V only
- the C1 communication level is specified up to 3.5 V
- the serial rate is relatively high at 460800 baud
- a vehicle environment is electrically noisy compared with a bench setup

Recommended approach:

- use the supplied or intended USB/UART adapter path first
- connect the LiDAR to the Pi as a USB serial device

That is the fastest, lowest-risk bring-up path.

If direct GPIO UART is ever tried, it should be done only after checking the exact converter board and signal level with a meter or scope, or by using a proper level shifter.

Short answer to the question "why not 4-pin UART?":

- for a short bench setup it may work
- for a first vehicle demo, USB is lower risk
- the voltage margin is not ideal
- the baud rate is fairly high
- a loader is a noisier electrical environment than a desk setup

### Extending the Sensor Connection by About 6 Meters

My engineering recommendation is:

- do not rely on a 6-meter run of raw TTL UART wires in this environment unless testing proves it is stable

Why:

- TTL UART is not intended as a robust long-distance field bus
- 460800 baud is fast enough that cable quality, noise, grounding, and routing matter
- the loader environment includes motors, switching loads, vibration, and weather exposure

Better options:

1. Use the LiDAR through USB and keep the USB run as robust as possible.
2. If the Pi must stay in the cockpit, use a higher-quality extension strategy rather than raw UART wires.
3. If long runs are necessary, convert to a differential link such as RS-485 near the sensor rather than extending bare TTL serial.

Working recommendation for prototype v1:

- put the LiDAR on USB first
- keep cable lengths modest if possible
- if cockpit placement is mandatory, test the full cable route early before building software around it

## Programming Language Recommendation

You asked whether Python, C++, or Go is the best choice, especially given that most code will be AI-assisted.

### Python

Pros:

- fastest for prototyping
- strongest ecosystem for quick geometry, filtering, plotting, and debugging
- very good for NumPy, plotting, and quick point-cloud style analysis
- easiest to iterate with AI assistance
- easiest to build the first data logger and visualization tool on Raspberry Pi

Cons:

- slower than C++ for heavier real-time processing
- can become messy if not structured well
- not the best long-term choice for a highly optimized embedded production system

### C++

Pros:

- best performance
- closest to typical robotics / embedded perception stacks
- strong choice if the system later needs ROS integration or tighter real-time control
- good fit for production-grade geometry processing

Cons:

- slower to iterate
- more development overhead
- debugging and refactoring take more effort

### Go

Pros:

- clean concurrency model
- excellent for services, networking, APIs, and telemetry backends
- simple deployment for backend tools

Cons:

- much weaker ecosystem for LiDAR / robotics / geometry work than Python or C++
- fewer off-the-shelf examples for this exact type of sensor-processing pipeline
- not the best first language for this perception prototype

### Recommendation

Best plan:

- use Python for prototype v1
- use Python to do:
  - LiDAR acquisition
  - calibration experiments
  - geometry visualization
  - left/right and forward estimation
  - logging and replay
- if performance becomes limiting later, move only the heavy geometry or filtering parts to C++
- keep Go in mind for the later telemetry / backend side, not for the first docking-perception prototype

## Existing Software Reused for This Repo

The current starter implementation intentionally uses existing code where practical.

- Official SLAMTEC documentation and SDK direction are used for the device-level understanding.
- A Python package called `rplidarc1` is used for quick C1 scan access in Python.
- The local demo script adds:
  - loader-frame coordinate conversion
  - the editable parameter sheet
  - the top-view live graph
  - a simple center/clearance/forward readout

Current local files added for this:

- [README.md](/home/max/Desktop/Steer_Clear/README.md)
- [config/system_parameters.toml](/home/max/Desktop/Steer_Clear/config/system_parameters.toml)
- [scripts/lidar_live_view.py](/home/max/Desktop/Steer_Clear/scripts/lidar_live_view.py)
- [scripts/show_serial_ports.py](/home/max/Desktop/Steer_Clear/scripts/show_serial_ports.py)
- [SURROUNDINGS_AND_WARNING_APPROACHES.md](/home/max/Desktop/Steer_Clear/SURROUNDINGS_AND_WARNING_APPROACHES.md)

Current local tooling status:

- the demo now includes live parameter editing inside the graph window
- geometry changes are autosaved back into the parameter sheet
- this makes it possible to tune mount location, lip geometry, target geometry, guidance corridor values, and visualization ranges while the demo is running

## Suggested Later LTE / GNSS Module

For the later telemetry phase, the best current fit I found is:

- Waveshare SIM7600G-H 4G HAT (B)

Why it looks like a good fit:

- works with Raspberry Pi boards
- combines LTE connectivity with GNSS support
- uses the SIM7600G-H module, which supports European LTE bands including B1, B3, B7, B8, B20, and B28
- widely documented and common in Raspberry Pi projects

Important note:

- I could validate the module and its features from Waveshare documentation
- I could not reliably extract a live Amazon.se product page from this environment because Amazon returned an error page to automated fetches

Practical buying note:

- if you buy via Amazon.se, search for the exact model name:
  - `Waveshare SIM7600G-H 4G HAT (B)`

Telemetry architecture note for later:

- when that phase starts, the system should upload:
  - timestamp
  - GPS position
  - loader ID
  - aircraft / stand metadata if known
  - left/right offset estimate
  - forward distance estimate
  - quality / confidence metrics
  - optionally compressed or sampled raw scan data for offline analysis

## Proposed System Architecture for Prototype v1

### Inputs

- RPLIDAR C1 scan stream
- fixed calibration from LiDAR frame to loader frame
- loader geometry constants

### Core Processing

1. Read and timestamp scans
2. Filter invalid and unstable points
3. Convert scan to loader-fixed coordinates
4. Identify candidate aircraft-side geometry near the cargo door opening
5. Estimate target center / left edge / right edge
6. Use fixed mount geometry to project lip center into the same frame
7. Compute:
   - left/right offset
   - forward distance
   - confidence

### Outputs for v1

- numeric left/right offset
- numeric forward distance
- simple textual state such as:
  - left
  - right
  - centered
  - approach
  - stop

### Non-Goals for v1

- polished driver UI
- full fleet telemetry platform
- universal all-aircraft performance claim
- production weatherproof certification

## Roadmap

### Phase 1: Mechanical Definition

- measure the exact mount point on the railing
- measure offset from sensor center to lip centerline
- measure sensor height above belt
- define pitch / yaw / roll of the mount
- define enclosure concept

### Phase 2: Electrical Bring-Up

- connect the C1 over USB to the Raspberry Pi 5
- verify serial device detection
- confirm stable scan acquisition
- confirm power behavior during startup
- test the intended cable path if the Pi stays in the cockpit

### Phase 3: Logging and Visualization

- build a Python scan logger
- build a 2D visualization tool
- keep all geometry in a single editable parameter sheet
- support live parameter tuning during the visualization session
- use a simulation mode before the live sensor is fully connected
- record real approach sequences
- replay recordings offline

### Phase 4: Calibration

- establish LiDAR-to-loader coordinate transform
- encode lip geometry relative to the sensor
- verify calibration repeatability after remounting

### Phase 5: Geometry Detection

- identify cargo-door side edges or equivalent target features
- estimate door centerline
- estimate forward distance
- compute lip-to-door offset

### Phase 6: Guidance Readout

- present left/right and forward values in a debug display
- explicitly show:
  - center offset
  - left clearance
  - right clearance
  - forward distance
- smooth output to avoid flicker
- add confidence and invalid-state handling

### Phase 7: Robustness Testing

- test across rain, wet surfaces, and night ramp conditions
- test in winter temperatures
- test across at least two aircraft geometry families
- evaluate whether the C1 remains acceptable or whether a different LiDAR class is needed

### Phase 8: Telemetry Expansion

- add LTE/GNSS hardware
- log position and docking metrics
- upload to a database
- build later analytics and monitoring tools

## Git / Backup Workflow

This folder should be treated as a git repo and backed up to:

- `https://github.com/MaxSch17799/Luggage_Loader_System.git`

Recommended working habit:

- commit after each meaningful milestone
- push after each meaningful milestone

Typical commands:

```bash
git status
git add .
git commit -m "Describe the milestone"
git push origin main
```

## Key Risks

- The 2D scan plane may miss the most useful door geometry if the mount height or tilt is wrong.
- The C1 environmental limits may be too weak for year-round airport use in northern climates.
- A universal system is harder because the aircraft geometry in the photos already varies noticeably.
- Raw sensor specs do not guarantee true 10 mm absolute docking accuracy.
- Cable extension from sensor to cockpit may become a real reliability issue if done with raw TTL wiring.

## Immediate Recommendation

The best next move is not writing docking logic yet. The best next move is:

1. finalize the exact mount geometry
2. bring the sensor up on USB
3. log real scans near a cargo door
4. verify that the scan plane actually intersects useful geometry

If that geometry looks good, the rest of the software plan is straightforward.

Related design note:

- [SURROUNDINGS_AND_WARNING_APPROACHES.md](/home/max/Desktop/Steer_Clear/SURROUNDINGS_AND_WARNING_APPROACHES.md) now captures researched options for warning boxes, ROI-based door recognition, occupancy grids, and longer-term surroundings awareness.

## Questions To Answer Next

These are now the most important unanswered questions.

1. Can you measure the exact sensor position relative to the lip centerline:
   - how far back from the lip tip
   - how far left/right from the belt center
   - exact height above the belt
2. What power is available in the loader cockpit for the Pi and later LTE module?
3. What is the best temporary mock target we should build for the first calibration session:
   - two vertical posts
   - a rectangular mock opening
   - a flat panel with a cutout
4. Should the first live tests happen with the Pi in the cockpit and the LiDAR connected by a temporary USB route, or should the Pi sit close to the sensor for bench bring-up first?
5. Once the exact measurements are available, which parameters in the sheet should be treated as locked geometry and which should remain operator-tunable?

## Reference Images in This Folder

The following files are useful reference images for the mounting and use case:

- `Luggage loader close up cargo door user view.jpeg`
- `Luggage loader close up cargo door.jpeg`
- `Luggage loader front view.jpeg`
- `Luggage loader interior close.jpeg`
- `Luggage loader interior wide.jpeg`
- `Luggage loader wide angle plane.jpeg`
- `Luggage loader wide angle.jpeg`
- `Luggage loader wide view bad back.jpeg`
- `Luggage loader wide view good.jpeg`

## Sources Checked on April 19, 2026

- SLAMTEC RPLIDAR C1 datasheet:
  - https://wiki.slamtec.com/download/attachments/83066883/SLAMTEC_rplidar_datasheet_C1_v1.0_en.pdf
- SLAMTEC RPLIDAR C1 user manual:
  - https://bucket-download.slamtec.com/54b4c03d64a293b2721639f0cd21edee209b886b/SLAMTEC_rplidarkit_usermanual_C1_v1.0_en.pdf
- Official SLAMTEC SDK:
  - https://github.com/Slamtec/rplidar_sdk
- `rplidarc1` Python package:
  - https://pypi.org/project/rplidarc1/
- `rplidarc1` source repository:
  - https://github.com/dsaadatmandi/rplidarc1
- Raspberry Pi documentation for GPIO voltage guidance:
  - https://www.raspberrypi.com/documentation/hardware/raspberrypi/gpio/
- Waveshare SIM7600G-H 4G HAT product page:
  - https://www.waveshare.com/SIM7600G-H-4G-HAT.htm
