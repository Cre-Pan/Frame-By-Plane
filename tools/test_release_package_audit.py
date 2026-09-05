"""Negative regressions: never publish stale, dirty or incomplete ZIPs."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from audit_release_packages import ROOT, audit_package


class PackageAuditTests(unittest.TestCase):
    source = ROOT / "frame_by_plane"
    package = ROOT / "dist/frame_by_plane-7.2.0-windows_x64.zip"

    def altered(self, *, extra=None, omitted=None, changed=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "package.zip"
        with zipfile.ZipFile(self.package) as original, zipfile.ZipFile(path, "w") as output:
            for name in original.namelist():
                if name != omitted:
                    output.writestr(name, b"# stale source\n" if name == changed else original.read(name))
            if extra:
                output.writestr(extra, b"not runtime data")
        return path

    def test_current(self):
        self.assertTrue(audit_package(self.package, self.source, "windows_x64")["source_matches"])

    def test_dirty(self):
        with self.assertRaisesRegex(ValueError, "Unexpected entries"):
            audit_package(self.altered(extra="work/private.log"), self.source, "windows_x64")

    def test_missing_license(self):
        with self.assertRaisesRegex(ValueError, "missing entries"):
            audit_package(self.altered(omitted="LICENSE.txt"), self.source, "windows_x64")

    def test_stale_code(self):
        with self.assertRaisesRegex(ValueError, "Source mismatch"):
            audit_package(self.altered(changed="feedback.py"), self.source, "windows_x64")

    def test_unsafe_path(self):
        with self.assertRaisesRegex(ValueError, "Unsafe archive path"):
            audit_package(self.altered(extra="../escape.py"), self.source, "windows_x64")

    def test_duplicate(self):
        with self.assertRaisesRegex(ValueError, "Duplicate archive entries"):
            audit_package(self.altered(extra="feedback.py"), self.source, "windows_x64")


if __name__ == "__main__":
    unittest.main()
