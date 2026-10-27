"""Which tool code a result depends on, following imports (TASKS.md T9).

A cache keyed on one file's bytes goes stale without anyone noticing once the code it runs is split across modules:
loop_master's stems were keyed on tools/audio.py alone, though audio.py imports audio_analyze and music. Here a tool
module's import closure is found from its source (imports inside functions included, since most of them are), so a
key or an mtime check covers everything the tool can run.

  code_files("audio")      [tools/audio.py, tools/audio_analyze.py, tools/music.py, ...] (sorted Paths)
  code_hash("audio")       sha1 of those files' paths and contents (line endings normalized), hex
"""
import ast
import functools
import hashlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]


def module_file(name):
    """tools/<name>.py for a tool; for "cozy..." the module's file in tools/cozy/ (a package's __init__.py); None for
    anything else."""
    parts = name.split(".")
    if parts[0] == "cozy":
        base = TOOLS.joinpath(*parts)
        for p in (base.with_suffix(".py"), base / "__init__.py"):
            if p.is_file():
                return p
        return None
    p = TOOLS / f"{name}.py"
    return p if len(parts) == 1 and p.is_file() else None


def _package(path):
    """The dotted package a file in tools/cozy/ belongs to ("cozy.audio" for tools/cozy/audio/dsp.py), else None."""
    rel = Path(path).relative_to(TOOLS).parent.parts
    return ".".join(rel) if rel and rel[0] == "cozy" else None


@functools.lru_cache(maxsize=None)
def _direct(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"), str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                     # relative, inside a tools/cozy package
                pkg = _package(path)
                if not pkg:
                    continue
                base = pkg.split(".")[: len(pkg.split(".")) - (node.level - 1)]
                mod = ".".join(base + ([node.module] if node.module else []))
            elif node.module:
                mod = node.module
            else:
                continue
            names.add(mod)
            names.update(f"{mod}.{a.name}" for a in node.names)   # `from cozy.audio import dsp` imports a module
    found = {module_file(n) for n in names}
    # importing cozy.a.b runs cozy/__init__.py and cozy/a/__init__.py first
    for n in names | ({_package(path)} - {None}):
        parts = n.split(".")
        if parts[0] == "cozy":
            found.update(module_file(".".join(parts[:k])) for k in range(1, len(parts)))
    return frozenset(p for p in found if p is not None and p != Path(path))


def code_files(*names):
    """The files of the named tool modules and every tool module they import, transitively."""
    todo = [module_file(n) for n in names]
    if None in todo:
        raise ValueError(f"not a tool module: {[n for n in names if module_file(n) is None]}")
    seen = set()
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        todo.extend(_direct(p) - seen)
    return sorted(seen)


def code_hash(*names):
    """sha1 (hex) of the code the named tool modules run: each file of their closure, by path and content."""
    h = hashlib.sha1()
    for p in code_files(*names):
        h.update(p.relative_to(TOOLS).as_posix().encode() + b"\n" + p.read_bytes().replace(b"\r\n", b"\n") + b"\n")
    return h.hexdigest()
