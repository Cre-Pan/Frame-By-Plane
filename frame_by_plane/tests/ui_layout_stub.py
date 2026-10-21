"""Record UILayout calls and check them against Blender's RNA signatures.

Background Blender cannot draw panels, so a wrong keyword or enum value in a
draw function only shows up as an empty popover in the real UI. This stub
replays a draw function and raises on any call Blender would reject.
"""

import bpy


_FUNCTIONS = bpy.types.UILayout.bl_rna.functions
_LAYOUT_PROPERTIES = {prop.identifier for prop in bpy.types.UILayout.bl_rna.properties}


class StubLayout:
    def __init__(self, calls=None):
        self.calls = [] if calls is None else calls

    def __setattr__(self, name, value):
        if name != "calls" and name not in _LAYOUT_PROPERTIES:
            raise AttributeError(f"UILayout has no property {name!r}")
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        function = _FUNCTIONS.get(name)
        if function is None:
            raise AttributeError(f"UILayout has no function {name!r}")
        parameters = {parameter.identifier: parameter for parameter in function.parameters}

        def call(*args, **kwargs):
            for key, value in kwargs.items():
                parameter = parameters.get(key)
                if parameter is None:
                    raise TypeError(f"UILayout.{name}() got an unexpected keyword {key!r}")
                if parameter.type == "ENUM" and isinstance(value, str) and value:
                    allowed = set(parameter.enum_items.keys())
                    if allowed and value not in allowed:
                        raise TypeError(f"UILayout.{name}({key}={value!r}) not in {sorted(allowed)[:8]}...")
            if name == "prop" and len(args) >= 2:
                owner, prop_name = args[0], args[1]
                if prop_name not in owner.bl_rna.properties:
                    raise TypeError(f"UILayout.prop(): {type(owner).__name__} has no {prop_name!r}")
            self.calls.append((name, args, kwargs))
            if name in {"panel"}:
                return StubLayout(self.calls), StubLayout(self.calls)
            if name in {"row", "column", "box", "split", "column_flow", "grid_flow"}:
                return StubLayout(self.calls)
            if name == "operator":
                return _StubOperatorProperties(args[0] if args else kwargs.get("operator", ""))
            return None

        return call


class _StubOperatorProperties:
    def __init__(self, idname):
        module, _dot, operator = str(idname).partition(".")
        try:
            rna = getattr(getattr(bpy.ops, module), operator).get_rna_type()
            properties = {prop.identifier for prop in rna.properties}
        except KeyError:
            # Background Blender skips some UI-only operators; nothing to check.
            properties = None
        object.__setattr__(self, "_properties", properties)
        object.__setattr__(self, "_idname", idname)

    def __setattr__(self, name, value):
        if self._properties is not None and name not in self._properties:
            raise AttributeError(f"{self._idname} has no property {name!r}")


class StubPanel:
    def __init__(self):
        self.layout = StubLayout()
