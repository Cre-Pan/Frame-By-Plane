# Frame by Plane 4.8.6 — Presets and Effect Settings

This reference is generated from the registered Blender RNA properties and the built-in preset dictionary. Internal property IDs are included so values can be changed directly in `geometry_nodes.py` or `properties.py`.

## Common controls

- **Eye:** viewport visibility only.
- **Camera:** render visibility.
- **Input Source:** Previous Effects, Original Material or Final Material, when supported.
- **Procedural Noise:** Evolve, Stepped, Seed and Unique per Layer, when supported.

## Image Effects — Base

### Crop — `MOD_BOOLEAN`

- ID: `CROP`
- Backend: `BASE`
- Performance: `LIGHT`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Top | `fbp_crop_top` | FLOAT | 0 | 0 → 1.95 |
| Left | `fbp_crop_left` | FLOAT | 0 | 0 → 1.95 |
| Right | `fbp_crop_right` | FLOAT | 0 | 0 → 1.95 |
| Bottom | `fbp_crop_bottom` | FLOAT | 0 | 0 → 1.95 |

#### Built-in presets

_No built-in presets._

### Extend — `FULLSCREEN_ENTER`

- ID: `EXTEND`
- Backend: `BASE`
- Performance: `LIGHT`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Extend Mode | `fbp_extend_mode` | ENUM | EDGE | `EDGE`, `REPEAT` |
| Top | `fbp_extend_top` | FLOAT | 0 | 0 → 3.40282e+38 |
| Left | `fbp_extend_left` | FLOAT | 0 | 0 → 3.40282e+38 |
| Right | `fbp_extend_right` | FLOAT | 0 | 0 → 3.40282e+38 |
| Bottom | `fbp_extend_bottom` | FLOAT | 0 | 0 → 3.40282e+38 |

#### Built-in presets

_No built-in presets._

### Tint — `IMAGE`

- ID: `SOLID_MASK`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Mask Color | `fbp_solid_mask_color` | FLOAT | [0, 0, 0, 1] | 0 → 1 |
| Mask Factor | `fbp_solid_mask_factor` | FLOAT | 0.5 | 0 → 1 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### Hue / Saturation — `COLOR`

- ID: `HUE_SATURATION`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Hue | `fbp_hue_saturation_hue` | FLOAT | 0.5 | 0 → 1 |
| Saturation | `fbp_hue_saturation_saturation` | FLOAT | 1 | 0 → 3.40282e+38 |
| Value | `fbp_hue_saturation_value` | FLOAT | 1 | 0 → 3.40282e+38 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### Brightness / Contrast — `IMAGE_ZDEPTH`

- ID: `BRIGHTNESS_CONTRAST`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Brightness | `fbp_brightness_contrast_brightness` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Contrast | `fbp_brightness_contrast_contrast` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |

#### Built-in presets

_No built-in presets._

### Invert — `IMAGE_ALPHA`

- ID: `INVERT`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Factor | `fbp_invert_factor` | FLOAT | 1 | 0 → 1 |

#### Built-in presets

_No built-in presets._

### Threshold — `MOD_MASK`

- ID: `THRESHOLD`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Threshold | `fbp_threshold_value` | FLOAT | 0.5 | 0 → 1 |

#### Built-in presets

_No built-in presets._

### Color Isolate — `EYEDROPPER`

- ID: `COLOR_ISOLATE`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Target Color | `fbp_color_isolate_target` | FLOAT | [1, 0, 0, 1] | 0 → 1 |
| Tolerance | `fbp_color_isolate_tolerance` | FLOAT | 0.15 | 0 → 1 |
| Falloff | `fbp_color_isolate_falloff` | FLOAT | 0.1 | 0 → 1 |

#### Built-in presets

_No built-in presets._

### Duotone — `MOD_TINT`

- ID: `DUOTONE`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Shadows Tone | `fbp_duotone_shadows` | FLOAT | [0, 0, 0.2, 1] | 0 → 1 |
| Highlights Tone | `fbp_duotone_highlights` | FLOAT | [1, 0.8, 0.6, 1] | 0 → 1 |

#### Built-in presets

_No built-in presets._

### Chroma Key — `EYEDROPPER`

- ID: `CHROMA_KEY`
- Backend: `SHADER` / `COLOR`
- Performance: `MEDIUM`
- Preview modes: `Final`, `Matte`, `Distance`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Key Color | `fbp_chroma_key_color` | FLOAT | [0, 1, 0, 1] | 0 → 1 |
| Tolerance | `fbp_chroma_key_tolerance` | FLOAT | 0.2 | 0 → 1.732 |
| Softness | `fbp_chroma_key_softness` | FLOAT | 0.08 | 0 → 1 |
| Despill | `fbp_chroma_key_despill` | FLOAT | 0.5 | 0 → 1 |
| Invert | `fbp_chroma_key_invert` | BOOLEAN | Off |  |

#### Built-in presets

**Green Screen**

- `fbp_chroma_key_color` = `[0, 1, 0, 1]`
- `fbp_chroma_key_tolerance` = `0.2`
- `fbp_chroma_key_softness` = `0.08`
- `fbp_chroma_key_despill` = `0.65`

**Blue Screen**

- `fbp_chroma_key_color` = `[0, 0.18, 1, 1]`
- `fbp_chroma_key_tolerance` = `0.2`
- `fbp_chroma_key_softness` = `0.08`
- `fbp_chroma_key_despill` = `0.55`


## Mesh Effects

### Wiggle — `MOD_NOISE`

- ID: `MESH_WIGGLE`
- Backend: `GEOMETRY`
- Performance: `MEDIUM`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Subdivision | `fbp_mesh_wiggle_subdivisions` | INT | 4 | 0 → 6 |
| Shade Smooth | `fbp_mesh_wiggle_shade_smooth` | BOOLEAN | On |  |
| Stepped | `fbp_mesh_wiggle_hold` | INT | 4 | 1 → 2147483647 |
| Strength | `fbp_mesh_wiggle_strength` | FLOAT | 1 | 0 → 3.40282e+38 |
| Speed | `fbp_mesh_wiggle_speed` | FLOAT | 10 | -3.40282e+38 → 3.40282e+38 |
| W | `fbp_mesh_wiggle_w` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Noise Scale | `fbp_mesh_wiggle_noise_scale` | FLOAT | 5 | 0.001 → 3.40282e+38 |
| Noise Detail | `fbp_mesh_wiggle_detail` | FLOAT | 0 | 0 → 3.40282e+38 |

#### Built-in presets

_No built-in presets._

### Stop Motion Crumple — `MOD_DISPLACE`

- ID: `STOP_MOTION_CRUMPLE`
- Backend: `GEOMETRY`
- Performance: `HEAVY`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Resolution | `fbp_stop_motion_resolution` | INT | 5 | 0 → 6 |
| Strength | `fbp_stop_motion_strength` | FLOAT | 0.05 | 0 → 3.40282e+38 |
| Step Frames | `fbp_stop_motion_step_frames` | INT | 3 | 1 → 2147483647 |

#### Built-in presets

_No built-in presets._

### Wind Bender — `FORCE_WIND`

- ID: `WIND_BENDER`
- Backend: `GEOMETRY`
- Performance: `MEDIUM`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Subdivision | `fbp_wind_subdivision` | INT | 4 | 0 → 6 |
| Bend Amount | `fbp_wind_bend_amount` | FLOAT | 0.5 | -3.40282e+38 → 3.40282e+38 |
| Wind Speed | `fbp_wind_speed` | FLOAT | 2 | -3.40282e+38 → 3.40282e+38 |
| Stepped | `fbp_wind_stepped` | INT | 1 | 1 → 2147483647 |
| Pin Edge | `fbp_wind_pin_edge` | ENUM | LEFT | `LEFT`, `RIGHT`, `BOTTOM`, `TOP` |
| Motion Mode | `fbp_wind_motion_mode` | ENUM | SWAY | `SWAY`, `FLOW` |
| Wave Count | `fbp_wind_wave_count` | FLOAT | 2 | 0 → 40 |
| Wave Amplitude | `fbp_wind_wave_amplitude` | FLOAT | 0.12 | 0 → 10 |
| Wave Speed | `fbp_wind_wave_speed` | FLOAT | 2 | -3.40282e+38 → 3.40282e+38 |
| Phase | `fbp_wind_phase` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Turbulence | `fbp_wind_turbulence` | FLOAT | 0.03 | 0 → 2 |
| Reverse Direction | `fbp_wind_reverse` | BOOLEAN | Off |  |
| Falloff | `fbp_wind_falloff` | FLOAT | 1.5 | 0.1 → 8 |
| Noise Scale | `fbp_wind_noise_scale` | FLOAT | 3 | 0.01 → 100 |
| Gust Strength | `fbp_wind_gust_strength` | FLOAT | 0 | 0 → 4 |
| Direction Space | `fbp_wind_direction_space` | ENUM | LOCAL | `LOCAL`, `WORLD` |
| Wind Direction | `fbp_wind_direction` | VECTOR | [0, 0, 1] | -1 → 1 |
| Preview Falloff | `fbp_wind_preview_falloff` | BOOLEAN | Off |  |

#### Built-in presets

**Gentle Breeze**

- `fbp_wind_bend_amount` = `0.18`
- `fbp_wind_speed` = `1.1`
- `fbp_wind_turbulence` = `0.018`
- `fbp_wind_gust_strength` = `0.12`
- `fbp_wind_falloff` = `1.4`

**Flag**

- `fbp_wind_motion_mode` = `FLOW`
- `fbp_wind_wave_count` = `2.5`
- `fbp_wind_wave_amplitude` = `0.16`
- `fbp_wind_wave_speed` = `2.1`
- `fbp_wind_turbulence` = `0.025`
- `fbp_wind_falloff` = `1`

**Strong Flag**

- `fbp_wind_motion_mode` = `FLOW`
- `fbp_wind_bend_amount` = `0.42`
- `fbp_wind_speed` = `2.4`
- `fbp_wind_wave_count` = `3.2`
- `fbp_wind_wave_amplitude` = `0.26`
- `fbp_wind_wave_speed` = `3`
- `fbp_wind_turbulence` = `0.055`
- `fbp_wind_gust_strength` = `0.38`
- `fbp_wind_falloff` = `0.9`

**Strong Gusts**

- `fbp_wind_bend_amount` = `0.55`
- `fbp_wind_speed` = `2.8`
- `fbp_wind_turbulence` = `0.09`
- `fbp_wind_gust_strength` = `0.65`
- `fbp_wind_noise_scale` = `2.2`


### Thickness — `MOD_SOLIDIFY`

- ID: `THICKNESS`
- Backend: `GEOMETRY`
- Performance: `HEAVY`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Thickness | `fbp_thickness_amount` | FLOAT | 0.02 | 0 → 3.40282e+38 |
| Alpha Threshold | `fbp_thickness_alpha_threshold` | FLOAT | 0.05 | 0 → 1 |
| Alpha Resolution | `fbp_thickness_alpha_resolution` | INT | 5 | 0 → 6 |
| Side / Back Material | `fbp_thickness_side_material` | POINTER | None |  |
| Side / Back Color | `fbp_thickness_side_color` | FLOAT | [0.18, 0.12, 0.08, 1] | 0 → 1 |

#### Built-in presets

**Cardboard Poster**

- `fbp_thickness_amount` = `0.018`
- `fbp_thickness_alpha_threshold` = `0.12`
- `fbp_thickness_alpha_resolution` = `256`


### Infinite Rotation — `DRIVER_ROTATIONAL_DIFFERENCE`

- ID: `INFINITE_ROTATION`
- Backend: `GEOMETRY`
- Performance: `LIGHT`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Speed | `fbp_infinite_rotation_speed` | FLOAT | 1 | 0 → 3.40282e+38 |
| Direction | `fbp_infinite_rotation_direction` | ENUM | RIGHT | `RIGHT`, `LEFT` |
| Stepped | `fbp_infinite_rotation_stepped` | INT | 1 | 1 → 2147483647 |
| Offset | `fbp_infinite_rotation_offset` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |

#### Built-in presets

_No built-in presets._

### Felt Fuzz — `MOD_NOISE`

- ID: `FELT_FUZZ`
- Backend: `GEOMETRY`
- Performance: `VERY_HEAVY`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Render Density | `fbp_felt_render_density` | INT | 50000 | 1000 → 3000000 |
| Viewport % | `fbp_felt_viewport_percentage` | FLOAT | 0.0025 | 0 → 1 |
| Fuzz Length | `fbp_felt_fuzz_length` | FLOAT | 0.04 | 0 → 10 |
| Subdivisions | `fbp_felt_subdivisions` | INT | 3 | 2 → 64 |
| Fuzz Radius | `fbp_felt_fuzz_radius` | FLOAT | 0.0005 | 1e-05 → 1 |
| Curl Amount | `fbp_felt_curl_amount` | FLOAT | 1 | 0 → 12 |
| Seed | `fbp_felt_seed` | INT | 0 | 0 → 2147483647 |
| Alpha Threshold | `fbp_felt_alpha_threshold` | FLOAT | 0.05 | 0 → 1 |
| Alpha Resolution | `fbp_felt_alpha_resolution` | INT | 2 | 2 → 6 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### Text Matrix — `OUTLINER_OB_FONT`

- ID: `TEXT_MATRIX`
- Backend: `GEOMETRY`
- Performance: `VERY_HEAVY`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Viewport Columns | `fbp_text_matrix_viewport_columns` | INT | 48 | 2 → 256 |
| Viewport Rows | `fbp_text_matrix_viewport_rows` | INT | 0 | 0 = Auto; 2 → 512 |
| Character Count | `fbp_text_matrix_character_count` | INT | 16 | 2 → 16 |
| Character Aspect | `fbp_text_matrix_character_aspect` | FLOAT | 0.6 | 0.1 → 2 |
| Glyph Scale | `fbp_text_matrix_glyph_scale` | FLOAT | 0.88 | 0.05 → 2 |
| Contrast | `fbp_text_matrix_contrast` | FLOAT | 1.3 | 0 → 8 |
| Invert | `fbp_text_matrix_invert` | BOOLEAN | Off |  |
| Variation | `fbp_text_matrix_variation` | FLOAT | 0 | 0 → 1 |
| Seed | `fbp_text_matrix_seed` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Alpha Threshold | `fbp_text_matrix_alpha_threshold` | FLOAT | 0 | 0 → 1 |
| Transparent Background | `fbp_text_matrix_transparent_background` | BOOLEAN | On |  |
| Realize Text | `fbp_text_matrix_realize` | BOOLEAN | Off |  |
| Character Set | `fbp_text_matrix_charset` | ENUM | CLASSIC | `CLASSIC`, `ALPHABETIC`, `ALPHANUMERIC`, `ARROW`, `CODE_PAGE_437`, `EXTENDED_HIGH`, `GRAY_SCALE`, `MINIMALIST`, `MATH_SYMBOLS`, `NORMAL`, `NORMAL_2`, `NUMERICAL`, `MAX`, `BLACK_WHITE`, `BINARY`, `SYMBOLS`, `CUSTOM` |
| Characters | `fbp_text_matrix_custom_charset` | STRING | None |  |
| Font | `fbp_text_matrix_font` | POINTER | None |  |
| Use Source Color | `fbp_text_matrix_use_source_color` | BOOLEAN | On |  |
| Text Color | `fbp_text_matrix_text_color` | FLOAT | [0.1, 1, 0.2, 1] | 0 → 1 |
| Background Color | `fbp_text_matrix_background_color` | FLOAT | [0, 0, 0, 1] | 0 → 1 |
| Render Columns | `fbp_text_matrix_render_columns` | INT | 96 | 2 → 512 |
| Render Rows | `fbp_text_matrix_render_rows` | INT | 0 | 0 = Auto; 2 → 512 |
| Quality | `fbp_text_matrix_quality` | ENUM | PREVIEW | `DRAFT`, `PREVIEW`, `FINAL`, `CUSTOM` |
| Limit During Playback | `fbp_text_matrix_auto_playback_limit` | BOOLEAN | On |  |
| Playback Columns | `fbp_text_matrix_playback_columns` | INT | 24 | 2 → 128 |
| Playback Rows | `fbp_text_matrix_playback_rows` | INT | 0 | 0 = Auto; 2 → 128 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |


> Built-in character sets are ordered from light to dense using the same 32-level atlas as Textellation. Source alpha is composited over white for density selection. With the default Alpha Threshold of `0`, only fully transparent cells are removed. Text Matrix samples the image from normalized point positions; `Rows = 0` derives an aspect-correct row count automatically.

#### Built-in presets

_No built-in presets._

## Image Effects — Creative

### Turbulence — `FORCE_TURBULENCE`

- ID: `UV_DISTORTION`
- Backend: `SHADER` / `UV`
- Performance: `MEDIUM`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Noise Scale | `fbp_uv_distortion_scale` | FLOAT | 10 | 0.001 → 3.40282e+38 |
| Distortion Amount | `fbp_uv_distortion_amount` | FLOAT | 0.05 | -3.40282e+38 → 3.40282e+38 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### Pixelate — `ALIASED`

- ID: `PIXELATE`
- Backend: `SHADER` / `UV`
- Performance: `LIGHT`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Resolution | `fbp_pixelate_resolution` | FLOAT | 64 | 1 → 3.40282e+38 |
| Square Pixels | `fbp_pixelate_square_pixels` | BOOLEAN | On |  |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### 2D Gradient Light — `LIGHT`

- ID: `GRADIENT_LIGHT`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Light Angle | `fbp_gradient_light_angle` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Shadow Position | `fbp_gradient_shadow_position` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Softness | `fbp_gradient_softness` | FLOAT | 0.5 | 0 → 1 |
| Shadow Color | `fbp_gradient_shadow_color` | FLOAT | [0, 0, 0.05, 1] | 0 → 1 |

#### Built-in presets

_No built-in presets._

### Gobo Shadows — `LIGHT_SPOT`

- ID: `GOBO_SHADOWS`
- Backend: `SHADER` / `COLOR`
- Performance: `MEDIUM`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Pattern Scale | `fbp_gobo_pattern_scale` | FLOAT | 10 | 0.001 → 3.40282e+38 |
| Rotation Angle | `fbp_gobo_rotation` | FLOAT | 0.5 | -3.40282e+38 → 3.40282e+38 |
| Sharpness | `fbp_gobo_sharpness` | FLOAT | 0.8 | 0 → 1 |

#### Built-in presets

_No built-in presets._

### Posterize — `MOD_TINT`

- ID: `POSTERIZE`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Color Steps | `fbp_posterize_steps` | FLOAT | 4 | 2 → 3.40282e+38 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### Halftone — `MESH_CIRCLE`

- ID: `HALFTONE`
- Backend: `SHADER` / `COLOR`
- Performance: `MEDIUM`
- Preview modes: `Final`, `Luminance`, `Mask`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Cell Scale | `fbp_halftone_scale` | FLOAT | 80 | 1 → 2000 |
| Dot Size | `fbp_halftone_dot_size` | FLOAT | 0.9 | 0 → 1.5 |
| Rotation | `fbp_halftone_rotation` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Contrast | `fbp_halftone_contrast` | FLOAT | 1.4 | 0 → 8 |
| Invert | `fbp_halftone_invert` | BOOLEAN | Off |  |
| Shape | `fbp_halftone_shape` | ENUM | CIRCLE | `CIRCLE`, `SQUARE`, `DIAMOND`, `LINE` |
| Use Source Color | `fbp_halftone_use_source_color` | BOOLEAN | On |  |
| Foreground | `fbp_halftone_foreground` | FLOAT | [0, 0, 0, 1] | 0 → 1 |
| Background | `fbp_halftone_background` | FLOAT | [1, 1, 1, 1] | 0 → 1 |
| Transparent Background | `fbp_halftone_transparent_background` | BOOLEAN | Off |  |

#### Built-in presets

**Newspaper**

- `fbp_halftone_scale` = `95`
- `fbp_halftone_dot_size` = `1`
- `fbp_halftone_contrast` = `1.6`
- `fbp_halftone_shape` = `CIRCLE`
- `fbp_halftone_use_source_color` = `Off`

**Comic**

- `fbp_halftone_scale` = `55`
- `fbp_halftone_dot_size` = `1.1`
- `fbp_halftone_contrast` = `2`
- `fbp_halftone_rotation` = `0.35`
- `fbp_halftone_shape` = `CIRCLE`

**Line Print**

- `fbp_halftone_scale` = `80`
- `fbp_halftone_dot_size` = `0.85`
- `fbp_halftone_shape` = `LINE`
- `fbp_halftone_rotation` = `0.25`


### Dot Matrix — `SNAP_GRID`

- ID: `DOT_MATRIX`
- Backend: `SHADER` / `COLOR`
- Performance: `MEDIUM`
- Preview modes: `Final`, `Luminance`, `Mask`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Cell Scale | `fbp_dot_matrix_scale` | FLOAT | 64 | 1 → 2000 |
| Dot Size | `fbp_dot_matrix_dot_size` | FLOAT | 0.85 | 0 → 1.5 |
| Spacing | `fbp_dot_matrix_spacing` | FLOAT | 0.1 | 0 → 0.95 |
| Contrast | `fbp_dot_matrix_contrast` | FLOAT | 1 | 0 → 8 |
| Brightness Response | `fbp_dot_matrix_response` | FLOAT | 1 | 0.1 → 8 |
| Invert | `fbp_dot_matrix_invert` | BOOLEAN | Off |  |
| Random Size | `fbp_dot_matrix_random_size` | FLOAT | 0 | 0 → 1 |
| Random Brightness | `fbp_dot_matrix_random_brightness` | FLOAT | 0 | 0 → 1 |
| Seed | `fbp_dot_matrix_seed` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Glow | `fbp_dot_matrix_glow` | FLOAT | 0.04 | 0 → 0.5 |
| Use Source Color | `fbp_dot_matrix_use_source_color` | BOOLEAN | On |  |
| Foreground | `fbp_dot_matrix_foreground` | FLOAT | [1, 0.65, 0.15, 1] | 0 → 1 |
| Background | `fbp_dot_matrix_background` | FLOAT | [0, 0, 0, 1] | 0 → 1 |
| Transparent Background | `fbp_dot_matrix_transparent_background` | BOOLEAN | On |  |
| Shape | `fbp_dot_matrix_shape` | ENUM | CIRCLE | `CIRCLE`, `SQUARE`, `DIAMOND`, `LINE` |
| Minimum Size | `fbp_dot_matrix_min_size` | FLOAT | 0 | 0 → 1.5 |
| Maximum Size | `fbp_dot_matrix_max_size` | FLOAT | 1 | 0 → 1.5 |
| Dead Pixels | `fbp_dot_matrix_dead_pixels` | FLOAT | 0 | 0 → 1 |
| Flicker | `fbp_dot_matrix_flicker` | FLOAT | 0 | 0 → 1 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

**LED Wall**

- `fbp_dot_matrix_scale` = `64`
- `fbp_dot_matrix_dot_size` = `0.9`
- `fbp_dot_matrix_min_size` = `0.08`
- `fbp_dot_matrix_max_size` = `1`
- `fbp_dot_matrix_response` = `0.82`
- `fbp_dot_matrix_glow` = `0.04`
- `fbp_dot_matrix_shape` = `CIRCLE`

**Printed Dots**

- `fbp_dot_matrix_scale` = `90`
- `fbp_dot_matrix_dot_size` = `0.8`
- `fbp_dot_matrix_response` = `1.25`
- `fbp_dot_matrix_glow` = `0.005`
- `fbp_dot_matrix_use_source_color` = `Off`
- `fbp_dot_matrix_shape` = `CIRCLE`

**Dead Display**

- `fbp_dot_matrix_scale` = `52`
- `fbp_dot_matrix_dead_pixels` = `0.08`
- `fbp_dot_matrix_flicker` = `0.12`
- `fbp_dot_matrix_glow` = `0.06`


### Textellation — `FONT_DATA`

- ID: `ASCII_MATRIX`
- Backend: `SHADER` / `COLOR`
- Performance: `HEAVY`
- Preview modes: `Final`, `Luminance`, `Glyph Index`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Cell Scale | `fbp_ascii_scale` | FLOAT | 48 | 1 → 1000 |
| Contrast | `fbp_ascii_contrast` | FLOAT | 1.3 | 0 → 8 |
| Invert | `fbp_ascii_invert` | BOOLEAN | Off |  |
| Use Source Color | `fbp_ascii_colorize` | BOOLEAN | On |  |
| Foreground | `fbp_ascii_foreground` | FLOAT | [0.1, 1, 0.2, 1] | 0 → 1 |
| Background | `fbp_ascii_background` | FLOAT | [0, 0, 0, 1] | 0 → 1 |
| Transparent Background | `fbp_ascii_transparent_background` | BOOLEAN | On |  |
| Variation | `fbp_ascii_variation` | FLOAT | 0 | 0 → 1 |
| Seed | `fbp_ascii_random_seed` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Edge Boost | `fbp_ascii_edge_boost` | FLOAT | 0 | 0 → 2 |
| Dither | `fbp_ascii_dither` | FLOAT | 0 | 0 → 1 |
| Character Set | `fbp_ascii_charset` | ENUM | CLASSIC | `CLASSIC`, `ALPHABETIC`, `ALPHANUMERIC`, `ARROW`, `CODE_PAGE_437`, `EXTENDED_HIGH`, `GRAY_SCALE`, `MINIMALIST`, `MATH_SYMBOLS`, `NORMAL`, `NORMAL_2`, `NUMERICAL`, `MAX`, `BLACK_WHITE`, `BINARY`, `SYMBOLS` |
| Character Count | `fbp_ascii_character_count` | INT | 16 | 2 → 32 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

> Partial source alpha makes a cell visually lighter but does not reduce output opacity. Only fully transparent source cells disappear. The sampled source RGB is used by default for glyph color.

#### Built-in presets

**Green Terminal**

- `fbp_ascii_charset` = `CLASSIC`
- `fbp_ascii_colorize` = `Off`
- `fbp_ascii_foreground` = `[0.08, 1, 0.22, 1]`
- `fbp_ascii_background` = `[0, 0.015, 0, 1]`
- `fbp_ascii_transparent_background` = `Off`

**Binary**

- `fbp_ascii_charset` = `BINARY`
- `fbp_ascii_character_count` = `2`
- `fbp_ascii_colorize` = `Off`
- `fbp_ascii_foreground` = `[0.75, 1, 0.75, 1]`

**Typewriter**

- `fbp_ascii_charset` = `ALPHANUMERIC`
- `fbp_ascii_scale` = `56`
- `fbp_ascii_colorize` = `Off`
- `fbp_ascii_foreground` = `[0.08, 0.06, 0.04, 1]`
- `fbp_ascii_background` = `[0.92, 0.88, 0.78, 1]`
- `fbp_ascii_transparent_background` = `Off`


## Image Effects — Film & Display

### Film Grain — `RENDER_STILL`

- ID: `GRAIN`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Intensity | `fbp_grain_strength` | FLOAT | 0.2 | 0 → 1 |
| Grain Scale | `fbp_grain_scale` | FLOAT | 180 | 0.01 → 3.40282e+38 |
| Animate (W) | `fbp_grain_seed` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### Paper Fibers — `TEXTURE`

- ID: `PAPER_FIBERS`
- Backend: `SHADER` / `COLOR`
- Performance: `MEDIUM`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Fiber Scale | `fbp_paper_fiber_scale` | FLOAT | 140 | 0.01 → 3.40282e+38 |
| Intensity | `fbp_paper_fiber_intensity` | FLOAT | 0.4 | 0 → 1 |
| Animate (W) | `fbp_paper_fiber_phase` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

_No built-in presets._

### CRT Scanlines — `NODE_TEXTURE`

- ID: `CRT_SCANLINES`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Line Count | `fbp_crt_line_count` | FLOAT | 200 | 1 → 3.40282e+38 |
| Opacity | `fbp_crt_opacity` | FLOAT | 0.15 | 0 → 1 |

#### Built-in presets

**VHS**

- `fbp_crt_line_count` = `420`
- `fbp_crt_opacity` = `0.22`

**Soft CRT**

- `fbp_crt_line_count` = `260`
- `fbp_crt_opacity` = `0.1`


### Vignette — `MESH_CIRCLE`

- ID: `VIGNETTE`
- Backend: `SHADER` / `COLOR`
- Performance: `LIGHT`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Radius | `fbp_vignette_radius` | FLOAT | 0.5 | 0 → 3.40282e+38 |
| Smoothness | `fbp_vignette_smoothness` | FLOAT | 0.2 | 0 → 1 |
| Strength | `fbp_vignette_strength` | FLOAT | 0.8 | 0 → 1 |

#### Built-in presets

_No built-in presets._

### Digital Noise — `RNDCURVE`

- ID: `DIGITAL_NOISE`
- Backend: `SHADER` / `COLOR`
- Performance: `MEDIUM`
- Input Source: `Previous Effects` / `Original Material` / `Final Material`

| Setting | Property ID | Type | Default | Range / Options |
|---|---|---|---:|---|
| Luminance Noise | `fbp_digital_noise_luma` | FLOAT | 0.12 | 0 → 1 |
| Chroma Noise | `fbp_digital_noise_chroma` | FLOAT | 0.08 | 0 → 1 |
| Noise Scale | `fbp_digital_noise_scale` | FLOAT | 500 | 1 → 10000 |
| Shadow Bias | `fbp_digital_noise_shadow_bias` | FLOAT | 0.65 | 0 → 2 |
| Animate (W) | `fbp_digital_noise_seed` | FLOAT | 0 | -3.40282e+38 → 3.40282e+38 |
| Evolve | `procedural.evolve` | Boolean | Off |  |
| Stepped | `procedural.step` | Integer | 4 | 1 → 100000 |
| Seed | `procedural.seed` | Integer | 0 | -1000000 → 1000000 |
| Unique per Layer | `procedural.unique` | Boolean | Off |  |

#### Built-in presets

**High ISO**

- `fbp_digital_noise_luma` = `0.12`
- `fbp_digital_noise_chroma` = `0.045`
- `fbp_digital_noise_scale` = `650`
- `fbp_digital_noise_shadow_bias` = `0.75`

**Night Sensor**

- `fbp_digital_noise_luma` = `0.2`
- `fbp_digital_noise_chroma` = `0.08`
- `fbp_digital_noise_scale` = `900`
- `fbp_digital_noise_shadow_bias` = `1`

**Cheap Camera**

- `fbp_digital_noise_luma` = `0.1`
- `fbp_digital_noise_chroma` = `0.13`
- `fbp_digital_noise_scale` = `320`
- `fbp_digital_noise_shadow_bias` = `0.55`

