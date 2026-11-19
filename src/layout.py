"""Top-nav chrome: global CSS, the compact top bar, and the on-demand
assistant/settings overlays. Pulled out of app.py so it's independently
testable and app.py stays a thin wire-up.

The assistant panel is deliberately NOT an st.dialog: the panel must survive
many reruns triggered from inside itself (every chat message submit reruns
the whole script) with no further action from app.py, and the only
mechanism guaranteed to do that on every rerun is checking a plain
st.session_state flag at render time - the same approach app.py already
used for its permanent chat column before this redesign. A fixed-position
CSS container (the same st-key-derived-class trick app.py already used to
pin "Show Assistant" to a corner) turns that column into an overlay instead.
"""

import os

import streamlit as st

from src import chat_view, gmail_client

CURRENT_PAGE_KEY = "current_page"
SHOW_ASSISTANT_KEY = "show_assistant"

NAV_PAGES = ["Applications", "Saved Jobs", "Mail Inbox", "Profile"]

_BASE_CSS = """
<style>
.block-container {
    padding-top: 0.25rem;
    padding-bottom: 2rem;
    padding-left: 1.75rem;
    padding-right: 1.75rem;
    margin-top: 3.1rem;
    max-width: 100% !important;
    border: none !important;
    outline: none !important;
}
[data-testid="stMain"], [data-testid="stAppViewContainer"] {
    border: none !important;
}
/* Compact, consistent control heights across the app. */
div[data-testid="stButton"] button, div[data-testid="stLinkButton"] a,
div[data-testid="stDownloadButton"] button, div[data-testid="stPopover"] button {
    border-radius: 8px;
    min-height: 2.25rem;
    padding-top: 0.3rem;
    padding-bottom: 0.3rem;
}
div[data-testid="stTextInput"] input, div[data-testid="stNumberInput"] input,
div[data-testid="stDateInput"] input, div[data-testid="stSelectbox"] div[data-baseweb="select"] {
    border-radius: 8px;
}
/* Top nav bar - logo/nav/actions in one compact row, ~60px tall. Pinned to
the actual viewport (not just its scroll ancestor) since Streamlit's own
block-container sits inside a scrolling region that position:sticky can't
reliably anchor against here - see layout.py's render_top_nav docstring. */
div.st-key-top_nav {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 999997;
    background: #171a23;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    padding: 0.5rem 1.75rem;
}
div.st-key-top_nav div[data-testid="stButton"] button {
    border: none;
    background: transparent;
    font-weight: 500;
}
div.st-key-top_nav div[data-testid="stButton"] button[kind="primary"] {
    background: var(--primary-color, #5b5fc7);
}
.jh-logo {
    font-weight: 700;
    font-size: 1.05rem;
    line-height: 2.25rem;
    white-space: nowrap;
}
/* Page title scale, per design spec (~28-32px). */
.jh-page-title {
    font-size: 1.85rem;
    font-weight: 700;
    margin-bottom: 0.1rem;
}
/* Segmented controls (Active/Completed, Board/Table, outcome filters, ...):
a solid accent fill for the selected pill reads with far more contrast
against the dark surface than the default thin border + tinted text. */
div[role="radiogroup"] button[aria-checked="true"] {
    background: #5b5fc7 !important;
    color: #ffffff !important;
    border-color: #5b5fc7 !important;
}
/* Compact status badge used for stages/outcomes. */
.jh-badge {
    display: inline-block;
    padding: 0.1rem 0.55rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    white-space: nowrap;
}
.jh-company-mark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 6px;
    background: var(--jh-surface-raised, #262a38);
    font-size: 0.72rem;
    font-weight: 700;
    margin-right: 0.45rem;
    vertical-align: middle;
}
.jh-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
/* Compact page-header primary action: sized to its label, pinned to the
right edge of its column instead of stretched full-width. */
div[class*="st-key-jh-header-action-"] {
    display: flex;
    justify-content: flex-end;
}
/* "Card body opens details" without disturbing nested controls below it:
scoped to a small *-click- sub-container that wraps only the non-interactive
info block (company/title/meta), never the action row, so there is no
geometric overlap with the real stage selectbox / link / call buttons that
follow it in normal flow - no z-index layering needed. */
div[class*="st-key-jh-click-"] { position: relative; cursor: pointer; }
/* Streamlit wraps every element (including the button) in its own
data-testid="stElementContainer" div that's already position:relative -
THAT is the real containing block to turn into the full-card overlay, not
the stButton div one level deeper: making the button itself absolute while
its own element-container stays in normal flow leaves that container with
nothing left to size itself by (its only child was just taken out of flow),
so it collapses to 0 height and the "inset:0" below ends up relative to a
0x0 box instead of the card. */
div[class*="st-key-jh-click-"] > div[data-testid="stElementContainer"]:has(button) {
    position: absolute !important; inset: 0 !important;
    width: 100% !important; height: 100% !important; margin: 0 !important;
}
div[class*="st-key-jh-click-"] > div[data-testid="stElementContainer"]:has(button) div[data-testid="stButton"],
div[class*="st-key-jh-click-"] > div[data-testid="stElementContainer"]:has(button) button {
    width: 100% !important; height: 100% !important; margin: 0 !important;
}
div[class*="st-key-jh-click-"] > div[data-testid="stElementContainer"]:has(button) button {
    background: transparent !important; border: none !important; color: transparent !important;
    cursor: pointer; padding: 0 !important;
}
div[class*="st-key-jh-click-"] div[data-testid="stButton"] button:hover,
div[class*="st-key-jh-click-"] div[data-testid="stButton"] button:active {
    background: transparent; border: none; color: transparent;
}
div[class*="st-key-jh-click-"] div[data-testid="stButton"] button:focus-visible {
    outline: 2px solid #5b5fc7;
    outline-offset: 2px;
}
/* Compact job/application cards: tighter internal spacing than Streamlit's
default ~1rem stacked-element gap, and a surface subtly lifted off the page
background so cards read as distinct from it. */
div[class*="st-key-jh-card-"] {
    background: #1b1e29;
}
/* A flat 8px gap between every stacked element in a card (company/title,
title/meta, meta/follow-up, ...) - flex `gap` applies between items
regardless of how many lines a title wraps to, so this stays consistent for
single- and multi-line titles alike without per-pair overrides. */
div[class*="st-key-jh-card-"] div[data-testid="stVerticalBlock"] {
    gap: 8px;
}
div[class*="st-key-jh-card-"]:has(div[class*="st-key-jh-click-"]:hover) {
    background: #20232f;
}
.jh-next-action {
    display: inline-block;
    font-size: 0.78rem;
    font-weight: 600;
    padding: 0.05rem 0.5rem;
    border-radius: 999px;
}
/* Assistant overlay panel. */
div.st-key-assistant_panel {
    position: fixed;
    top: 0;
    right: 0;
    height: 100vh;
    width: 380px;
    max-width: 94vw;
    background: var(--jh-surface, #171a23);
    border-left: 1px solid rgba(255,255,255,0.08);
    box-shadow: -12px 0 32px rgba(0,0,0,0.45);
    z-index: 999998;
    overflow-y: auto;
    padding: 0.75rem 1rem 1rem 1rem;
}
@media (max-width: 680px) {
    div.st-key-assistant_panel { width: 100vw; max-width: 100vw; }
    .block-container { padding-left: 1rem; padding-right: 1rem; }
}
</style>
"""


def inject_base_css() -> None:
    st.markdown(_BASE_CSS, unsafe_allow_html=True)


def _initials(company: str) -> str:
    company = (company or "").strip()
    if not company:
        return "?"
    parts = [p for p in company.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return company[:2].upper()


def company_mark(company: str) -> str:
    """Small inline logo-stand-in (initials) used on compact job cards/rows."""
    return f'<span class="jh-company-mark">{_initials(company)}</span>'


def _set_page(page: str) -> None:
    st.session_state[CURRENT_PAGE_KEY] = page


def _toggle_assistant() -> None:
    st.session_state[SHOW_ASSISTANT_KEY] = not st.session_state.get(SHOW_ASSISTANT_KEY, False)


@st.dialog("Settings")
def _settings_dialog() -> None:
    st.caption("Read-only overview. Manage each connection from its own page.")

    st.markdown("**Assistant providers**")
    for name, provider in chat_view.PROVIDERS.items():
        env_var = provider["needs_key"]
        if env_var is None:
            st.caption(f"{name}: runs locally, no API key needed.")
        elif os.environ.get(env_var):
            st.caption(f"{name}: API key configured.")
        else:
            st.caption(f"{name}: no API key yet - add one from the Assistant panel.")

    st.markdown("**Gmail**")
    try:
        connected = gmail_client.is_connected()
    except gmail_client.GmailError:
        connected = False
    if connected:
        st.caption("Connected. Manage sync and disconnect from the Mail Inbox page.")
    else:
        st.caption("Not connected yet - connect from the Mail Inbox page.")

    st.markdown("**Appearance**")
    st.caption("Dark theme.")


def render_top_nav(current_page: str) -> None:
    with st.container(key="top_nav"):
        cols = st.columns([1.4, 1, 1, 1, 1, 0.1, 1.3, 0.55], gap="small", vertical_alignment="center")
        with cols[0]:
            st.markdown('<div class="jh-logo">🧭 Job Hunter</div>', unsafe_allow_html=True)
        for i, page in enumerate(NAV_PAGES):
            with cols[1 + i]:
                st.button(
                    page,
                    key=f"nav_{page}",
                    type="primary" if page == current_page else "secondary",
                    use_container_width=True,
                    on_click=_set_page,
                    args=(page,),
                )
        with cols[6]:
            st.button(
                "Ask Assistant",
                key="nav_ask_assistant",
                use_container_width=True,
                on_click=_toggle_assistant,
            )
        with cols[7]:
            if st.button("⚙️", key="nav_settings_btn", help="Settings"):
                _settings_dialog()


def _hide_assistant() -> None:
    st.session_state[SHOW_ASSISTANT_KEY] = False


def render_assistant_panel() -> None:
    if not st.session_state.get(SHOW_ASSISTANT_KEY):
        return
    with st.container(key="assistant_panel"):
        chat_view.render(on_hide=_hide_assistant)


def page_header(title: str, caption: str = "", primary_label: str | None = None, primary_key: str = "") -> bool:
    """Compact page header: title (+ caption) on the left, one primary action
    - sized to its own label, right-aligned, never stretched - on the right.
    Returns True the run the primary action button is clicked."""
    title_col, action_col = st.columns([5, 1.3], vertical_alignment="center")
    with title_col:
        st.markdown(f'<div class="jh-page-title">{title}</div>', unsafe_allow_html=True)
        if caption:
            st.caption(caption)
    clicked = False
    if primary_label:
        with action_col:
            with st.container(key=f"jh-header-action-{primary_key}"):
                clicked = st.button(primary_label, key=primary_key, type="primary")
    return clicked
