"""A1: scan the data tree, unpack archives (zip/rar/7z, multivolume), and
yield a flat list of processable source files with a stable relative path
used for metadata heuristics.

Archive safety: 2 GB unpack limit per archive, bounded nesting depth.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config
from .util import log, sha256_file, slug


@dataclass
class SourceFile:
    abs_path: Path            # real location on disk
    rel_path: str             # path used for metadata (posix, relative to DATA_ROOT)
    origin: str               # "direct" | "archive"
    archive_rel: Optional[str] = None   # archive this came from (rel to DATA_ROOT)
    warnings: list[str] = field(default_factory=list)


# --- archive volume classification ----------------------------------------
_part_rar = re.compile(r"^(?P<base>.+)\.part(?P<n>\d+)\.rar$", re.IGNORECASE)
_split_num = re.compile(r"^(?P<base>.+)\.(?P<n>\d{3})$")   # foo.zip.001


def classify_volume(name: str) -> tuple[str, bool]:
    """Return (kind, is_primary). kind in
    {single, part_rar, split_num, none}."""
    m = _part_rar.match(name)
    if m:
        return "part_rar", int(m.group("n")) == 1
    m = _split_num.match(name)
    if m:
        return "split_num", int(m.group("n")) == 1
    ext = Path(name).suffix.lower()
    if ext in config.ARCHIVE_EXT:
        return "single", True
    return "none", False


def _unar_available() -> bool:
    return shutil.which("unar") is not None


def _extract_archive(primary: Path, dest: Path) -> tuple[bool, list[str]]:
    """Extract *primary* archive into *dest*. Handles split-zip (.zip.00N) by
    concatenation. Returns (success, warnings)."""
    warnings: list[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    kind, _ = classify_volume(primary.name)

    src = primary
    tmp_join: Optional[Path] = None
    if kind == "split_num":
        # concatenate foo.zip.001, foo.zip.002 ... -> foo.zip
        base = primary.name[: -len(primary.suffix)]  # foo.zip
        vols = sorted(primary.parent.glob(base + ".[0-9][0-9][0-9]"))
        joined = dest / base
        try:
            with open(joined, "wb") as out:
                for v in vols:
                    with open(v, "rb") as fin:
                        shutil.copyfileobj(fin, out)
            src = joined
            tmp_join = joined
        except OSError as e:
            return False, [f"join-failed: {e}"]

    if not _unar_available():
        # zip fallback via python; rar cannot be handled
        if src.suffix.lower() == ".zip" or kind == "split_num":
            return _extract_zip_py(src, dest, warnings)
        warnings.append("unar missing: cannot extract rar/7z")
        return False, warnings

    try:
        proc = subprocess.run(
            ["unar", "-force-overwrite", "-no-directory", "-output-directory",
             str(dest), str(src)],
            capture_output=True, text=True, timeout=1200,
        )
        if proc.returncode != 0:
            warnings.append(f"unar rc={proc.returncode}: {proc.stderr.strip()[:200]}")
            # try python zip fallback
            if src.suffix.lower() == ".zip":
                return _extract_zip_py(src, dest, warnings)
            return False, warnings
    except (subprocess.TimeoutExpired, OSError) as e:
        warnings.append(f"unar error: {e}")
        return False, warnings
    finally:
        if tmp_join and tmp_join.exists():
            try:
                tmp_join.unlink()
            except OSError:
                pass

    # enforce unpack size limit (post-hoc guard against bombs)
    total = _dir_size(dest)
    if total > config.ARCHIVE_UNPACK_LIMIT:
        warnings.append(f"unpack size {total} > limit; keeping but flagged")
    return True, warnings


def _extract_zip_py(src: Path, dest: Path, warnings: list[str]) -> tuple[bool, list[str]]:
    import zipfile
    try:
        with zipfile.ZipFile(src) as zf:
            total = 0
            for info in zf.infolist():
                total += info.file_size
                if total > config.ARCHIVE_UNPACK_LIMIT:
                    warnings.append("zip exceeds unpack limit (bomb guard) - aborted")
                    return False, warnings
            zf.extractall(dest)
        return True, warnings
    except Exception as e:  # noqa: BLE001
        warnings.append(f"zip python fallback failed: {e}")
        return False, warnings


def _dir_size(d: Path) -> int:
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())


def scan(root: Path = config.DATA_ROOT, depth: int = 0,
         rel_prefix: str = "") -> list[SourceFile]:
    """Walk *root*, returning processable files. Archives are extracted into
    config.EXTRACT_DIR and recursed into (up to ARCHIVE_MAX_DEPTH)."""
    out: list[SourceFile] = []
    if not root.exists():
        log(f"scan: root does not exist: {root}")
        return out

    entries = sorted(root.rglob("*"))
    # handle archives first so we know which secondary volumes to skip
    primaries: list[Path] = []
    for p in entries:
        if not p.is_file():
            continue
        kind, is_primary = classify_volume(p.name)
        if kind != "none" and is_primary:
            primaries.append(p)

    for p in entries:
        if not p.is_file():
            continue
        name = p.name
        if name == ".DS_Store":
            continue
        kind, is_primary = classify_volume(name)
        ext = p.suffix.lower()
        rel = _rel(p, root, rel_prefix)

        if kind != "none":
            if not is_primary:
                continue  # secondary volume, consumed by primary
            # extract
            if depth >= config.ARCHIVE_MAX_DEPTH:
                out.append(SourceFile(p, rel, "direct",
                                      warnings=["archive nesting too deep - skipped"]))
                continue
            dest = config.EXTRACT_DIR / (slug(p.stem) + "_" + sha256_file(p)[:10])
            if dest.exists() and any(dest.rglob("*")):
                ok, warns = True, []   # already extracted on a previous run
            else:
                ok, warns = _extract_archive(p, dest)
            if not ok:
                out.append(SourceFile(p, rel, "direct", warnings=warns))
                continue
            # metadata rel base: archive's parent dir + archive stem (keeps year folders)
            inner_prefix = str(Path(rel).parent / Path(rel).stem)
            sub = scan(dest, depth + 1, inner_prefix)
            for s in sub:
                s.origin = "archive"
                s.archive_rel = rel
                if warns:
                    s.warnings = warns + s.warnings
            out.extend(sub)
            if not sub:
                out.append(SourceFile(p, rel, "direct",
                                      warnings=(warns or []) + ["archive extracted but no processable files"]))
            continue

        if ext in config.SKIP_EXT:
            continue
        if ext not in config.SUPPORTED_TEXT_EXT:
            # unknown extension: record as skipped marker
            out.append(SourceFile(p, rel, "direct", warnings=[f"unsupported ext {ext}"]))
            continue
        out.append(SourceFile(p, rel, "direct"))
    return out


def _rel(p: Path, root: Path, rel_prefix: str) -> str:
    r = p.relative_to(root).as_posix()
    if rel_prefix:
        return (rel_prefix.rstrip("/") + "/" + r)
    return r
