"""Safeguards against efficiency and duplication regressing (see docs/EFFICIENCY_REVIEW.md).

* Startup guard: loading the URLconf must not import heavy optional libraries (openpyxl), so a worker stays small.
* Duplication guard: a few shared helpers have exactly one home; re-implementing them elsewhere fails here. Where
  copies already exist the test is a ratchet: the count may go down, never up.
* Static weight guard: the JS and CSS a page loads (its own files plus those of the templates it extends or includes)
  stay under a budget.

Pure file scans plus one subprocess; no database.
"""
import ast
import os
import re
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

BASE = str(settings.BASE_DIR)
APPS = ("accounts", "backups", "config", "diary", "fees", "mailer")
SKIP_PARTS = {"tests", "migrations", "__pycache__", "node_modules", "staticfiles"}
HEAVY_LIBS = ("openpyxl", "pandas", "numpy", "PIL", "lxml")


def source_files():
    """(path relative to the project, text) of every non-test, non-migration Python file in the apps."""
    found = []
    for app in APPS:
        for folder, dirs, files in os.walk(os.path.join(BASE, app)):
            dirs[:] = [d for d in dirs if d not in SKIP_PARTS]
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as handle:
                        found.append((os.path.relpath(path, BASE).replace(os.sep, "/"), handle.read()))
    return found


class StartupGuardTests(SimpleTestCase):
    def test_loading_the_urlconf_does_not_import_heavy_libraries(self):
        code = (
            "import os, sys, django\n"
            "django.setup()\n"
            "from django.urls import get_resolver\n"
            "get_resolver().url_patterns\n"
            f"print(','.join(m for m in {HEAVY_LIBS!r} if m in sys.modules))\n"
        )
        env = dict(os.environ, DJANGO_SETTINGS_MODULE=os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings"),
                   DJANGO_TESTING="1")
        result = subprocess.run([sys.executable, "-c", code], cwd=BASE, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        loaded = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        self.assertEqual(loaded, "", f"importing the URLconf loaded heavy libraries: {loaded}")

    def test_no_module_imports_a_heavy_library_at_the_top_level(self):
        offenders = []
        for path, text in source_files():
            for node in ast.parse(text).body:  # module level only: imports inside functions are the rule
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                if any(n.split(".")[0] in HEAVY_LIBS for n in names):
                    offenders.append(path)
        self.assertEqual(offenders, [], "import heavy libraries inside the function that needs them")


class DuplicationGuardTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sources = source_files()

    def defined_in(self, pattern):
        regex = re.compile(pattern, re.M)
        return sorted(path for path, text in self.sources if regex.search(text))

    def test_indian_digit_grouping_and_currency_format_live_only_in_money(self):
        self.assertEqual(self.defined_in(r"^\s*def (_group_indian|format_currency)\b"), ["fees/services/money.py"])

    def test_financial_year_derivation_has_one_home(self):
        # derive_financial_year and current_financial_year live in financial_year.py and nowhere else.
        self.assertEqual(self.defined_in(r"^\s*def (derive_financial_year|current_financial_year)\b"),
                         ["fees/services/financial_year.py"])

    def test_financial_year_arithmetic_copies_do_not_increase(self):
        # Ratchet. These statistics modules used to repeat "year if month >= 4 else year - 1" (now they call derive_financial_year).
        # The ratchet is at zero.
        expression = re.compile(r"year\s+if\s+month\s*>=\s*4\s+else\s+year\s*-\s*1")
        copies = sorted(path for path, text in self.sources
                        if expression.search(text) and path != "fees/services/financial_year.py")
        self.assertLessEqual(len(copies), 0, f"new copy of the financial year rule: {copies}")
        helper = re.compile(r"^\s*def _payment_fy\b", re.M)
        helpers = [path for path, text in self.sources if helper.search(text)]
        self.assertLessEqual(len(helpers), 0, f"new _payment_fy copy: {helpers}")

    def test_the_heavy_operation_lock_is_taken_only_by_the_heavy_module(self):
        self.assertEqual(self.defined_in(r"advisory_lock\s*\("), ["fees/services/heavy.py"])

    def test_role_decorators_are_defined_only_in_the_two_permission_modules(self):
        # accounts/permissions.py is the home; diary/views.py has one program-specific wrapper (profile_required).
        allowed = {"accounts/permissions.py", "diary/views.py"}
        found = set(self.defined_in(r"^def \w*(?:editor|reader|admin)_required\b"))
        self.assertLessEqual(found, allowed, f"define role decorators in accounts/permissions.py: {sorted(found - allowed)}")

    def test_email_is_built_only_through_the_sender_helper(self):
        # Every email must get its From / Reply-To from mailer.sender (Gmail DKIM rule).
        offenders = [path for path, text in self.sources
                     if re.search(r"\b(EmailMessage|EmailMultiAlternatives|send_mail)\s*\(", text)
                     and path not in ("mailer/sender.py", "accounts/forms.py")]
        self.assertEqual(offenders, [], "build mail with mailer.sender.build_message")


class StaticWeightGuardTests(SimpleTestCase):
    """What a page downloads for its own scripts and styles (before compression), including shared base templates."""

    JS_BUDGET = 110 * 1024
    CSS_BUDGET = 140 * 1024
    ASSET = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]""")
    LINK = re.compile(r"""\{%\s*(?:extends|include)\s+['"]([^'"]+)['"]""")

    def templates_dir(self):
        return os.path.join(BASE, "templates")

    def assets_of(self, name, seen):
        path = os.path.join(self.templates_dir(), name)
        if name in seen or not os.path.exists(path):
            return set()
        seen.add(name)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        found = set(self.ASSET.findall(text))
        for linked in self.LINK.findall(text):
            found |= self.assets_of(linked, seen)
        return found

    def size(self, asset):
        path = os.path.join(BASE, "static", asset)
        self.assertTrue(os.path.exists(path), f"{asset} is named in a template but is not in static/")
        return os.path.getsize(path)

    def test_every_page_stays_within_the_script_and_style_budget(self):
        root = self.templates_dir()
        checked = 0
        for folder, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(".html"):
                    continue
                template = os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
                assets = self.assets_of(template, set())
                js = sum(self.size(a) for a in assets if a.endswith(".js"))
                css = sum(self.size(a) for a in assets if a.endswith(".css"))
                self.assertLessEqual(js, self.JS_BUDGET, f"{template}: {js} bytes of JavaScript (budget {self.JS_BUDGET})")
                self.assertLessEqual(css, self.CSS_BUDGET, f"{template}: {css} bytes of CSS (budget {self.CSS_BUDGET})")
                checked += 1
        self.assertGreater(checked, 20)
