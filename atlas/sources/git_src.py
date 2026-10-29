"""Atlas's own git mirror of the erp repo.

The user's erp/ checkout is never written: Atlas clones a bare mirror into
.data/erp.git and only ever runs fetch / ls-tree / cat-file / diff / blame on
that.  Reading blobs straight from the object store also sidesteps the
CRLF-vs-LF question -- what comes back is exactly what was committed.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

GH_CRED = "!gh auth git-credential"


class GitError(RuntimeError):
    pass


@dataclass
class Change:
    status: str          # A, M, D, R
    path: str
    old_path: str | None = None


def decode(blob: bytes) -> str:
    # latin-1 round-trips all 256 byte values, so raw MultiValue mark bytes keep
    # their column positions (same choice as lintbasic.read_lines).
    return blob.decode("latin-1")


def split_lines(text: str) -> list[str]:
    return text.splitlines()


_MAP_RE = re.compile(r'"original":"(.*?)","sanitized":"(.*?)","reldir":"(.*?)"')


def parse_filename_map(text: str) -> dict[str, str]:
    """sanitized basename -> original Pick name.  The file is JSONL with raw
    backslashes, which json.loads rejects, so it is read with a regex."""
    out: dict[str, str] = {}
    for m in _MAP_RE.finditer(text):
        out[m.group(2)] = m.group(1)
    return out


class GitMirror:
    def __init__(self, mirror: Path, origin: str, local_fallback: Path | None = None,
                 branch: str = "main") -> None:
        self.mirror = mirror
        self.origin = origin
        self.local_fallback = local_fallback
        self.branch = branch

    def _git(self, *args: str, input: bytes | None = None, cred: bool = False) -> bytes:
        cmd = ["git"]
        if cred:
            cmd += ["-c", f"credential.helper={GH_CRED}"]
        cmd += ["--git-dir", str(self.mirror), *args]
        p = subprocess.run(cmd, input=input, capture_output=True)
        if p.returncode != 0:
            raise GitError(f"git {' '.join(args[:3])}: {p.stderr.decode(errors='replace').strip()}")
        return p.stdout

    def exists(self) -> bool:
        return (self.mirror / "HEAD").exists()

    def ensure(self) -> str:
        """Clone the mirror if missing.  Returns which source was used."""
        if self.exists():
            return "existing"
        self.mirror.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(["git", "-c", f"credential.helper={GH_CRED}", "clone", "--mirror",
                            self.origin, str(self.mirror)], capture_output=True)
        if p.returncode == 0:
            return "origin"
        if self.local_fallback and (self.local_fallback / ".git").exists():
            p2 = subprocess.run(["git", "clone", "--mirror", str(self.local_fallback), str(self.mirror)],
                                capture_output=True)
            if p2.returncode == 0:
                return "local-fallback (may be shallow: no history before its oldest commit)"
        raise GitError(f"could not clone mirror: {p.stderr.decode(errors='replace').strip()}")

    def fetch(self) -> str:
        self._git("fetch", "--prune", "origin", cred=True)
        return self.head()

    def head(self) -> str:
        return self._git("rev-parse", f"refs/heads/{self.branch}").decode().strip()

    def is_ancestor(self, old: str, new: str) -> bool:
        p = subprocess.run(["git", "--git-dir", str(self.mirror), "merge-base", "--is-ancestor", old, new])
        return p.returncode == 0

    def ls_tree(self, sha: str, paths: list[str]) -> dict[str, str]:
        """path -> blob sha for every file under `paths` at `sha`."""
        out = self._git("ls-tree", "-r", "-z", sha, "--", *paths)
        files: dict[str, str] = {}
        for entry in out.split(b"\0"):
            if not entry:
                continue
            meta, path = entry.split(b"\t", 1)
            _mode, kind, blob = meta.split()
            if kind == b"blob":
                files[path.decode("utf-8", "surrogateescape")] = blob.decode()
        return files

    def diff(self, old: str, new: str, paths: list[str]) -> list[Change]:
        out = self._git("diff", "--name-status", "-z", "-M", old, new, "--", *paths)
        parts = [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]
        changes: list[Change] = []
        i = 0
        while i < len(parts):
            st = parts[i]
            if st.startswith("R") or st.startswith("C"):
                changes.append(Change("R", parts[i + 2], parts[i + 1]))
                i += 3
            else:
                changes.append(Change(st[0], parts[i + 1]))
                i += 2
        return changes

    def read_blobs(self, blobs: list[str]) -> dict[str, bytes]:
        """Batch-read many blobs in one git process."""
        if not blobs:
            return {}
        uniq = list(dict.fromkeys(blobs))
        out = self._git("cat-file", "--batch", input=("\n".join(uniq) + "\n").encode())
        res: dict[str, bytes] = {}
        pos = 0
        for sha in uniq:
            nl = out.index(b"\n", pos)
            header = out[pos:nl].split()
            if len(header) < 3:
                raise GitError(f"cat-file: missing {sha}")
            size = int(header[2])
            res[sha] = out[nl + 1: nl + 1 + size]
            pos = nl + 1 + size + 1
        return res

    def read(self, sha: str, path: str) -> bytes:
        return self._git("show", f"{sha}:{path}")

    def recent_commits(self, ref: str, paths: list[str], limit: int = 10) -> list[dict[str, object]]:
        """Newest commits touching `paths`, with the basenames of the files each changed."""
        out = self._git("log", f"-{limit}", "--name-only", "--format=%x1e%H%x00%an%x00%ad%x00%s", "--date=short",
                        ref, "--", *paths).decode("utf-8", "replace")
        rows: list[dict[str, object]] = []
        for chunk in out.split("\x1e"):
            if not chunk.strip():
                continue
            head, *files = chunk.strip("\n").split("\n")
            h, author, date, summary = head.split("\0", 3)
            rows.append({"sha": h, "author": author, "date": date, "summary": summary,
                         "files": [f.rsplit("/", 1)[-1] for f in files if f.strip()]})
        return rows

    def file_history(self, sha: str, path: str, limit: int = 15) -> list[dict[str, str]]:
        out = self._git("log", f"-{limit}", "--format=%H%x00%an%x00%ad%x00%s", "--date=short",
                        sha, "--", path).decode("utf-8", "replace")
        rows = []
        for line in out.splitlines():
            h, author, date, summary = line.split("\0", 3)
            rows.append({"sha": h, "author": author, "date": date, "summary": summary})
        return rows

    def last_touching(self, sha: str, path: str, text: str) -> dict[str, str] | None:
        """Most recent commit (up to `sha`) that added or removed `text` as ACTIVE code
        in `path` -- for a live-only hunk, the commit that took it out of git.

        Anchored so a commented-out copy (`*    IF ...`) does not match: commenting a
        rule out leaves its string count unchanged, which `-S` would miss entirely."""
        ere = re.sub(r"([\\.\[\]*^$+?(){}|])", r"\\\1", text.strip())     # pickaxe -G is POSIX ERE
        pattern = rf"^[[:space:]]*([0-9A-Za-z.]*:[[:space:]]*)?{ere}"
        out = self._git("log", "-1", "-G", pattern, "--format=%H%x00%an%x00%ad%x00%s", "--date=short",
                        sha, "--", path).decode("utf-8", "replace").strip()
        if not out:
            return None
        h, author, date, summary = out.split("\0", 3)
        return {"sha": h, "author": author, "date": date, "summary": summary}

    def blame_lines(self, sha: str, path: str, start: int, end: int) -> list[dict[str, str]]:
        """Commit behind each line in [start, end] (1-based) at `sha`."""
        out = self._git("blame", "--porcelain", "-L", f"{start},{end}", sha, "--", path).decode(
            "utf-8", "replace")
        commits: dict[str, dict[str, str]] = {}
        result: list[dict[str, str]] = []
        cur: str | None = None
        for line in out.splitlines():
            m = re.match(r"^([0-9a-f]{40}) \d+ \d+", line)
            if m:
                cur = m.group(1)
                commits.setdefault(cur, {"sha": cur})
                continue
            if cur is None:
                continue
            if line.startswith("author "):
                commits[cur]["author"] = line[7:]
            elif line.startswith("author-time "):
                from datetime import UTC, datetime
                commits[cur]["date"] = datetime.fromtimestamp(int(line[12:]), UTC).date().isoformat()
            elif line.startswith("summary "):
                commits[cur]["summary"] = line[8:]
            elif line.startswith("\t"):
                result.append(commits[cur])
        return result
