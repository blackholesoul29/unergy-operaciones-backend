"""Tests del módulo de manejo seguro de archivos (app.utils.file_handling)."""
from __future__ import annotations

import asyncio
import pathlib
from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.utils.file_handling import (
    generate_secure_filename,
    get_secure_path,
    validate_and_save_file,
)

ALLOWED = ["application/pdf", "image/png"]


def _make_upload(content: bytes, filename: str | None, content_type: str | None) -> UploadFile:
    headers = Headers({"content-type": content_type}) if content_type else Headers({})
    return UploadFile(file=BytesIO(content), filename=filename, headers=headers, size=len(content))


# ── generate_secure_filename ──────────────────────────────────────────────────

def test_generate_secure_filename_preserves_extension():
    name = generate_secure_filename("factura.pdf")
    assert name.endswith(".pdf")
    assert name != "factura.pdf"
    # 32 hex chars + ".pdf"
    assert len(name) == 32 + len(".pdf")


def test_generate_secure_filename_strips_path_traversal():
    name = generate_secure_filename("../../etc/passwd.pdf")
    assert "/" not in name
    assert ".." not in name
    assert name.endswith(".pdf")


def test_generate_secure_filename_handles_no_extension():
    name = generate_secure_filename("noext")
    assert "/" not in name
    assert len(name) == 32


def test_generate_secure_filename_is_unique():
    assert generate_secure_filename("a.pdf") != generate_secure_filename("a.pdf")


# ── validate_and_save_file ────────────────────────────────────────────────────

def test_validate_and_save_rejects_disallowed_mime(tmp_path):
    up = _make_upload(b"data", "evil.exe", "application/x-msdownload")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(validate_and_save_file(up, tmp_path, "x.exe", 1024, ALLOWED))
    assert exc.value.status_code == 400


def test_validate_and_save_rejects_empty_filename(tmp_path):
    up = _make_upload(b"data", "", "application/pdf")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(validate_and_save_file(up, tmp_path, "x.pdf", 1024, ALLOWED))
    assert exc.value.status_code == 400


def test_validate_and_save_rejects_oversized_file_and_removes_partial(tmp_path):
    up = _make_upload(b"x" * 5000, "big.pdf", "application/pdf")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(validate_and_save_file(up, tmp_path, "big.pdf", 1024, ALLOWED))
    assert exc.value.status_code == 413
    # partial file must be cleaned up
    assert not (tmp_path / "big.pdf").exists()


def test_validate_and_save_writes_valid_file(tmp_path):
    dest = tmp_path / "uploads" / "sub"
    up = _make_upload(b"hello pdf", "doc.pdf", "application/pdf")
    asyncio.run(validate_and_save_file(up, dest, "secure.pdf", 1024, ALLOWED))
    saved = dest / "secure.pdf"
    assert saved.exists()
    assert saved.read_bytes() == b"hello pdf"


# ── get_secure_path ───────────────────────────────────────────────────────────

def test_get_secure_path_valid(tmp_path):
    p = get_secure_path(tmp_path, "om_uploads", "file.pdf")
    assert p.resolve().is_relative_to(tmp_path.resolve())
    assert p.name == "file.pdf"


def test_get_secure_path_blocks_traversal_in_filename(tmp_path):
    with pytest.raises(HTTPException) as exc:
        get_secure_path(tmp_path, "om_uploads", "../../../../etc/passwd")
    assert exc.value.status_code == 400


def test_get_secure_path_blocks_traversal_in_subdir(tmp_path):
    with pytest.raises(HTTPException) as exc:
        get_secure_path(tmp_path, "../../../etc", "passwd")
    assert exc.value.status_code == 400
