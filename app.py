from __future__ import annotations

from pathlib import Path

import streamlit as st

from media_manager.service import get_media_service
from ui_shell import configure_page, render_codex_sidebar


configure_page(
    "Codex",
    "",
)

service = get_media_service()
thread_id = render_codex_sidebar(service)

st.subheader("Codex")

def render_chat_history() -> None:
    messages = service.list_codex_messages(
        thread_id=thread_id,
        model=st.session_state.get("codex_model"),
        sandbox=st.session_state.get("codex_sandbox", "full"),
    )
    for message in messages:
        with st.chat_message("assistant" if message["role"] == "assistant" else "user"):
            st.write(_strip_artifact_marker(message["content"]))
            artifact = message.get("artifact")
            if artifact:
                _render_download_artifact(artifact)


def _strip_artifact_marker(content: str) -> str:
    return content.split("<!-- chat-media-artifact", 1)[0].strip()


def _render_download_artifact(artifact: dict[str, str]) -> None:
    path = Path(artifact["path"])
    if not path.is_file():
        st.warning("Arquivo de download nao encontrado no disco.")
        return
    st.download_button(
        artifact.get("label") or "Baixar arquivo",
        data=path.read_bytes(),
        file_name=artifact.get("filename") or path.name,
        mime=artifact.get("mime") or "application/octet-stream",
        width="stretch",
        key=f"download-artifact-{path}",
    )


render_chat_history()

chat_value = st.chat_input(
    "Mensagem",
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
        with st.status("Executando", expanded=True) as status_box:
            for step in service.preview_activity(
                prompt=prompt,
                uploaded_torrents=uploads,
                model=st.session_state.get("codex_model"),
                effort=st.session_state.get("codex_effort", "medium"),
                sandbox=st.session_state.get("codex_sandbox", "full"),
                current_thread_id=st.session_state.get("codex_thread_id"),
            ):
                status_box.write(step)
            reply = service.handle_chat_submission(
                prompt=prompt,
                uploaded_torrents=uploads,
                current_thread_id=st.session_state.get("codex_thread_id"),
                model=st.session_state.get("codex_model"),
                effort=st.session_state.get("codex_effort", "medium"),
                sandbox=st.session_state.get("codex_sandbox", "full"),
            )
            if reply.get("thread_id") and reply.get("thread_id") != st.session_state.get("codex_thread_id"):
                status_box.write(f"Thread ativa: `{reply['thread_id']}`")
            status_box.write("Resposta concluida.")
            status_box.update(label="Concluido", state="complete", expanded=False)
        st.session_state["codex_thread_id"] = reply.get("thread_id")
        st.session_state["codex_new_chat"] = False
        if reply.get("model"):
            st.session_state["codex_model"] = reply["model"]
        if reply.get("effort"):
            st.session_state["codex_effort"] = reply["effort"]
        if reply.get("sandbox"):
            st.session_state["codex_sandbox"] = reply["sandbox"]
        st.write(_strip_artifact_marker(str(reply.get("reply") or "")))
    st.rerun()
