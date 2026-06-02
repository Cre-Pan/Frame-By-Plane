# Frame by Plane v2.3.10

Blender Extensions upload note:

- `schema_version` must stay `1.0.0`.
- Add-on `version` is `2.3.10`.
- Current tags: `3D View`, `Animation`.

Suggested Blender command-line build:

```bash
blender --command extension build --source-dir ./frame_by_plane --output-dir ./build
```

If Blender Extensions rejects the Animation tag, change:

```toml
tags = ["3D View", "Animation"]
```

to:

```toml
tags = ["3D View"]
```
