from pathlib import Path


def extract_text(uploaded_file) -> str:
    """Extract plain text from an uploaded PDF, DOCX, or plain-text file-like object."""
    suffix = Path(uploaded_file.name).suffix.lower()

    if suffix == ".pdf":
        import pypdf

        reader = pypdf.PdfReader(uploaded_file)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()

    if suffix == ".docx":
        import docx

        document = docx.Document(uploaded_file)
        paragraphs = [p.text for p in document.paragraphs]
        return "\n".join(paragraphs).strip()

    if suffix in (".txt", ".md"):
        return uploaded_file.getvalue().decode("utf-8", errors="ignore").strip()

    raise ValueError(f"Unsupported file type: {suffix or uploaded_file.name}")
