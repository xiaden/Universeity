"""Archive-security tests (Phase C, P1-S2/S4).

Verifies the archive allowlist + escape-rejection boundary: absolute paths,
``..`` traversal, symlink members, non-allowlisted suffixes, and the
count/decompressed-size ceilings are all rejected before any extraction. The
validation is defense-in-depth in the sandbox boundary, never a substitute for
OS isolation (which capability reporting treats honestly).
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from umd.security.archive import (
    ArchiveDenial,
    ArchivePlan,
    extract_zip,
    sanitize_tar,
    sanitize_zip,
)
from umd.security.sandbox import SandboxLimits, SandboxPolicy

_EPUB_ALLOW = ("xml", "opf", "html", "xhtml", "css", "png", "jpg", "svg")


def _policy(allow: tuple[str, ...] = _EPUB_ALLOW, **kw) -> SandboxPolicy:
    return SandboxPolicy(archive_allow_extensions=allow, **kw)


def _zip(members: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


class TestZipPathSafety:
    def test_absolute_rejected(self) -> None:
        with pytest.raises(ArchiveDenial) as ei:
            sanitize_zip(_zip({"/etc/evil": b"x"}), policy=_policy(), limits=SandboxLimits())
        assert "absolute" in str(ei.value) or "unsafe" in str(ei.value)

    def test_traversal_rejected(self) -> None:
        with pytest.raises(ArchiveDenial):
            sanitize_zip(_zip({"../pwned.txt": b"x"}), policy=_policy(), limits=SandboxLimits())

    def test_windows_drive_rejected(self) -> None:
        with pytest.raises(ArchiveDenial):
            sanitize_zip(_zip({"C:/x.txt": b"x"}), policy=_policy(), limits=SandboxLimits())

    def test_not_allowlisted_extension_rejected(self) -> None:
        with pytest.raises(ArchiveDenial):
            sanitize_zip(
                _zip({"page.exe": b"x"}),
                policy=_policy(),
                limits=SandboxLimits(),
            )

    def test_allowlisted_members_pass(self) -> None:
        plan = sanitize_zip(
            _zip({"META-INF/container.xml": b"<x/>", "OEBPS/a.html": b"<p>hi</p>"}),
            policy=_policy(),
            limits=SandboxLimits(),
        )
        assert isinstance(plan, ArchivePlan)
        assert len(plan.members) == 2


class TestZipSymlink:
    def test_symlink_member_rejected(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("link")
            info.create_system = 3  # Unix
            info.external_attr = 0o120777 << 16  # S_IFLNK | 0777
            zf.writestr(info, b"/etc/passwd")
        buf.seek(0)
        with pytest.raises(ArchiveDenial):
            sanitize_zip(zipfile.ZipFile(buf), policy=_policy(), limits=SandboxLimits())


class TestTarSafety:
    def test_symlink_tar_member_rejected(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            link = tarfile.TarInfo("linkln")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)
        buf.seek(0)
        with pytest.raises(ArchiveDenial), tarfile.open(fileobj=buf) as tf2:
            sanitize_tar(tf2, policy=_policy(), limits=SandboxLimits())

    def test_traversal_tar_rejected(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo("../escape.txt")
            data = b"x"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        buf.seek(0)
        with pytest.raises(ArchiveDenial), tarfile.open(fileobj=buf) as tf2:
            sanitize_tar(tf2, policy=_policy(), limits=SandboxLimits())


class TestLimits:
    def test_file_count_limit(self) -> None:
        many = {f"f{i}.xml": b"x" for i in range(3)}
        with pytest.raises(ArchiveDenial):
            sanitize_zip(
                _zip(many),
                policy=_policy(),
                limits=SandboxLimits(max_files=2),
            )

    def test_decompressed_size_limit(self) -> None:
        # A tiny max_decompressed_bytes must reject a single modest member.
        with pytest.raises(ArchiveDenial):
            sanitize_zip(
                _zip({"big.xml": b"y" * 10}),
                policy=_policy(),
                limits=SandboxLimits(max_decompressed_bytes=5),
            )


class TestExtract:
    def test_extract_writes_only_safe_paths(self, tmp_path: Path) -> None:
        plan = extract_zip(
            _zip({"dir/a.xml": b"<a/>"}),
            tmp_path,
            policy=_policy(),
            limits=SandboxLimits(),
        )
        assert len(plan.members) == 1
        target = tmp_path / "dir" / "a.xml"
        assert target.read_bytes() == b"<a/>"
        # Nothing escaped the extraction root.
        outside = [p for p in tmp_path.rglob("*") if ".." in str(p)]
        assert not outside
