from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

import streamlit as st

from api_server import ensure_api_server
from media_manager.service import get_media_service
from ui_shell import (
    configure_app,
    configure_page,
    format_thread_date,
    render_codex_sidebar,
    selected_codex_model,
)


@st.cache_resource(show_spinner=False)
def _chat_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=2, thread_name_prefix="codex-chat")


def _strip_artifact_marker(content: str) -> str:
    return content.split("<!-- chat-media-artifact", 1)[0].strip()


def _apply_reply(reply: dict) -> None:
    st.session_state["codex_thread_id"] = reply.get("thread_id")
    st.session_state["codex_new_chat"] = False
    for key in ("model", "effort", "sandbox"):
        if reply.get(key):
            st.session_state[f"codex_{key}"] = reply[key]


def _render_messages(service, thread_id: str | None) -> list[dict[str, str]]:
    messages = service.list_codex_messages(
        thread_id=thread_id,
        model=selected_codex_model(),
        sandbox=st.session_state.get("codex_sandbox", "full"),
    )
    for message in messages:
        role = "assistant" if message["role"] == "assistant" else "user"
        with st.chat_message(role):
            st.markdown(_strip_artifact_marker(message["content"]))
    return messages


@st.fragment(run_every=1)
def _render_pending_reply() -> None:
    future: Future | None = st.session_state.get("codex_future")
    if future is None:
        return
    if not future.done():
        with st.chat_message("assistant"):
            st.status("Codex está trabalhando…", state="running", expanded=False)
        return
    try:
        reply = future.result()
    except Exception as exc:
        reply = {
            "reply": f"Falha ao processar a mensagem: {exc}",
            "thread_id": st.session_state.get("codex_thread_id"),
        }
    _apply_reply(reply)
    st.session_state["codex_completed_reply"] = str(reply.get("reply") or "")
    st.session_state.pop("codex_future", None)
    st.session_state.pop("codex_pending_prompt", None)
    st.rerun()


def _render_chat_tab(service) -> None:
    active_thread = st.session_state.get("codex_thread_id")
    messages = _render_messages(service, active_thread)
    if active_thread and not messages:
        error = service.codex_error("messages")
        if error:
            st.error(f"Não foi possível abrir esta conversa: {error}")

    completed_reply = st.session_state.pop("codex_completed_reply", None)
    if completed_reply and not any(
        message["role"] == "assistant" and message["content"] == completed_reply
        for message in messages[-1:]
    ):
        with st.chat_message("assistant"):
            st.markdown(_strip_artifact_marker(completed_reply))

    pending_prompt = st.session_state.get("codex_pending_prompt")
    if pending_prompt:
        with st.chat_message("user"):
            st.markdown(pending_prompt)

    if not messages and not pending_prompt and not completed_reply:
        st.markdown(
            """
            <div class="chat-empty">
                <div class="mark">C</div>
                <h2>O que vamos fazer?</h2>
                <p>Converse normalmente ou mencione uma skill com <code>$nome-da-skill</code>.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    _render_pending_reply()

    chat_value = st.chat_input(
        "Mensagem para o Codex",
        disabled=st.session_state.get("codex_future") is not None,
    )
    if chat_value:
        options = {
            "prompt": chat_value,
            "uploaded_torrents": [],
            "current_thread_id": active_thread,
            "model": selected_codex_model(),
            "effort": st.session_state.get("codex_effort", "medium"),
            "sandbox": st.session_state.get("codex_sandbox", "full"),
        }
        st.session_state["codex_pending_prompt"] = chat_value
        st.session_state["codex_future"] = _chat_executor().submit(
            service.handle_chat_submission, **options
        )
        st.rerun()


def _render_history_tab(service) -> None:
    threads = service.list_codex_threads(limit=100, model=selected_codex_model())
    error = service.codex_error("threads")
    if error:
        st.error(f"Não foi possível carregar o histórico: {error}")
        return
    if not threads:
        st.info("Nenhuma conversa do Codex encontrada.")
        return

    query = st.text_input(
        "Buscar no histórico",
        placeholder="Busque pelo título ou pelo início da conversa",
        key="codex_history_search",
    ).strip().lower()
    shown = [
        item
        for item in threads
        if not query
        or query in item["name"].lower()
        or query in item.get("preview", "").lower()
    ]
    if not shown:
        st.info("Nenhuma conversa corresponde à busca.")
        return

    selected_id = st.session_state.get("codex_history_thread_id")
    if selected_id not in {item["id"] for item in shown}:
        selected_id = shown[0]["id"]
        st.session_state["codex_history_thread_id"] = selected_id

    list_column, detail_column = st.columns([0.9, 2.1], gap="large")
    with list_column:
        st.caption(f"{len(shown)} conversa(s)")
        for item in shown[:50]:
            selected = item["id"] == selected_id
            if st.button(
                item["name"],
                key=f"history-{item['id']}",
                width="stretch",
                type="primary" if selected else "secondary",
            ):
                st.session_state["codex_history_thread_id"] = item["id"]
                st.rerun()
            date = format_thread_date(item.get("updated_at", ""))
            if selected and date:
                st.caption(date)

    selected = next(item for item in shown if item["id"] == selected_id)
    with detail_column:
        header, action = st.columns([1.7, 0.8], vertical_alignment="center")
        header.subheader(selected["name"])
        if action.button(
            "Continuar no Chat",
            key=f"continue-{selected_id}",
            type="primary",
            width="stretch",
        ):
            st.session_state["codex_thread_id"] = selected_id
            st.session_state["codex_new_chat"] = False
            st.session_state["codex_section"] = "Chat"
            st.session_state.pop("codex_completed_reply", None)
            st.rerun()
        date = format_thread_date(selected.get("updated_at", ""))
        if date:
            st.caption(f"Atualizada em {date} · `{selected_id}`")
        messages = _render_messages(service, selected_id)
        message_error = service.codex_error("messages")
        if message_error:
            st.error(f"Não foi possível abrir esta conversa: {message_error}")
        elif not messages:
            st.info("Essa conversa ainda não possui mensagens persistidas.")


def render_chat_page() -> None:
    configure_page(
        "Codex",
        "Converse com o agente ou consulte suas conversas anteriores.",
    )
    service = get_media_service()
    ensure_api_server(service)
    render_codex_sidebar(service)

    st.session_state.setdefault("codex_section", "Chat")
    section = st.segmented_control(
        "Seção",
        ["Chat", "Histórico"],
        key="codex_section",
        label_visibility="collapsed",
    )
    st.divider()
    if section == "Histórico":
        _render_history_tab(service)
    else:
        _render_chat_tab(service)


configure_app()
navigation = st.navigation(
    [
        st.Page(
            render_chat_page,
            title="Chat",
            icon=":material/chat_bubble:",
            url_path="chat",
            default=True,
        ),
        st.Page(
            "pages/2_Downloads.py",
            title="Torrents",
            icon=":material/download:",
            url_path="torrents",
        ),
    ],
    position="sidebar",
)
navigation.run()
