from __future__ import annotations

import streamlit as st

from media_manager.gemini import DEFAULT_MODEL, DOCUMENTED_CHAT_MODELS
from media_manager.service import get_media_service
from ui_shell import configure_page


configure_page(
    "Chat Media",
    "Converse com o agente para baixar audio do YouTube e organizar sua biblioteca.",
    sidebar_models=DOCUMENTED_CHAT_MODELS,
)

service = get_media_service()

top_left, top_right = st.columns([1.0, 0.24])
top_left.subheader("Conversa")
if top_right.button("Limpar chat", width="stretch"):
    service.clear_chat()
    st.rerun()

@st.fragment(run_every="2s")
def render_chat_history() -> None:
    messages = service.list_chat_messages()
    if not messages:
        with st.chat_message("assistant"):
            st.write(
                "Envie um link do YouTube para extrair audio, cole um magnet, "
                "ou abra a pagina de downloads para adicionar magnets e arquivos .torrent."
            )
        return

    for message in messages:
        with st.chat_message("assistant" if message["role"] == "assistant" else "user"):
            st.write(message["content"])


render_chat_history()

chat_value = st.chat_input(
    "Peça um download, cole um YouTube ou um magnet...",
    accept_file="multiple",
    file_type=["torrent"],
)
if chat_value:
    if isinstance(chat_value, str):
        prompt = chat_value
        uploaded_files = []
    else:
        prompt = chat_value.text or ""
        uploaded_files = list(chat_value.files or [])

    uploads = [(item.name, item.getvalue()) for item in uploaded_files]
    with st.chat_message("user"):
        if prompt:
            st.write(prompt)
        for item in uploaded_files:
            st.caption(f"Anexo: {item.name}")

    with st.chat_message("assistant"):
        with st.spinner("Processando sua solicitacao..."):
            reply = service.handle_chat_submission(
                prompt=prompt,
                uploaded_torrents=uploads,
                model=st.session_state.get("gemini_model", DEFAULT_MODEL),
                api_key=st.session_state.get("gemini_api_key") or None,
            )
        st.write(reply)
    st.rerun()
