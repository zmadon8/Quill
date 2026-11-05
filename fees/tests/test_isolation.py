"""R-SC-3: the fees and diary packages must not import each other, and fees keeps no mutable module state."""
import importlib
import pkgutil

from django.test import SimpleTestCase


def _package_modules(package_name):
    """Every importable submodule name under ``package_name`` (the package itself included)."""
    package = importlib.import_module(package_name)
    names = [package_name]
    for info in pkgutil.walk_packages(package.__path__, prefix=package_name + "."):
        names.append(info.name)
    return names


def _source_of(module_name):
    module = importlib.import_module(module_name)
    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None)
    if loader is None or not hasattr(loader, "get_source"):
        return ""
    try:
        return loader.get_source(module_name) or ""
    except (OSError, ImportError):
        return ""


class ImportIsolationTests(SimpleTestCase):
    def test_no_fees_module_imports_diary(self):
        offenders = []
        for name in _package_modules("fees"):
            if ".migrations" in name or name.endswith(".migrations"):
                continue
            source = _source_of(name)
            if "import diary" in source or "from diary" in source:
                offenders.append(name)
        self.assertEqual(offenders, [], f"fees modules importing diary: {offenders}")

    def test_no_diary_module_imports_fees(self):
        offenders = []
        for name in _package_modules("diary"):
            if ".migrations" in name or name.endswith(".migrations"):
                continue
            source = _source_of(name)
            if "import fees" in source or "from fees" in source:
                offenders.append(name)
        self.assertEqual(offenders, [], f"diary modules importing fees: {offenders}")

    def test_registering_fees_did_not_pull_diary_into_accounts_programs(self):
        # The program registry stays free of a diary or fees import at module level (it uses lazy callables).
        source = _source_of("accounts.programs")
        self.assertNotIn("import diary", source)
        self.assertNotIn("from diary", source)
        self.assertNotIn("import fees", source)
        self.assertNotIn("from fees", source)
