# Frame By Plane 7.1.10 LTS — Build report

## Source baseline

- Previous release: 7.1.9 LTS
- Current release: 7.1.10 LTS
- Blender API target: 5.2.x
- Python target: 3.13

## Implemented contracts

- Deferred callbacks are rejected when the bounded RNA scan cannot prove the payload safe.
- Wrapper-based deferred systems revalidate the actual callback at dispatch time.
- Generic Mesh batch application is all-or-nothing across the selected objects.
- Compositor Safe Repair cannot proceed with partial nested artist-group snapshots.
- Snapshot read errors are surfaced as explicit incomplete-graph diagnostics.

## Validation scope

- Python parsing and bytecode compilation.
- Duplicate Blender identifier detection.
- UI operator and menu reference validation.
- Runtime timer registration audit.
- PNG integrity verification.
- Scheduler RNA-capture and facade-mutation self-tests with a Blender stub.
- Platform manifest and wheel isolation.
- Cross-platform common-payload equality.
- ZIP CRC and SHA-256 generation.

## Native execution status

The official Blender Foundation `bpy 5.2.0` Linux wheel is available for Python 3.13, but the binary download was blocked by the container DNS. Native Blender RNA, GPU, render and interactive UI suites remain included in the source archive and are not claimed as executed in this environment.
