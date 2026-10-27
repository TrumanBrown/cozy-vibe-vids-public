r"""Tools safety net (TASKS.md T1): free, offline (no Azure, no GPU, no network), about 15 s.

  .venv\Scripts\python -m unittest discover -s tests -v

1. Every tool in tools/ imports in its own process, the way it runs.
2. Every cross-tool reference resolves: `from <tool> import name` anywhere in a tool (most sit inside functions, so
   importing the tool doesn't run them) and `M.name` where M is a tool imported as `import <tool> as M`. Moving a
   helper out of a big script can't leave a caller behind.
"""
import ast
import importlib
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
# the tools, and the shared modules in tools/cozy/ and its packages by their import names (cozy.models, cozy.publish.words, ...)
NAMES = sorted([p.stem for p in TOOLS.glob("*.py")] + [".".join(p.relative_to(TOOLS).with_suffix("").parts)
                                                       for p in (TOOLS / "cozy").rglob("*.py") if p.stem != "__init__"])
FILES = sorted(TOOLS.glob("*.py")) + sorted((TOOLS / "cozy").rglob("*.py"))
# Scripts that do their work at import (no main guard): compiled, not imported. TASKS.md T5 gives them one.
SCRIPT_ONLY = set()


def import_alone(name):
    code = f"import sys; sys.path.insert(0, {str(TOOLS)!r}); import {name}"
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=600)
    return name, r.returncode, (r.stderr or r.stdout).strip()[-1500:]


def tool_refs(path):
    """(line, modules, name) for each reference from this file into another tool module. An alias that is also
    assigned as a plain variable somewhere in the file is left out, so a local `A = ...` is never read as a tool."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), str(path))
    tools = set(NAMES)
    refs, aliases, rebound = [], {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in tools:
            refs += [(node.lineno, (node.module,), a.name) for a in node.names if a.name != "*"]
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name in tools:
                    aliases.setdefault(a.asname or a.name, set()).add(a.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            rebound.add(node.id)
        elif isinstance(node, ast.arg):
            rebound.add(node.arg)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases
                and node.value.id not in rebound):
            refs.append((node.lineno, tuple(sorted(aliases[node.value.id])), node.attr))
    return refs


class Tools(unittest.TestCase):
    def test_tools_import(self):
        with ThreadPoolExecutor(8) as ex:
            results = list(ex.map(import_alone, [n for n in NAMES if n not in SCRIPT_ONLY]))
        self.assertGreater(len(results), 40)
        for name, rc, err in results:
            with self.subTest(tool=name):
                self.assertEqual(rc, 0, err)
        for name in sorted(SCRIPT_ONLY):
            with self.subTest(tool=name):
                p = TOOLS / f"{name}.py"
                compile(p.read_text(encoding="utf-8-sig"), str(p), "exec")

    def test_cross_tool_references(self):
        sys.path.insert(0, str(TOOLS))
        loaded, checked = {}, 0
        for p in FILES:
            for line, mods, attr in tool_refs(p):
                if any(m in SCRIPT_ONLY for m in mods):
                    continue
                with self.subTest(ref=f"{p.relative_to(TOOLS).as_posix()}:{line} {'|'.join(mods)}.{attr}"):
                    for m in mods:
                        if m not in loaded:
                            loaded[m] = importlib.import_module(m)
                    self.assertTrue(any(hasattr(loaded[m], attr) for m in mods),
                                    f"tools/{p.relative_to(TOOLS).as_posix()} line {line} uses {attr} from {'/'.join(mods)}, which has no such name")
                    checked += 1
        self.assertGreater(checked, 100, "the reference scan found almost nothing: the parser is broken")


if __name__ == "__main__":
    unittest.main()
