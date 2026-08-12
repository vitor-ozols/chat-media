from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st


DEFAULT_MODEL = "Padrão do Codex"
EFFORT_CHOICES = ["low", "medium", "high", "xhigh"]
SANDBOX_CHOICES = ["read", "write", "full"]


def configure_app() -> None:
    st.set_page_config(
        page_title="Chat Media",
        page_icon="💬",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def configure_page(title: str, subtitle: str) -> None:
    inject_styles()
    render_hero(title, subtitle)


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            :root {
                --surface: #111820;
                --surface-raised: #17212b;
                --line: rgba(255, 255, 255, 0.09);
                --text: #edf2f7;
                --muted: #93a4b5;
                --accent: #45d4a3;
            }
            .stApp {
                background:
                    radial-gradient(circle at 75% -15%, rgba(69, 212, 163, 0.08), transparent 34rem),
                    #0b1016;
                color: var(--text);
            }
            html, body, [class*="css"] {
                font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
                    "Segoe UI", sans-serif;
            }
            [data-testid="stSidebar"] {
                background: #080d12;
                border-right: 1px solid var(--line);
            }
            [data-testid="stSidebar"] [data-testid="stButton"] button {
                text-align: left;
                justify-content: flex-start;
                min-height: 2.45rem;
            }
            [data-testid="stHeader"] { background: transparent; }
            .block-container {
                padding-top: 1.2rem;
                padding-bottom: 7rem;
            }
            h1, h2, h3 { letter-spacing: -0.025em; }
            .hero {
                display: flex;
                align-items: flex-end;
                justify-content: space-between;
                gap: 1rem;
                padding: 0.35rem 0 1rem;
                margin-bottom: 0.75rem;
                border-bottom: 1px solid var(--line);
            }
            .hero h1 {
                margin: 0;
                color: var(--text);
                font-size: clamp(1.65rem, 3vw, 2.25rem);
                font-weight: 680;
            }
            .hero p {
                margin: 0.3rem 0 0;
                color: var(--muted);
                max-width: 52rem;
                line-height: 1.5;
            }
            .chat-empty {
                max-width: 42rem;
                margin: 12vh auto 2rem;
                padding: 2rem;
                text-align: center;
                background: rgba(23, 33, 43, 0.72);
                border: 1px solid var(--line);
                border-radius: 22px;
            }
            .chat-empty .mark {
                display: grid;
                place-items: center;
                width: 3.2rem;
                height: 3.2rem;
                margin: 0 auto 1rem;
                border-radius: 16px;
                color: #07110d;
                background: var(--accent);
                font-weight: 800;
                font-size: 1.15rem;
            }
            .chat-empty h2 { margin: 0; font-size: 1.35rem; }
            .chat-empty p { margin: 0.6rem 0 0; color: var(--muted); }
            [data-testid="stChatMessage"] {
                max-width: 54rem;
                margin-inline: auto;
                padding: 1.05rem 1.15rem;
                border: 1px solid var(--line);
                border-radius: 18px;
                background: rgba(17, 24, 32, 0.72);
            }
            [data-testid="stBottomBlockContainer"] {
                background: linear-gradient(180deg, transparent, #0b1016 28%);
                padding-top: 2rem;
            }
            [data-testid="stChatInput"] {
                max-width: 54rem;
                margin-inline: auto;
                border-color: rgba(69, 212, 163, 0.35);
                border-radius: 18px;
                background: #111820;
                box-shadow: 0 14px 40px rgba(0, 0, 0, 0.32);
            }
            div[data-testid="stVerticalBlockBorderWrapper"],
            div[data-testid="stMetric"] {
                background: rgba(17, 24, 32, 0.82);
                border: 1px solid var(--line);
                border-radius: 18px;
                box-shadow: none;
            }
            div[data-testid="stMetric"] { padding: 0.75rem 1rem; }
            .muted { color: var(--muted); }
            .chip {
                display: inline-flex;
                align-items: center;
                padding: 0.25rem 0.6rem;
                border-radius: 999px;
                color: #b8f8df;
                background: rgba(69, 212, 163, 0.12);
                border: 1px solid rgba(69, 212, 163, 0.22);
                font-size: 0.76rem;
                font-weight: 700;
                letter-spacing: 0.035em;
                text-transform: uppercase;
            }
            .chip-error { color: #ffc4c4; background: rgba(248, 113, 113, 0.12); border-color: rgba(248, 113, 113, 0.22); }
            .chip-paused, .chip-removed { color: #cbd5e1; background: rgba(148, 163, 184, 0.12); border-color: rgba(148, 163, 184, 0.22); }
            @media (max-width: 700px) {
                .block-container { padding-inline: 1rem; }
                .hero { align-items: flex-start; flex-direction: column; }
                [data-testid="stChatMessage"] { padding: 0.8rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(title: str, subtitle: str) -> None:
    subtitle_html = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f'<div class="hero"><div><h1>{escape(title)}</h1>{subtitle_html}</div></div>',
        unsafe_allow_html=True,
    )


def selected_codex_model() -> str | None:
    selected = st.session_state.get("codex_model")
    return None if not selected or selected == DEFAULT_MODEL else str(selected)


def format_thread_date(raw: str) -> str:
    try:
        return datetime.fromtimestamp(int(raw)).strftime("%d/%m · %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def render_codex_sidebar(service) -> str | None:
    models = service.list_codex_models()
    model_choices = [DEFAULT_MODEL, *(item["id"] for item in models)]
    current_model = st.session_state.get("codex_model")
    if current_model and current_model not in model_choices:
        model_choices.append(str(current_model))

    st.session_state.setdefault("codex_model", DEFAULT_MODEL)
    st.session_state.setdefault("codex_effort", "medium")
    st.session_state.setdefault("codex_sandbox", "full")
    st.session_state.setdefault("codex_new_chat", False)
    st.session_state.setdefault("codex_thread_id", None)

    st.sidebar.markdown("### Codex")
    if st.sidebar.button(
        "＋  Novo chat",
        width="stretch",
        type="primary",
        disabled=st.session_state.get("codex_future") is not None,
    ):
        st.session_state["codex_thread_id"] = None
        st.session_state["codex_new_chat"] = True
        st.session_state["codex_section"] = "Chat"
        st.session_state.pop("codex_completed_reply", None)
        st.rerun()
    active_thread = st.session_state.get("codex_thread_id")
    if active_thread:
        st.sidebar.caption(f"Thread ativa · `{active_thread[:8]}…`")
    else:
        st.sidebar.caption("Novo chat pronto para começar")

    with st.sidebar.expander("Configurações", expanded=False):
        st.selectbox("Modelo", model_choices, key="codex_model")
        st.selectbox("Raciocínio", EFFORT_CHOICES, key="codex_effort")
        st.selectbox("Acesso ao sistema", SANDBOX_CHOICES, key="codex_sandbox")
        if service.codex_sdk.is_available():
            st.caption("Codex SDK disponível")
        else:
            st.error("Codex SDK não está instalado neste ambiente.")

    skills = service.list_codex_skills()
    with st.sidebar.expander(f"Skills locais · {len(skills)}", expanded=False):
        if skills:
            st.caption("O Codex pode ativá-las automaticamente. Para forçar uma, use `$nome-da-skill`.")
            st.markdown("\n".join(f"- `{item['name']}`" for item in skills[:30]))
            if len(skills) > 30:
                st.caption(f"e mais {len(skills) - 30}…")
        else:
            st.warning("Nenhuma skill foi encontrada no ambiente do app.")

    return st.session_state.get("codex_thread_id")
