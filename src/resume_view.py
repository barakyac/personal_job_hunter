import io

import streamlit as st

from src import fit_analysis, ollama_client, resume_extract, storage

RESUME_KEY = "resume_text_area"


def _remove_personal_file(filename: str) -> None:
    storage.delete_personal_file(filename)
    _rebuild_personal_context()


@st.dialog("Remove this document?")
def _confirm_remove_dialog(filename: str) -> None:
    st.write(f"This permanently deletes **{filename}** from your supporting documents.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button("Remove", key=f"confirm_remove_personal_{filename}", type="primary"):
            _remove_personal_file(filename)
            st.rerun()
    with cancel_col:
        if st.button("Cancel", key=f"cancel_remove_personal_{filename}"):
            st.rerun()


def render() -> None:
    st.markdown('<div class="jh-page-title">Profile</div>', unsafe_allow_html=True)
    st.caption(
        "Your resume, supporting documents, and work information - what the assistant and "
        "fit scoring read when matching you against a job."
    )

    st.subheader("Resume")
    st.caption(
        "Plain text/Markdown. Ask the assistant in chat to analyze fit against a saved job "
        "or a First Call application - it reads this file and writes a fit score and notes below."
    )

    if RESUME_KEY not in st.session_state:
        st.session_state[RESUME_KEY] = storage.load_resume()

    # Defaults to Edit so the raw text area is there on first load (and for
    # every existing caller/test that writes to it directly) - Preview is an
    # explicit opt-in for a cleaner read, not a replacement for editing.
    mode = st.segmented_control(
        "Resume view", ["Edit", "Preview"], default="Edit", key="resume_view_mode"
    )
    mode = mode or "Edit"

    if mode == "Preview":
        if st.session_state[RESUME_KEY].strip():
            with st.container(border=True):
                st.markdown(st.session_state[RESUME_KEY])
        else:
            st.caption("No resume text yet - switch to Edit to add one.")
    else:
        uploaded = st.file_uploader("Upload resume (PDF or DOCX)", type=["pdf", "docx"])
        if st.button("Use uploaded file", disabled=uploaded is None):
            try:
                text = resume_extract.extract_text(uploaded)
            except Exception as exc:
                st.error(f"Could not read {uploaded.name}: {exc}")
            else:
                storage.save_resume_original(uploaded.getvalue(), uploaded.name)
                storage.save_resume(text)
                st.session_state[RESUME_KEY] = text
                st.success(f"Extracted text from {uploaded.name} and saved.")

        st.text_area("Resume", height=400, key=RESUME_KEY, label_visibility="collapsed")

        if st.button("Save resume", type="primary"):
            storage.save_resume(st.session_state[RESUME_KEY])
            st.success("Resume saved.")

    original_path = storage.load_resume_original_path()
    if original_path:
        st.caption(f"Original file on record: {original_path.name}")
        st.download_button(
            "Download original resume",
            data=original_path.read_bytes(),
            file_name=original_path.name,
        )

    st.divider()
    st.subheader("Supporting documents")
    st.caption(
        "Cover letters, certifications, portfolio notes - anything beyond the "
        "resume that should inform fit scoring. Every file here is folded into "
        "the context Ollama sees on each fit check."
    )

    uploader_version = st.session_state.get("personal_uploader_version", 0)
    extra_uploaded = st.file_uploader(
        "Upload a supporting document (PDF, DOCX, TXT, or MD)",
        type=["pdf", "docx", "txt", "md"],
        key=f"personal_file_uploader_{uploader_version}",
    )
    if st.button("Add supporting document", disabled=extra_uploaded is None):
        try:
            resume_extract.extract_text(extra_uploaded)
        except Exception as exc:
            st.error(f"Could not read {extra_uploaded.name}: {exc}")
        else:
            storage.save_personal_file(extra_uploaded.getvalue(), extra_uploaded.name)
            _rebuild_personal_context()
            st.session_state["personal_uploader_version"] = uploader_version + 1
            st.success(f"Added {extra_uploaded.name}.")
            st.rerun()

    personal_files = storage.list_personal_files()
    if personal_files:
        for path in personal_files:
            col_name, col_remove = st.columns([4, 1])
            col_name.write(path.name)
            if col_remove.button("Remove", key=f"remove_personal_{path.name}"):
                _confirm_remove_dialog(path.name)
    else:
        st.caption("No supporting documents yet.")

    st.divider()
    st.subheader("Work information & fit")
    st.caption("How your resume and supporting documents score against positions you're tracking.")

    st.markdown("**Fit - Saved Positions**")
    st.caption(f"Scored locally with Ollama ({ollama_client.DEFAULT_MODEL}). A full batch can take a while.")
    if st.button(f"Analyze all saved jobs (Ollama {ollama_client.DEFAULT_MODEL})"):
        _run_batch_analysis(storage.load_saved, storage.save_saved, filter_status=None)
    _render_fit_list(storage.load_saved())

    st.markdown("**Fit - First Call Applications**")
    if st.button(f"Analyze First Call applications (Ollama {ollama_client.DEFAULT_MODEL})"):
        _run_batch_analysis(storage.load_applied, storage.save_applied, filter_status="First Call")
    applied = [r for r in storage.load_applied() if (r.get("status") or "") == "First Call"]
    _render_fit_list(applied)


def _rebuild_personal_context() -> None:
    parts = []
    for path in storage.list_personal_files():
        buf = io.BytesIO(path.read_bytes())
        buf.name = path.name
        try:
            text = resume_extract.extract_text(buf)
        except Exception:
            continue
        if text.strip():
            parts.append(f"--- {path.name} ---\n{text}")
    storage.save_personal_context("\n\n".join(parts))


def _run_batch_analysis(loader, saver, filter_status: str | None) -> None:
    resume_text = st.session_state.get(RESUME_KEY, "")
    if not resume_text.strip():
        st.error("Add a resume above first.")
        return

    records = loader()
    targets = [
        i for i, r in enumerate(records)
        if not filter_status or (r.get("status") or "") == filter_status
    ]
    if not targets:
        st.info("Nothing to analyze.")
        return

    progress = st.progress(0.0)
    status_box = st.empty()

    def on_progress(n, total, job):
        status_box.text(f"Analyzing {job.get('company', '?')} - {job.get('title', '')}...")
        progress.progress(n / total)

    errors = fit_analysis.analyze_many(resume_text, records, targets, on_progress=on_progress)
    progress.progress(1.0)
    status_box.empty()

    saver(records)
    for error in errors:
        st.warning(error)
    st.success(f"Analyzed {len(targets) - len(errors)} of {len(targets)} position(s).")


def _render_fit_list(records: list[dict]) -> None:
    if not records:
        st.info("Nothing here yet.")
        return

    for record in records:
        with st.container(border=True):
            st.markdown(f"**{record.get('company') or 'Unknown company'}** - {record.get('title') or ''}")
            if record.get("link"):
                st.markdown(f"[Open posting]({record['link']})")

            fit_score = record.get("fit_score")
            fit_notes = record.get("fit_notes")
            if fit_score not in (None, ""):
                st.markdown(f"Fit score: **{fit_score}**")
            if fit_notes:
                st.caption(fit_notes)
            else:
                st.caption("No fit analysis yet - ask the assistant to analyze this one against your resume.")
