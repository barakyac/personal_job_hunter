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
