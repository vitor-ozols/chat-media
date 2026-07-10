from __future__ import annotations

import streamlit as st

MODEL_CHOICES = [
    "codex-mini-latest",
    "gpt-5",
    "gpt-5-mini",
]
EFFORT_CHOICES = ["low", "medium", "high"]
SANDBOX_CHOICES = ["read", "write", "full"]


def configure_page(
    title: str,
    subtitle: str,
) -> None:
    st.set_page_config(
        page_title=title,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_styles()
    if title or subtitle:
        render_hero(title, subtitle)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(189, 87, 46, 0.16), transparent 24%),
                    radial-gradient(circle at bottom right, rgba(26, 107, 95, 0.18), transparent 22%),
                    linear-gradient(180deg, #10151b 0%, #17212b 100%);
            }
            html, body, [class*="css"] {
                color: #f3efe6;
                font-family: "Trebuchet MS", "Segoe UI", sans-serif;
            }
            h1, h2, h3, [data-testid="stMetricLabel"] {
                font-family: Georgia, "Times New Roman", serif;
                letter-spacing: 0.02em;
            }
            .hero {
                padding: 1.25rem 1.4rem;
                border-radius: 24px;
                background: linear-gradient(135deg, rgba(16, 21, 27, 0.96), rgba(44, 34, 24, 0.92));
                border: 1px solid rgba(231, 176, 86, 0.18);
                box-shadow: 0 22px 40px rgba(0, 0, 0, 0.26);
                margin-bottom: 1rem;
            }
            .hero h1 { margin: 0; font-size: 2.5rem; }
            .hero p { margin: 0.5rem 0 0; color: rgba(243, 239, 230, 0.76); max-width: 60rem; }
            div[data-testid="stVerticalBlockBorderWrapper"] {
                background: rgba(23, 33, 43, 0.76);
                border: 1px solid rgba(231, 176, 86, 0.11);
                border-radius: 20px;
                box-shadow: 0 18px 36px rgba(0, 0, 0, 0.14);
            }
            div[data-testid="stMetric"] {
                background: rgba(23, 33, 43, 0.84);
                border: 1px solid rgba(231, 176, 86, 0.11);
                border-radius: 18px;
                padding: 0.8rem 1rem;
                box-shadow: 0 18px 36px rgba(0, 0, 0, 0.14);
            }
            .muted {
                color: rgba(243, 239, 230, 0.74);
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="hero">
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_codex_sidebar(service) -> str:
    models = service.list_codex_models()
    model_choices = [item["id"] for item in models] or MODEL_CHOICES
    default_model = next((item["id"] for item in models if item.get("default")), model_choices[0])
    st.session_state.setdefault("codex_model", default_model)
    st.session_state.setdefault("codex_effort", "medium")
    st.session_state.setdefault("codex_sandbox", "full")
    st.session_state.setdefault("codex_new_chat", False)
    threads = service.list_codex_threads(limit=20, model=st.session_state.get("codex_model"))
    if "codex_thread_id" not in st.session_state:
        st.session_state["codex_thread_id"] = threads[0]["id"] if threads else None

    st.sidebar.header("Codex")
    if st.sidebar.button("Novo chat", width="stretch"):
        st.session_state["codex_thread_id"] = None
        st.session_state["codex_new_chat"] = True
        st.rerun()

    config_tab, history_tab = st.sidebar.tabs(["Config", "Historico"])

    with config_tab:
        st.selectbox("Modelo", model_choices, key="codex_model")
        st.selectbox("Effort", EFFORT_CHOICES, key="codex_effort")
        st.selectbox("Sandbox", SANDBOX_CHOICES, key="codex_sandbox")
        status = service.codex.status()
        if status.available:
            st.caption(status.version or "Codex CLI")
        st.caption("`full` permite que o Codex use os mounts do host dentro do container.")

    with history_tab:
        thread_ids = [item["id"] for item in threads]
        current = st.session_state.get("codex_thread_id")
        if current is None and st.session_state.get("codex_new_chat"):
            st.caption("Novo chat em branco.")
        elif current not in thread_ids and thread_ids:
            current = thread_ids[0]
            st.session_state["codex_thread_id"] = current
        if thread_ids:
            labels = {item["id"]: item["name"] for item in threads}
            selection = st.radio(
                "Ultimas 20 conversas",
                thread_ids,
                index=None if st.session_state.get("codex_new_chat") and current is None else thread_ids.index(st.session_state["codex_thread_id"]),
                format_func=lambda value: labels.get(value, value),
                label_visibility="collapsed",
            )
            if selection:
                st.session_state["codex_thread_id"] = selection
                st.session_state["codex_new_chat"] = False
        else:
            st.caption("Sem conversas do Codex ainda.")

    return st.session_state.get("codex_thread_id")


def render_home() -> None:
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Paginas", "3")
    col_b.metric("Entradas", "YouTube + Torrent")
    col_c.metric("Orquestracao", "Skills + Codex")

    st.info(
        "Use o menu lateral do Streamlit para abrir `Chat`, `Downloads` e `Historico`. "
        "O app organiza audio do YouTube em `media/music` e torrents em `media/music` ou `media/movies`."
    )
