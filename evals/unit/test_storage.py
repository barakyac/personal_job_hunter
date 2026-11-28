import re

import pandas as pd
import pytest

from src import storage


def test_find_record_index_matches_by_link():
    records = [{"company": "Acme", "link": "https://acme.example/job"}]
    assert storage.find_record_index(records, "Acme", link="https://acme.example/job") == 0


def test_find_record_index_matches_by_company_case_insensitive():
    records = [{"company": "Acme", "title": "Backend"}]
    assert storage.find_record_index(records, "acme") == 0


def test_find_record_index_ambiguous_without_title_returns_none():
    records = [
        {"company": "Acme", "title": "Backend"},
        {"company": "Acme", "title": "Frontend"},
    ]
    assert storage.find_record_index(records, "Acme") is None
    assert storage.find_record_index(records, "Acme", title="Backend") == 0


def test_find_record_index_no_match_returns_none():
    assert storage.find_record_index([], "Nobody") is None


def test_save_and_load_saved_positions_roundtrip():
    records = [{"company": "Acme", "title": "Backend Engineer", "link": "", "fit_score": 7}]
    storage.save_saved(records)
    assert storage.load_saved() == records


def test_save_and_load_applied_positions_roundtrip():
    records = [{"company": "Acme", "status": "Applied"}]
    storage.save_applied(records)
    assert storage.load_applied() == records


def test_load_saved_missing_file_returns_empty_list():
    assert storage.load_saved() == []


def test_load_saved_raises_runtime_error_naming_the_backup_dir_on_corrupt_json():
    # Regression test: a truncated/corrupt file (an interrupted write, a
    # full disk) used to let the bare json.JSONDecodeError propagate - this
    # confirms it's now a clear RuntimeError pointing at where the rolling
    # backup copy (see storage._save) can be recovered from.
    storage.data_dir().mkdir(parents=True, exist_ok=True)
    path = storage.data_dir() / "saved_positions.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(RuntimeError, match=re.escape(str(storage.backup_dir()))):
        storage.load_saved()


def test_load_saved_raises_runtime_error_on_invalid_utf8_bytes():
    # UnicodeDecodeError (from invalid-UTF-8 bytes) isn't a JSONDecodeError
    # or OSError - it needs its own entry in _load's except tuple, or this
    # case falls through as a bare, un-actionable traceback.
    storage.data_dir().mkdir(parents=True, exist_ok=True)
    path = storage.data_dir() / "saved_positions.json"
    path.write_bytes(b"\xff\xfe[")

    with pytest.raises(RuntimeError, match=re.escape(str(storage.backup_dir()))):
        storage.load_saved()


def test_load_match_profile_falls_back_to_defaults_on_invalid_utf8_bytes():
    # Same UnicodeDecodeError gap as _load, but load_match_profile()'s own
    # contract (unlike _load's) is to fall back to defaults rather than
    # raise, since matches_view.render() calls this as the very first thing
    # it does and a corrupt profile must not take down the whole page.
    storage.data_dir().mkdir(parents=True, exist_ok=True)
    path = storage.data_dir() / "match_profile.json"
    path.write_bytes(b"\xff\xfe[")

    assert storage.load_match_profile() == storage.DEFAULT_MATCH_PROFILE


def test_load_match_profile_falls_back_to_defaults_when_json_is_not_an_object():
    storage.data_dir().mkdir(parents=True, exist_ok=True)
    path = storage.data_dir() / "match_profile.json"
    path.write_text("[]", encoding="utf-8")

    assert storage.load_match_profile() == storage.DEFAULT_MATCH_PROFILE


def test_resume_save_and_load_roundtrip():
    storage.save_resume("My resume text")
    assert storage.load_resume() == "My resume text"


def test_load_resume_missing_file_returns_empty_string():
    assert storage.load_resume() == ""


def test_personal_file_add_list_delete():
    assert storage.list_personal_files() == []
    storage.save_personal_file(b"hello", "notes.txt")
    assert [p.name for p in storage.list_personal_files()] == ["notes.txt"]
    storage.delete_personal_file("notes.txt")
    assert storage.list_personal_files() == []


def test_save_personal_file_strips_path_traversal():
    path = storage.save_personal_file(b"hello", "../../etc/evil.txt")
    assert path.parent == storage.personal_dir()
    assert path.name == "evil.txt"
    storage.delete_personal_file("../../etc/evil.txt")
    assert storage.list_personal_files() == []


def test_personal_context_save_and_load_roundtrip():
    assert storage.load_personal_context() == ""
    storage.save_personal_context("some context")
    assert storage.load_personal_context() == "some context"


def test_dataframe_roundtrip_preserves_data():
    records = [{"company": "Acme", "title": "Backend", "date_saved": "2026-01-01"}]
    df = storage.to_dataframe(records, storage.SAVED_COLUMNS, date_cols=["date_saved"])
    out = storage.from_dataframe(df, date_cols=["date_saved"])
    assert out[0]["company"] == "Acme"
    assert out[0]["date_saved"] == "2026-01-01"


def test_from_dataframe_drops_rows_missing_required_col():
    records = [{"company": "", "title": "Backend"}, {"company": "Acme", "title": "X"}]
    df = storage.to_dataframe(records, storage.SAVED_COLUMNS, date_cols=["date_saved"])
    out = storage.from_dataframe(df, date_cols=["date_saved"])
    assert len(out) == 1
    assert out[0]["company"] == "Acme"


def test_to_dataframe_text_column_missing_everywhere_stays_string_dtype():
    # Regression: a record added without a "fit_notes" key at all (e.g. via
    # the paste-to-create flow) used to leave that whole column NaN/float64,
    # which st.data_editor's TextColumn rejects with a StreamlitAPIException.
    records = [{"company": "Acme", "title": "Backend", "date_saved": "2026-01-01"}]
    df = storage.to_dataframe(records, storage.SAVED_COLUMNS, date_cols=["date_saved"])
    assert not pd.api.types.is_float_dtype(df["fit_notes"])
    assert df["fit_notes"].iloc[0] == ""


def test_to_dataframe_numeric_column_missing_everywhere_stays_numeric_dtype():
    records = [{"company": "Acme", "title": "Backend", "date_saved": "2026-01-01"}]
    df = storage.to_dataframe(records, storage.SAVED_COLUMNS, date_cols=["date_saved"])
    assert df["fit_score"].dtype.kind == "f"
    assert pd.isna(df["fit_score"].iloc[0])


def test_to_dataframe_defaults_posting_status_to_open_when_missing():
    # A record saved before posting_status existed, or added via a path
    # that doesn't set it, is implicitly still open - not blank.
    records = [{"company": "Acme", "title": "Backend", "date_saved": "2026-01-01"}]
    df = storage.to_dataframe(records, storage.SAVED_COLUMNS, date_cols=["date_saved"])
    assert df["posting_status"].iloc[0] == storage.POSTING_STATUS_OPEN


def test_to_dataframe_preserves_explicit_posting_status():
    records = [{"company": "Acme", "posting_status": storage.POSTING_STATUS_CLOSED, "date_saved": "2026-01-01"}]
    df = storage.to_dataframe(records, storage.SAVED_COLUMNS, date_cols=["date_saved"])
    assert df["posting_status"].iloc[0] == storage.POSTING_STATUS_CLOSED


def test_from_dataframe_defaults_posting_status_to_open_when_blank():
    records = [{"company": "Acme", "date_saved": "2026-01-01"}]
    df = storage.to_dataframe(records, storage.SAVED_COLUMNS, date_cols=["date_saved"])
    df["posting_status"] = None
    out = storage.from_dataframe(df, date_cols=["date_saved"])
    assert out[0]["posting_status"] == storage.POSTING_STATUS_OPEN
