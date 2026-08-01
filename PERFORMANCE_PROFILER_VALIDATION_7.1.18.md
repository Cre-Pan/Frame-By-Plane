# Frame By Plane 7.1.18 — performance profiler validation

## Verdict

**PASS.** The authoritative frame timing no longer runs with `tracemalloc` or detailed local handler profiling. Memory is sampled in a separate run, and the same-fixture calibration estimates detailed-profiling overhead independently.

## Controlled methodology

- Blender: 5.2.0 LTS
- OS: Windows 11 (`10.0.26200`)
- CPU: Intel64 Family 6 Model 154, 20 logical CPUs
- Scene: factory-startup empty scene, frames 1–120
- Mode: `PLAYBACK`, a CPU-side `scene.frame_set` approximation
- Warm-up: 8 frames
- Authoritative samples: 120
- Calibration samples: 24
- Allocation samples: 24
- Environment `FBP_PROFILE`: unset
- Network: not used

This is not a GPU presentation benchmark and is not a final-render benchmark. The UI/report names it a CPU-side Playback/Viewport/Render approximation according to the selected mode.

## Before/after validity

### Before follow-up (`a1a0435`)

The dashboard enabled detailed handler profiling and `tracemalloc` for the same 120-frame loop it reported as frame timing:

- average: 0.673725 ms;
- p95: 0.737500 ms;
- Python allocation delta: 7,670 bytes;
- detailed local profile: enabled during timing;
- `tracemalloc`: enabled during timing.

Those numbers describe instrumented execution and are not an authoritative normal-playback measurement.

### After follow-up

The 120 authoritative samples run with both instruments disabled:

- average: 0.088371 ms;
- p50: 0.088400 ms;
- p95: 0.090310 ms;
- max: 0.092300 ms;
- frames over 24 fps budget: 0;
- `timing_tracemalloc=false`;
- `timing_profile_enabled=false`;
- frame state restored: true.

The independent 240-frame default-off control measured 0.088806 ms average after versus 0.089206 ms before, a −0.45% difference. This is sub-millisecond run noise and does not indicate a normal-playback regression.

The apparent 86.75% dashboard improvement is not presented as an add-on runtime speedup. It is the removal of measurement distortion from the old dashboard path.

## Instrumentation calibration

The after build times a separate 24-frame same-fixture subset with detailed local profiling enabled:

- uninstrumented subset average: 0.088904 ms;
- detailed-profile average: 0.089475 ms;
- estimated overhead: **0.6421%**.

This is below the threshold for a substantial alteration of the empty-scene measurement. It is reported as an estimate, not subtracted from authoritative samples.

The 12-frame regression-contract run also records calibration, but its percentage varies because the sample is deliberately short. Release evidence therefore uses the dedicated 120/24-frame probe above, while the short suite verifies schema and invariants.

## Memory separation

Allocation tracing begins only after the authoritative and calibration timing runs complete. The after result reports:

- mode: separate allocation run with `tracemalloc`;
- samples: 24;
- initial Python bytes: 0;
- final Python bytes: 942;
- delta: 942 bytes;
- included in avg/p50/p95/max: false.

If an external allocation trace is already active, the profiler refuses to start instead of stopping or reusing instrumentation it does not own.

## Concurrency guards

Each guard is tested independently so guard ordering cannot hide a missing condition:

| Context | Expected/result |
| --- | --- |
| Animation playback active | Refused — PASS |
| Render state busy | Refused — PASS |
| FBP generation owner active | Refused — PASS |
| Undo/load guard active | Refused — PASS |
| Another FBP profiler active | Refused — PASS |
| External `tracemalloc` active | Refused — PASS |
| Interactive operator in background | Refused — PASS |

The internal measurement function remains callable by deterministic background regression probes. The UI operator is the surface that rejects unsupported background use.

## Transaction preparation scaling

Five samples were taken with 1k, 10k and 100k unrelated empty Mesh datablocks.

| Datablocks | Legacy snapshot median | Owned journal acquire+retire median |
| ---: | ---: | ---: |
| 1,000 | 0.2014 ms | 0.0803 ms |
| 10,000 | 1.8982 ms | 0.0761 ms |
| 100,000 | 73.1491 ms | 0.2410 ms |

The legacy scan grows about 363× from 1k to 100k in the final control. The production path remains below 0.25 ms and grows about 3× while the unrelated ID count grows 100×; it therefore does not exhibit the old linear/global-scan behavior. In the retained higher-load repetition, owner medians were 0.2591, 0.2283 and 0.2393 ms—flat across the same range. Absolute timing varied with system load, so both final runs are retained in the JSON.

## Hot-path buffers and counters

- Handler timing samples use `collections.deque(maxlen=2048)`; there is no front deletion or list shifting.
- Detailed per-handler timings remain gated by Developer/Profile mode.
- Minimal scheduler/icon counters remain always-on because the independent default-off frame control did not show meaningful regression.
- Grease Pencil/Layer Tree interactive stress completed 300 redraw cycles in 2.7187 s on the final run.

## Remaining profiler limitation

The 120-frame UI profile is synchronous. It refuses unsafe concurrent states and restores the original frame in `finally`, but it does not expose mid-run Cancel. Converting it to incremental modal execution would add another timer/progress owner and was not justified for this stability patch. This is an accepted UX limitation, not a correctness blocker.

Full machine-readable data and methodology are in `PERFORMANCE_BEFORE_AFTER_7.1.18.json`.
