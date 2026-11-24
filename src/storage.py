import json
import os
import shutil
from pathlib import Path

import pandas as pd


def data_dir() -> Path:
    """Resolved fresh on every call, never cached at import time.

    A module-level constant computed once from JOB_HUNTER_DATA_DIR is a trap:
    anything that does `from src import storage` before setting that env var
    - a pytest fixture that forgets the ordering, a one-off debug script, a
    REPL session - silently locks onto the real project data/ dir for the
    rest of that process, with no error. Resolving it fresh on every call
    means only the ordering at the actual read/write site matters, not at
    import time. (This bit us for real: a verification script imported
    storage before setting the override and clobbered data/saved_positions.json.)
    """
    return Path(os.environ.get("JOB_HUNTER_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")


def backup_dir() -> Path:
    """Sibling of data_dir() holding a rolling pre-overwrite copy of each
    record file - see _save(). Tracks data_dir()'s own override so tests
    (which point JOB_HUNTER_DATA_DIR at a tmp dir) back up into that tmp
    dir too, never into the real project's data-backup/."""
    return data_dir().parent / "data-backup"


def _saved_file() -> Path:
    return data_dir() / "saved_positions.json"


def _applied_file() -> Path:
    return data_dir() / "applied_positions.json"


def _resume_file() -> Path:
    return data_dir() / "resume.md"


def _matched_file() -> Path:
    return data_dir() / "matched_jobs.json"


def _match_profile_file() -> Path:
    return data_dir() / "match_profile.json"


def personal_dir() -> Path:
    return data_dir() / "personal"


def _personal_context_file() -> Path:
    return data_dir() / "personal_context.md"

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

# Whether the job posting itself is still accepting applications - distinct
# from APPLIED_COLUMNS' "status", which tracks this user's own pipeline
# stage (Applied, Interview, ...) once they've applied.
POSTING_STATUS_OPEN = "Open for applications"
POSTING_STATUS_CLOSED = "Closed for applications"
POSTING_STATUS_OPTIONS = [POSTING_STATUS_OPEN, POSTING_STATUS_CLOSED]

SAVED_COLUMNS = [
    "company", "title", "link", "location", "salary", "posting_status", "date_saved", "notes",
    "description", "fit_score", "fit_notes",
]
APPLIED_COLUMNS = [
    "company", "title", "link", "location", "salary",
    "date_saved", "date_applied", "status", "rejected_from_stage", "notes",
    "call_notes", "description", "fit_score", "fit_notes",
]


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save(path: Path, records: list[dict]) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    # Keep a rolling copy of what's about to be overwritten - cheap
    # insurance against a bad write (ours or a future bug's) losing data
    # with nowhere to recover it from.
    if path.exists():
        dest = backup_dir()
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest / path.name)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)


def load_saved() -> list[dict]:
    return _load(_saved_file())


def save_saved(records: list[dict]) -> None:
    _save(_saved_file(), records)


def load_applied() -> list[dict]:
    return _load(_applied_file())


def save_applied(records: list[dict]) -> None:
    _save(_applied_file(), records)


# Matching Jobs: candidate postings found by a source (Gmail job alerts,
# Google Jobs search, or Claude browsing LinkedIn/Google in Chrome) that the
# user hasn't decided on yet. Kept separate from saved_positions.json so a
# scan that pulls in 30 maybe-relevant jobs never floods Saved Jobs - a
# match only becomes a Saved Position when the user picks it.
MATCH_STATUS_NEW = "New"
MATCH_STATUS_SAVED = "Saved"
MATCH_STATUS_DISMISSED = "Dismissed"
MATCH_STATUS_OPTIONS = [MATCH_STATUS_NEW, MATCH_STATUS_SAVED, MATCH_STATUS_DISMISSED]

MATCH_SOURCE_GMAIL = "Gmail alert"
MATCH_SOURCE_GOOGLE = "Google Jobs"
MATCH_SOURCE_LINKEDIN = "LinkedIn (Claude)"
MATCH_SOURCE_GOOGLE_CLAUDE = "Google (Claude)"
MATCH_SOURCE_OPTIONS = [MATCH_SOURCE_GMAIL, MATCH_SOURCE_GOOGLE, MATCH_SOURCE_LINKEDIN, MATCH_SOURCE_GOOGLE_CLAUDE]

MATCHED_COLUMNS = [
    "company", "title", "link", "location", "salary", "source", "source_detail",
    "date_found", "match_status", "description", "fit_score", "fit_notes",
]

DEFAULT_MATCH_PROFILE = {
    "titles": [],
    "location": "",
    "keywords": [],
    "exclude_keywords": [],
}


def load_matched() -> list[dict]:
    return _load(_matched_file())


def save_matched(records: list[dict]) -> None:
    _save(_matched_file(), records)


def load_match_profile() -> dict:
    """What "matches your profile" means for searches: target titles, a
    location and optional keywords. Every key is always present, even for
    a file written before a key existed."""
    stored = {}
    if _match_profile_file().exists():
        with _match_profile_file().open("r", encoding="utf-8") as f:
            stored = json.load(f) or {}
    return {**DEFAULT_MATCH_PROFILE, **{k: v for k, v in stored.items() if k in DEFAULT_MATCH_PROFILE}}


def save_match_profile(profile: dict) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    clean = {k: profile.get(k, v) for k, v in DEFAULT_MATCH_PROFILE.items()}
    with _match_profile_file().open("w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)


def load_resume() -> str:
    if not _resume_file().exists():
        return ""
    return _resume_file().read_text(encoding="utf-8")


def save_resume(text: str) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    _resume_file().write_text(text, encoding="utf-8")


def save_resume_original(file_bytes: bytes, filename: str) -> Path:
    data_dir().mkdir(parents=True, exist_ok=True)
    for existing in data_dir().glob("resume_original.*"):
        existing.unlink()
    path = data_dir() / f"resume_original{Path(filename).suffix.lower()}"
    path.write_bytes(file_bytes)
    return path


def load_resume_original_path() -> Path | None:
    matches = list(data_dir().glob("resume_original.*"))
    return matches[0] if matches else None


def save_personal_file(file_bytes: bytes, filename: str) -> Path:
    """Store an original supporting document (cover letter, certs, notes, ...)."""
    personal_dir().mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    if not safe_name:
        raise ValueError("filename must not be empty")
    path = personal_dir() / safe_name
    path.write_bytes(file_bytes)
    return path


def list_personal_files() -> list[Path]:
    if not personal_dir().exists():
        return []
    return sorted(p for p in personal_dir().iterdir() if p.is_file())


def delete_personal_file(filename: str) -> None:
    path = personal_dir() / Path(filename).name
    if path.exists():
        path.unlink()


def save_personal_context(text: str) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    _personal_context_file().write_text(text, encoding="utf-8")


def load_personal_context() -> str:
    if not _personal_context_file().exists():
        return ""
    return _personal_context_file().read_text(encoding="utf-8")


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


NUMERIC_COLUMNS = {"fit_score"}

# Text columns whose missing/blank value should default to something other
# than "" - e.g. a record saved before posting_status existed, or added via
# a path that doesn't set it, is implicitly still open.
COLUMN_DEFAULTS = {"posting_status": POSTING_STATUS_OPEN}


def to_dataframe(records: list[dict], columns: list[str], date_cols: list[str]) -> pd.DataFrame:
    # A record missing a text column entirely (e.g. added via a path that
    # doesn't set fit_notes) leaves that whole column NaN, which pandas
    # infers as float64 - incompatible with a TextColumn's dtype check.
    # Default every text column to "" (or its COLUMN_DEFAULTS entry) so it
    # stays an object/string column.
    filled = [
        {
            col: (
                record.get(col)
                if col in NUMERIC_COLUMNS or col in date_cols
                else (record.get(col) or COLUMN_DEFAULTS.get(col, ""))
            )
            for col in columns
        }
        for record in records
    ]
    df = pd.DataFrame(filled, columns=columns)
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    for col in NUMERIC_COLUMNS & set(columns):
        df[col] = pd.to_numeric(df[col], errors="coerce")
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
                record[key] = COLUMN_DEFAULTS.get(key, "")
    return records
