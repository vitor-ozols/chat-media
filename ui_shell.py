from __future__ import annotations

import os

import streamlit as st

from media_manager.gemini import DEFAULT_MODEL, DOCUMENTED_CHAT_MODELS


def configure_page(
    title: str,
    subtitle: str,
    sidebar_models: list[str] | None = None,
    sidebar_label: str = "Modelo",
) -> None:
    st.set_page_config(
        page_title=title,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_styles()
    render_sidebar_model_picker(sidebar_models, sidebar_label)
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


def render_sidebar_model_picker(models: list[str] | None = None, label: str = "Modelo") -> None:
    st.sidebar.header("Gemini")
    st.session_state["gemini_api_key"] = os.getenv("GEMINI_API_KEY", "")
    if st.session_state["gemini_api_key"]:
        st.sidebar.caption("Usando `GEMINI_API_KEY` do ambiente.")
    else:
        st.sidebar.warning("`GEMINI_API_KEY` nao encontrada no ambiente.")

    choices = models or DOCUMENTED_CHAT_MODELS or [DEFAULT_MODEL]
    current = st.session_state.get("gemini_model", DEFAULT_MODEL)
    if current not in choices:
        current = DEFAULT_MODEL
    st.session_state["gemini_model"] = st.sidebar.selectbox(
        label,
        choices,
        index=choices.index(current),
        help="Lista baseada na documentacao oficial e usada como fallback quando a API nao puder listar modelos em tempo real.",
    )
    st.sidebar.caption("Modelos de chat/texto documentados pelo Gemini API.")


def render_home() -> None:
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Paginas", "3")
    col_b.metric("Entradas", "YouTube + Torrent")
    col_c.metric("IA", st.session_state.get("gemini_model", DEFAULT_MODEL))

    st.info(
        "Use o menu lateral do Streamlit para abrir `Chat`, `Downloads` e `Historico`. "
        "O app organiza audio do YouTube em `media/music` e torrents em `media/music` ou `media/movies`."
    )
