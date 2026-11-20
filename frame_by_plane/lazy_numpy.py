"""NumPy loaded on first use instead of at add-on import.

Importing NumPy costs about 60 ms. Only alpha outlines and gesture selection
need it, and they run long after Blender has started, so the modules that use
it at module level bind ``np`` to this proxy instead of importing NumPy.
"""

import importlib


class _LazyNumpy:
    __slots__ = ()

    def __getattr__(self, name):
        module = importlib.import_module("numpy")
        return getattr(module, name)

    def __repr__(self):
        return "<lazy numpy>"


np = _LazyNumpy()
