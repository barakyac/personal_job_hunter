import io

import pytest

from src import resume_extract


def _make_upload(name: str, content: bytes):
    buf = io.BytesIO(content)
    buf.name = name
    return buf


def test_extract_text_txt():
    upload = _make_upload("notes.txt", b"Hello world")
    assert resume_extract.extract_text(upload) == "Hello world"


def test_extract_text_md():
    upload = _make_upload("notes.md", b"# Heading\nBody")
    assert resume_extract.extract_text(upload) == "# Heading\nBody"


def test_extract_text_unsupported_type_raises():
    upload = _make_upload("resume.xyz", b"data")
    with pytest.raises(ValueError):
        resume_extract.extract_text(upload)
