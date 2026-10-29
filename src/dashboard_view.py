import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import storage

MUTED_INK = "#898781"


def _chrome_colors() -> tuple[str, str]:
    theme_base = st.get_option("theme.base") or "light"
    if theme_base == "dark":
        return "#2c2c2a", "#383835"  # gridline, baseline
    return "#e1e0d9", "#c3c2b7"


def _style_layout(fig: go.Figure) -> go.Figure:
    gridline_color, baseline_color = _chrome_colors()
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=MUTED_INK, size=13),
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, linecolor=baseline_color, tickfont=dict(color=MUTED_INK))
    fig.update_yaxes(showgrid=True, gridcolor=gridline_color, zeroline=False, tickfont=dict(color=MUTED_INK))
    return fig


def render() -> None:
    st.header("Dashboard")

    saved = storage.load_saved()
    applied = storage.load_applied()

    status_counts = {s: 0 for s in storage.STATUS_OPTIONS}
    for record in applied:
        status = record.get("status") or "Applied"
        status_counts[status] = status_counts.get(status, 0) + 1

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Saved", len(saved))
    col2.metric("Applied (total)", len(applied))
    col3.metric("Interviewing", status_counts.get("Interviewing", 0))
    col4.metric("Offers", status_counts.get("Offer", 0))
    col5.metric("Rejected", status_counts.get("Rejected", 0))

    st.divider()

    left, right = st.columns(2)

    with left:
        st.subheader("Applications over time")
        dates = [r.get("date_applied") for r in applied if r.get("date_applied")]
        if dates:
            df = pd.DataFrame({"date": pd.to_datetime(dates)})
            daily = df.groupby("date").size().sort_index().cumsum().reset_index(name="total")
            fig = go.Figure(
                go.Scatter(
                    x=daily["date"],
                    y=daily["total"],
                    mode="lines+markers",
                    line=dict(color="#2a78d6", width=2),
                    marker=dict(size=6, color="#2a78d6"),
                    hovertemplate="%{x|%b %d, %Y}<br>Total applications: %{y}<extra></extra>",
                )
            )
            fig = _style_layout(fig)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No applications logged yet.")

    with right:
        st.subheader("Status breakdown")
        if applied:
            statuses = storage.STATUS_OPTIONS
            counts = [status_counts.get(s, 0) for s in statuses]
            colors = [storage.STATUS_COLORS[s] for s in statuses]
            fig = go.Figure(
                go.Bar(
                    x=statuses,
                    y=counts,
                    marker_color=colors,
                    text=counts,
                    textposition="outside",
                    hovertemplate="%{x}: %{y}<extra></extra>",
                )
            )
            fig.update_layout(bargap=0.4)
            fig = _style_layout(fig)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No applications logged yet.")
