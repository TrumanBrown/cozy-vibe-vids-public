r"""One list of types (TASKS.md T14): src/library/types.json. Free, offline, a few seconds.

  .venv\Scripts\python -m unittest discover -s tests -p test_types.py -v

types.json lists the layer types of scene.json (autoscene.js LAYERS), the types the timeline gives its events and the
pet's motions, and the top-level keys a scene.json may have. No render reads it, so it can't change a frame; these
tests hold the rest to it:
  1. LAYERS and types.json's layers are the same types.
  2. Every event and pet-motion type in each scene's timeline is listed, and the list is what a timeline gives when
     its spec switches on every generator (tests/js_types.mjs).
  3. Every scenes/*/scene.json has only listed top-level keys and layer types.
  4. Every string a tool (tools/*.py, tools/cozy/**/*.py) compares an event's or a layer's "type" against is a listed
     layer or event type. The scan finds comparisons with x["type"] or x.get("type") and follows the other side to its
     strings: a literal, a module-level constant, a loop over one, or a parameter of a function through every call to
     it in the same file. NOT_TYPES holds the strings that are some other kind of "type", RUNTIME the comparisons with
     a value that is only known when the tool runs.
"""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_scenes import NODE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from cozy.paths import save_scene, scene_problems  # noqa: E402  (the check save_scene() runs before it writes)
TYPES = json.loads((ROOT / "src" / "library" / "types.json").read_text(encoding="utf-8"))
TOOLS = sorted([*(ROOT / "tools").glob("*.py"), *(ROOT / "tools" / "cozy").rglob("*.py")])
NOT_TYPES = {("tools/azure_ai.py", "image_url"): "a part of an Azure chat message, not a layer or an event"}
RUNTIME = {
    ("tools/critic.py", "tight_box", "kind"): "an event kind of the render's timeline (critic's EVENT_Q)",
    ("tools/event_sheets.py", "plan", "only"): "the event kinds asked for (--kinds, critic's EVENT_Q)",
    ("tools/cozy/paths.py", "scene_problems", "layers"): "the layer types of types.json itself (save_scene's check)",
}
COLLECTIONS = ("set", "frozenset", "tuple", "list", "sorted")


def is_type_access(n):
    """x["type"] or x.get("type"[, default])"""
    if isinstance(n, ast.Subscript):
        return isinstance(n.slice, ast.Constant) and n.slice.value == "type"
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and bool(n.args)
            and isinstance(n.args[0], ast.Constant) and n.args[0].value == "type")


def type_comparisons(source):
    """[(line, function, other side's name or None, its strings or None if they can't be known)] for every comparison
    (==, !=, in, not in) of x["type"] or x.get("type") in a tool's source."""
    tree = ast.parse(source)
    parent = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    consts = {n.targets[0].id: n.value for n in tree.body
              if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    funcs = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(n.name, []).append(n)
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Lambda):
            funcs.setdefault(n.targets[0].id, []).append(n.value)
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in funcs]
    values, unknown = {}, set()      # (function node, parameter) -> the strings its calls pass; parameters with an unknown call

    def positional(f):
        return [a.arg for a in (*f.args.posonlyargs, *f.args.args)]

    def scopes(node):
        while node in parent:
            node = parent[node]
            yield node

    def resolve(node, at, seen=()):
        if isinstance(node, ast.Constant):
            return [node.value] if isinstance(node.value, str) else []
        if isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.Dict)):
            out = []
            for e in (node.keys if isinstance(node, ast.Dict) else node.elts):
                r = None if e is None else resolve(e, at, seen)
                if r is None:
                    return None
                out += r
            return out
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in COLLECTIONS and len(node.args) == 1:
            return resolve(node.args[0], at, seen)
        if not isinstance(node, ast.Name):
            return None
        name = node.id
        for s in scopes(at):
            if isinstance(s, (ast.For, ast.AsyncFor)) or isinstance(s, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                for target, it in ([(s.target, s.iter)] if isinstance(s, (ast.For, ast.AsyncFor)) else [(g.target, g.iter) for g in s.generators]):
                    if isinstance(target, ast.Name) and target.id == name:
                        return resolve(it, s, seen)
                    if any(isinstance(x, ast.Name) and x.id == name for x in ast.walk(target)):
                        return None
            elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                if name in positional(s) or name in [a.arg for a in s.args.kwonlyargs]:
                    return None if (s, name) in unknown or not values.get((s, name)) else sorted(values[(s, name)])
        if name in consts and name not in seen:
            return resolve(consts[name], consts[name], (*seen, name))
        return None

    def bindings(c, f):
        """(parameter, argument or default) for one call of f."""
        ps, out = positional(f), []
        given = {k.arg: k.value for k in c.keywords if k.arg}
        for i, a in enumerate(c.args):
            if isinstance(a, ast.Starred):
                return None
            if i < len(ps):
                given[ps[i]] = a
        kw = [a.arg for a in f.args.kwonlyargs]
        defaults = dict(zip(ps[len(ps) - len(f.args.defaults):], f.args.defaults)) | {
            a: d for a, d in zip(kw, f.args.kw_defaults) if d is not None}
        for p in (*ps, *kw):
            if p in given or p in defaults:
                out.append((p, given.get(p, defaults.get(p))))
        return out

    for _ in range(20):              # what each parameter is called with, until nothing new turns up
        before = {k: set(v) for k, v in values.items()}, set(unknown)
        for c in calls:
            for f in funcs[c.func.id]:
                b = bindings(c, f)
                if b is None:
                    unknown.update((f, p) for p in (*positional(f), *[a.arg for a in f.args.kwonlyargs]))
                    continue
                for p, a in b:
                    r = resolve(a, c)
                    if r is None:
                        unknown.add((f, p))
                    else:
                        values.setdefault((f, p), set()).update(r)
        if ({k: set(v) for k, v in values.items()}, unknown) == before:
            break

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        sides = [node.left, *node.comparators]
        for op, a, b in zip(node.ops, sides, sides[1:]):
            if not isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn)):
                continue
            other = b if is_type_access(a) else a if is_type_access(b) else None
            if other is None:
                continue
            fn = next((s.name for s in scopes(node) if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))), "<module>")
            out.append((node.lineno, fn, other.id if isinstance(other, ast.Name) else None, resolve(other, node)))
    return out


@unittest.skipUnless(NODE, "node isn't on PATH")
class Types(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "types.json"
            r = subprocess.run([NODE, str(ROOT / "tests" / "js_types.mjs"), str(out)], cwd=ROOT, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(f"tests/js_types.mjs failed:\n{r.stderr[-2000:]}")
            cls.js = json.loads(out.read_text(encoding="utf-8"))

    def test_save_scene_refuses_what_the_renderer_cant_read(self):
        """TASKS.md T14: a misspelled layer type or an unknown key fails on save, and nothing is written."""
        for bad, why in (({"layers": [{"type": "rian"}]}, "'rian'"), ({"titel": "x"}, "'titel'")):
            with self.subTest(why=why):
                with self.assertRaises(ValueError) as cm:
                    save_scene("_t14_never_written", {"name": "x", **bad})
                self.assertIn(why, str(cm.exception))
        self.assertFalse((ROOT / "scenes" / "_t14_never_written").exists())
        self.assertEqual(scene_problems({"name": "x", "_any_note": 1, "layers": [{"type": "rain"}]}), [])

    def test_lists(self):
        for k in ("layers", "events", "scene_keys"):
            with self.subTest(list=k):
                self.assertEqual(TYPES[k], sorted(set(TYPES[k])), f"types.json {k}: keep it sorted, each once")

    def test_layers_are_autoscene_layers(self):
        self.assertEqual(sorted(self.js["layers"]), TYPES["layers"], "autoscene.js LAYERS and types.json layers differ")

    def test_timeline_types(self):
        self.assertGreater(len(self.js["scenes"]), 10)
        for scene, t in self.js["scenes"].items():
            with self.subTest(scene=scene):
                self.assertEqual([x for x in t["events"] + t["pet"] if x not in TYPES["events"]], [])
        self.assertEqual(self.js["can_emit"], TYPES["events"], "the types a timeline gives aren't types.json's events")

    def test_scene_json(self):
        files = sorted((ROOT / "scenes").glob("*/scene.json"))
        self.assertGreater(len(files), 5)
        for p in files:
            with self.subTest(scene=p.parent.name):
                self.assertEqual(scene_problems(json.loads(p.read_text(encoding="utf-8"))), [])

    def test_tools_compare_known_types(self):
        known = set(TYPES["layers"]) | set(TYPES["events"])
        bad, unknown, n = [], [], 0
        for f in TOOLS:
            rel = f.relative_to(ROOT).as_posix()
            for line, fn, name, strings in type_comparisons(f.read_text(encoding="utf-8-sig")):
                n += 1
                if strings is None:
                    if (rel, fn, name) not in RUNTIME:
                        unknown.append(f"{rel}:{line} in {fn}() against {name or 'an expression'}")
                    continue
                bad += [f"{rel}:{line} {s!r}" for s in strings if s not in known and (rel, s) not in NOT_TYPES]
        self.assertGreater(n, 40, "the scan found almost no type comparisons")
        self.assertEqual(bad, [], "a tool compares a type with a string that is no layer or event type (types.json)")
        self.assertEqual(unknown, [], "can't tell what these are compared with: make it a constant, or add it to RUNTIME with why")

    def test_checks_catch_mistakes(self):
        """The checks themselves: a misspelled type, a constant, a loop, a function's calls, and an unknown value."""
        src = (
            'KINDS = ("rain", "drips")\n'
            'def f(L, e, kind):\n'
            '    return L.get("type") == "rian" or e["type"] in KINDS or any(x["type"] == kind for x in e)\n'
            'f(1, 2, "lightning")\n'
            'def g(e, k):\n'
            '    return e["type"] == k\n'
            'for q in ("fish", "flurry"):\n'
            '    g(None, q)\n'
            'def h(e, z):\n'
            '    return e.get("type") != z\n')
        got = {(line, fn, name): strings for line, fn, name, strings in type_comparisons(src)}
        self.assertEqual(got, {(3, "f", None): ["rian"], (3, "f", "KINDS"): ["rain", "drips"], (3, "f", "kind"): ["lightning"],
                               (6, "g", "k"): ["fish", "flurry"], (10, "h", "z"): None})
        self.assertEqual(scene_problems({"name": "x", "laeyrs": [], "layers": [{"type": "rain"}, {"type": "rian"}]}),
                         ["top-level key 'laeyrs'", "layer 1 has type 'rian'"])


if __name__ == "__main__":
    unittest.main()
