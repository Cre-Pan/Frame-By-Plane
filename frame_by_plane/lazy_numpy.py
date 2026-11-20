"""NumPy loaded on first use instead of at add-on import.

Importing NumPy costs about 60 ms. Only alpha outlines and gesture selection
need it, and they run long after Blender has started, so the modules that use
it at module level bind ``np`` to this proxy instead of importing NumPy.
"""

import importlib


class _LazyNumpy:
    def __getattr__(self, name):
        # Only called for names not cached yet: keep each one on the instance
        # so later lookups are plain attribute reads, not an import call.
        value = getattr(importlib.import_module("numpy"), name)
        self.__dict__[name] = value
        return value

    def __repr__(self):
        return "<lazy numpy>"


np = _LazyNumpy()
