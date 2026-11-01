from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import AppTestError
import pytest

from src import storage


def _render_resume():
    from src import resume_view

    resume_view.render()


def test_loads_existing_resume_into_text_area():
    storage.save_resume("Experienced backend engineer.")

    at = AppTest.from_function(_render_resume).run()

    assert not at.exception
    assert at.text_area(key="resume_text_area").value == "Experienced backend engineer."


def test_save_resume_button_persists_text_area_value():
    at = AppTest.from_function(_render_resume).run()

    at.text_area(key="resume_text_area").set_value("Updated resume text.").run()
    save_button = next(b for b in at.button if b.label == "Save resume")
    save_button.click().run()

    assert not at.exception
    assert storage.load_resume() == "Updated resume text."
    assert any("Resume saved." in s.value for s in at.success)


def test_use_uploaded_file_button_disabled_without_an_upload():
    at = AppTest.from_function(_render_resume).run()

    use_button = next(b for b in at.button if b.label == "Use uploaded file")
    with pytest.raises(AppTestError):
        use_button.click()


def _docx_bytes(text: str) -> bytes:
    import io

    import docx

    document = docx.Document()
    document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def test_uploading_a_resume_extracts_and_saves_it():
    at = AppTest.from_function(_render_resume).run()

    uploader = next(f for f in at.file_uploader if f.label == "Upload resume (PDF or DOCX)")
    content = _docx_bytes("Senior engineer, 10 years Python.")
    uploader.upload(
        "resume.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ).run()
    use_button = next(b for b in at.button if b.label == "Use uploaded file")
    use_button.click().run()

    assert not at.exception
    assert storage.load_resume() == "Senior engineer, 10 years Python."
    assert any("Extracted text from resume.docx and saved." in s.value for s in at.success)


def test_no_download_button_without_an_original_resume_on_record():
    at = AppTest.from_function(_render_resume).run()

    assert not at.exception
    assert not at.download_button


def test_download_button_shown_once_original_resume_is_on_record():
    storage.save_resume_original(b"%PDF-1.4 fake pdf bytes", "resume.pdf")

    at = AppTest.from_function(_render_resume).run()

    assert not at.exception
    assert any("resume_original.pdf" in c.value for c in at.caption)
    assert at.download_button[0].label == "Download original resume"


def test_no_supporting_documents_shows_placeholder():
    at = AppTest.from_function(_render_resume).run()

    assert not at.exception
    assert any("No supporting documents yet." in c.value for c in at.caption)


def test_adding_a_supporting_document_rebuilds_personal_context():
    at = AppTest.from_function(_render_resume).run()

    uploader = next(f for f in at.file_uploader if "supporting document" in f.label)
    uploader.upload("cover_letter.txt", b"Dear hiring manager, ...", "text/plain").run()
    add_button = next(b for b in at.button if b.label == "Add supporting document")
    add_button.click().run()

    assert not at.exception
    assert [p.name for p in storage.list_personal_files()] == ["cover_letter.txt"]
    assert "Dear hiring manager" in storage.load_personal_context()


def test_removing_a_supporting_document_updates_the_list_and_context():
    storage.save_personal_file(b"Dear hiring manager, ...", "cover_letter.txt")

    at = AppTest.from_function(_render_resume).run()
    assert any(w.value == "cover_letter.txt" for w in list(at.markdown) + list(at.text))

    remove_button = next(b for b in at.button if b.key == "remove_personal_cover_letter.txt")
    remove_button.click().run()

    assert not at.exception
    assert storage.list_personal_files() == []


def test_analyze_saved_jobs_requires_a_resume_first():
    at = AppTest.from_function(_render_resume).run()

    analyze_button = next(b for b in at.button if b.label == "Analyze all saved jobs with Ollama")
    analyze_button.click().run()

    assert not at.exception
    assert any("Add a resume above first." in e.value for e in at.error)


def test_analyze_saved_jobs_reports_nothing_to_analyze_when_list_is_empty():
    at = AppTest.from_function(_render_resume).run()
    at.text_area(key="resume_text_area").set_value("Some resume.").run()

    analyze_button = next(b for b in at.button if b.label == "Analyze all saved jobs with Ollama")
    analyze_button.click().run()

    assert not at.exception
    assert any("Nothing to analyze." in i.value for i in at.info)


def test_analyze_saved_jobs_scores_records_with_ollama(monkeypatch):
    from src import fit_analysis

    storage.save_saved([{"company": "Acme", "title": "Backend", "description": "Backend role."}])

    monkeypatch.setattr(
        fit_analysis,
        "analyze_many",
        lambda resume_text, records, targets, on_progress=None: (
            records[0].__setitem__("fit_score", 8),
            records[0].__setitem__("fit_notes", "Strong match."),
            [],
        )[-1],
    )

    at = AppTest.from_function(_render_resume).run()
    at.text_area(key="resume_text_area").set_value("Some resume.").run()

    analyze_button = next(b for b in at.button if b.label == "Analyze all saved jobs with Ollama")
    analyze_button.click().run()

    assert not at.exception
    assert storage.load_saved()[0]["fit_score"] == 8
    assert any("Analyzed 1 of 1 position(s)." in s.value for s in at.success)


def test_fit_list_shows_placeholder_when_empty():
    at = AppTest.from_function(_render_resume).run()

    assert not at.exception
    assert any("Nothing here yet." in i.value for i in at.info)


def test_fit_list_shows_score_and_notes_for_saved_positions():
    storage.save_saved(
        [{"company": "Acme", "title": "Backend", "link": "https://acme.example/jobs/1", "fit_score": 7, "fit_notes": "Good overlap on backend skills."}]
    )

    at = AppTest.from_function(_render_resume).run()

    assert not at.exception
    assert any("Acme" in m.value and "Backend" in m.value for m in at.markdown)
    assert any("Fit score: **7**" in m.value for m in at.markdown)
    assert any("Good overlap on backend skills." in c.value for c in at.caption)


def test_fit_list_only_shows_first_call_applications():
    storage.save_applied(
        [
            {"company": "Acme", "title": "Backend", "status": "First Call"},
            {"company": "Globex", "title": "Backend", "status": "Applied"},
        ]
    )

    at = AppTest.from_function(_render_resume).run()

    assert not at.exception
    assert any("Acme" in m.value for m in at.markdown)
    assert not any("Globex" in m.value for m in at.markdown)
