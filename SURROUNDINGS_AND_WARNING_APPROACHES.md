# Surroundings Recognition and Warning Approaches

This note proposes practical ways for the Steer Clear prototype to move from a simple LiDAR plot into a real docking-assist and surroundings-awareness system.

The focus here is a single-plane 2D LiDAR on a luggage loader approaching an aircraft cargo door.

## Key Constraint

The `RPLIDAR C1` is a 2D spinning sensor, so the system only sees what intersects the scan plane.

Inference:
If the scan plane does not cut through useful door and aircraft geometry, no software stack will fully recover the missing structure. That makes mount position, tilt, and calibration part of the sensing problem, not just a mechanical detail.

## Research Takeaways

### 1. Zone-based safety logic is a strong fit

The Nav2 Collision Monitor is built around user-defined polygons or circles that trigger behaviors like `stop`, `slowdown`, `limit`, or `approach` when enough points fall inside a zone. Their tutorial shows exactly the pattern of a small inner stop box and a larger outer slowdown box in front of the robot.

Why this matters for Steer Clear:
- this matches the "box warning" idea very well
- it is simple to explain to operators
- it is robust against imperfect object classification
- it can be implemented in plain Python without needing ROS first

Sources:
- https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html
- https://docs.nav2.org/tutorials/docs/using_collision_monitor.html

### 2. Filtering the scan before recognition is standard practice

The ROS `laser_filters` package includes filters for angular bounds, box filtering, polygon filtering, range filtering, speckle filtering, and masking.

Why this matters for Steer Clear:
- you can ignore scan sectors that always see the loader structure
- you can crop to a door-facing region of interest
- you can remove isolated speckle hits and bad reflections before computing warnings

Sources:
- https://docs.ros.org/en/noetic/api/laser_filters/html/annotated.html
- https://docs.ros.org/en/rolling/p/laser_filters/generated/classlaser__filters_1_1LaserScanAngularBoundsFilter.html

### 3. Segment extraction from 2D scans is mature and useful

The `obstacle_detector` ROS package extracts line segments and circles from 2D laser data, with configurable grouping, splitting, merging, and optional Kalman tracking.

Why this matters for Steer Clear:
- line segments are a natural fit for cargo door edges, fuselage returns, and lip-aligned structure
- this gives a middle ground between raw points and a full SLAM map
- tracking can later stabilize repeated obstacle detections

Source:
- https://github.com/tysik/obstacle_detector

### 4. Occupancy-grid style local surroundings maps are also standard

Nav2's obstacle layer uses 2D raycasting from `LaserScan` or `PointCloud2` data into a 2D costmap, with marking and clearing ranges.

Why this matters for Steer Clear:
- it is a strong pattern for "what space around the loader is occupied right now?"
- it can support keep-out areas and local monitoring even when the target opening is not recognized
- it is a good second-stage feature after basic docking assist works

Sources:
- https://docs.nav2.org/configuration/packages/costmap-plugins/obstacle.html
- https://docs.nav2.org/setup_guides/sensors/mapping_localization.html

### 5. Door localization from 2D LiDAR benefits from prior geometry plus region-of-interest cropping

The paper "Laser-Based Door Localization for Autonomous Mobile Service Robots" describes a practical pattern:
- convert polar scan data to Cartesian points
- use coarse prior door location
- crop a polygonal region of interest around the expected door
- fit lines with RANSAC
- recover hinge/lock/keypoints using known door geometry

Why this matters for Steer Clear:
- your loader use case also has strong prior geometry
- the lip is fixed relative to the sensor
- the approximate target area is known
- a model-based method is likely more realistic here than trying to classify the full scene end-to-end

Source:
- https://www.mdpi.com/1424-8220/23/11/5247

## Practical Approaches for Steer Clear

## Approach A: Geometry-Only Docking Overlay

What it is:
- treat lip position as known from mount geometry
- treat cargo opening location as a tunable target model
- compute center offset, left clearance, right clearance, and forward distance

Pros:
- fastest to ship
- easiest to tune
- already partially implemented in the current demo

Cons:
- not true recognition yet
- depends on the operator or setup knowing where the target should be
- can drift if the real scan orientation or mount geometry is off

Best use:
- mock rig
- early prototype demos
- first field tuning sessions

## Approach B: Loader-Frame Warning Boxes

What it is:
- define several rectangular or polygonal zones in loader coordinates
- count points inside each zone
- trigger warning states based on point count and persistence

Suggested zones:
- `front_stop_box`: immediate no-go zone close to the lip
- `front_slow_box`: larger approach zone ahead of the lip
- `left_intrusion_box`: protect left-side clearance envelope
- `right_intrusion_box`: protect right-side clearance envelope
- `upper_engine_side_box` or `aircraft_body_box`: later, if the scan plane intersects sensitive aircraft structure

Suggested outputs:
- `green`: clear
- `amber`: object in caution zone
- `red`: object in stop zone

Pros:
- robust
- understandable
- directly inspired by a proven robotics safety pattern
- does not require exact object classification

Cons:
- does not itself tell you what the object is
- needs tuning so loader structure is not falsely flagged

Recommendation:
- implement this next

## Approach C: ROI-Based Cargo Door Recognition

What it is:
- define a search region in front of the loader where the door should appear
- filter scan points to that region
- extract line segments or run a simple RANSAC line fit
- look for a door-opening signature:
  - fuselage returns on both sides
  - gap or reduced returns inside the opening
  - stable side edges of the opening

One practical version:
1. Crop to a door search polygon.
2. Remove points from known loader self-geometry.
3. Cluster remaining points by distance continuity.
4. Fit one or more line segments.
5. Estimate left edge, right edge, opening center, and forward distance.
6. Compare those against the lip geometry.

Pros:
- much more aligned with the real product goal
- naturally produces center offset and clearances
- can stay lightweight enough for Python on a Pi 5

Cons:
- depends strongly on scan-plane placement
- reflective aircraft skin, missing returns, and door-state variation may complicate edge extraction
- needs measured geometry and recorded test data

Recommendation:
- this should be the main recognition path after warning boxes

## Approach D: Local Occupancy Grid Around the Loader

What it is:
- maintain a 2D grid around the loader in loader coordinates
- mark cells as occupied when returns are seen
- clear cells along observed rays
- use that local map for visualization and danger logic

Pros:
- better surroundings awareness than raw points
- good for showing "occupied space" near engine nacelles, fuselage, carts, or people
- combines well with warning boxes

Cons:
- more state to manage
- still does not automatically identify the cargo opening
- harder to tune than simple boxes

Recommendation:
- useful as a second-generation surroundings layer, not as the first milestone

## Approach E: Tracked Obstacles and Semantic Labels

What it is:
- cluster obstacles over time
- track stable objects
- optionally assign labels like `fuselage`, `engine`, `cart`, `unknown`

Pros:
- good for long-term product maturity
- stronger remote monitoring and analytics potential
- useful later for logging and fleet-wide analysis

Cons:
- higher complexity
- hard to do reliably from a single 2D scan plane alone
- probably not the right first prototype step

Recommendation:
- defer until after docking guidance is stable

## Recommended Steer Clear Roadmap

Inference from the research and your use case:

### Phase 1: Ship a robust operator demo

- keep the current top-down viewer
- keep live-editable geometry parameters
- add warning boxes in loader coordinates
- add point-count and persistence thresholds
- show color-coded states for left, center, right, and front

This is the best next engineering step because it gives useful behavior quickly without pretending we already have perfect door recognition.

### Phase 2: Add true opening recognition

- add region-of-interest cropping for the expected cargo door area
- fit line segments or RANSAC lines
- estimate opening left edge, right edge, center, and depth
- compare those against the lip geometry

This is the most promising path for real docking assist.

### Phase 3: Add local surroundings memory

- maintain a short-term local occupancy grid
- show occupied cells in the plot
- use the grid to stabilize warnings and track nearby obstacles

This improves situational awareness around the loader, even outside the door-opening region.

## Suggested Operator Display Concepts

## Option 1: Minimal Numeric Guidance

- center offset in mm
- left clearance in mm
- right clearance in mm
- forward distance in mm
- one status line: `MOVE LEFT`, `MOVE RIGHT`, `CENTERED`, `STOP`

Best for:
- first prototype
- debugging

## Option 2: Numeric Guidance Plus Colored Boxes

- same numeric values as above
- front `slow` and `stop` boxes drawn on the plot
- left and right intrusion boxes drawn on the plot
- each box changes color based on occupancy

Best for:
- near-term field demo
- easy operator explanation

## Option 3: Centering Bar Plus Clearance Bars

- horizontal bar for lip-to-opening center offset
- left and right vertical bars showing remaining clearance
- forward distance bar with stop threshold

Best for:
- simple operator UI later
- cab display or external screen

## My Recommendation

If we keep this practical, the best next stack is:

1. `Current viewer + live parameter editor`
2. `Warning boxes in loader frame`
3. `Door ROI crop + line fitting`
4. `Later: local occupancy grid and obstacle tracking`

That gives you:
- something demoable quickly
- a path to robust docking guidance
- a path to broader collision-awareness later

## Concrete Next Build Step

The next code feature I would build is:

1. Add configurable warning polygons to the parameter sheet.
2. Count points inside each polygon with debounce logic.
3. Show `green/amber/red` states on the plot.
4. Add a dedicated cargo-door ROI box.
5. Start experimenting with door-edge extraction inside only that ROI.

That is the shortest path from "cool LiDAR plot" to "real operator assistance."
