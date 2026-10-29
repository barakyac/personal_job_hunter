import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SAVED_FILE = DATA_DIR / "saved_positions.json"
APPLIED_FILE = DATA_DIR / "applied_positions.json"
RESUME_FILE = DATA_DIR / "resume.md"
PERSONAL_DIR = DATA_DIR / "personal"
PERSONAL_CONTEXT_FILE = DATA_DIR / "personal_context.md"

PIPELINE_STATUSES = [
    "Applied",
    "First Call",
    "Assignment / Home Test",
    "Interview",
    "Reference Check",
]
OUTCOME_STATUSES = ["Offer", "Rejected", "Withdrawn"]
STATUS_OPTIONS = PIPELINE_STATUSES + OUTCOME_STATUSES

# Fixed status colors (never themed) - see dataviz skill palette.
# In-process pipeline stages take the fixed categorical hue order (identity,
# not sentiment); terminal outcomes take the reserved status-palette colors.
STATUS_COLORS = {
    "Applied": "#2a78d6",                 # categorical slot 1 - blue
    "First Call": "#eb6834",              # categorical slot 2 - orange
    "Assignment / Home Test": "#1baf7a",  # categorical slot 3 - aqua
    "Interview": "#eda100",               # categorical slot 4 - yellow
    "Reference Check": "#e87ba4",         # categorical slot 5 - magenta
    "Offer": "#0ca30c",                   # status: good
    "Rejected": "#d03b3b",                # status: critical
    "Withdrawn": "#898781",               # muted
}

SAVED_COLUMNS = [
    "company", "title", "link", "location", "salary", "date_saved", "notes",
    "fit_score", "fit_notes",
]
APPLIED_COLUMNS = [
    "company", "title", "link", "location", "salary",
    "date_saved", "date_applied", "status", "notes",
    "fit_score", "fit_notes",
]


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: Path, records: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)


def load_saved() -> list[dict]:
    return _load(SAVED_FILE)


def save_saved(records: list[dict]) -> None:
    _save(SAVED_FILE, records)


def load_applied() -> list[dict]:
    return _load(APPLIED_FILE)


def save_applied(records: list[dict]) -> None:
    _save(APPLIED_FILE, records)


def load_resume() -> str:
    if not RESUME_FILE.exists():
        return ""
    return RESUME_FILE.read_text(encoding="utf-8")


def save_resume(text: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESUME_FILE.write_text(text, encoding="utf-8")


def save_resume_original(file_bytes: bytes, filename: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for existing in DATA_DIR.glob("resume_original.*"):
        existing.unlink()
    path = DATA_DIR / f"resume_original{Path(filename).suffix.lower()}"
    path.write_bytes(file_bytes)
    return path


def load_resume_original_path() -> Path | None:
    matches = list(DATA_DIR.glob("resume_original.*"))
    return matches[0] if matches else None


def save_personal_file(file_bytes: bytes, filename: str) -> Path:
    """Store an original supporting document (cover letter, certs, notes, ...)."""
    PERSONAL_DIR.mkdir(parents=True, exist_ok=True)
    path = PERSONAL_DIR / filename
    path.write_bytes(file_bytes)
    return path


def list_personal_files() -> list[Path]:
    if not PERSONAL_DIR.exists():
        return []
    return sorted(p for p in PERSONAL_DIR.iterdir() if p.is_file())


def delete_personal_file(filename: str) -> None:
    path = PERSONAL_DIR / filename
    if path.exists():
        path.unlink()


def save_personal_context(text: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PERSONAL_CONTEXT_FILE.write_text(text, encoding="utf-8")


def load_personal_context() -> str:
    if not PERSONAL_CONTEXT_FILE.exists():
        return ""
    return PERSONAL_CONTEXT_FILE.read_text(encoding="utf-8")


def find_record_index(records: list[dict], company: str, title: str = "", link: str = "") -> int | None:
    """Find a record by link (exact match) or by company (+ title if ambiguous)."""
    if link:
        for i, r in enumerate(records):
            if r.get("link") == link:
                return i
    matches = [
        i for i, r in enumerate(records)
        if r.get("company", "").strip().lower() == company.strip().lower()
        and (not title or r.get("title", "").strip().lower() == title.strip().lower())
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def to_dataframe(records: list[dict], columns: list[str], date_cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=columns)
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df


def from_dataframe(df: pd.DataFrame, date_cols: list[str], required_col: str = "company") -> list[dict]:
    df = df.dropna(subset=[required_col])
    df = df[df[required_col].astype(str).str.strip() != ""]
    records = df.to_dict(orient="records")
    for record in records:
        for col in date_cols:
            value = record.get(col)
            if pd.isna(value):
                record[col] = None
            else:
                record[col] = value.isoformat() if hasattr(value, "isoformat") else str(value)
        for key, value in record.items():
            if key not in date_cols and pd.isna(value):
                record[key] = ""
    return records
