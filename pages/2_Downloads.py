from __future__ import annotations

import json

import streamlit as st

from media_manager.service import get_media_service
from torrent_manager.models import ACTIVE_STATUSES
from torrent_manager.ui import render_dashboard
from torrent_manager.utils import format_timestamp
from ui_shell import configure_page


configure_page("Downloads", "Acompanhe o status dos torrents e das extracoes de audio do YouTube.")

service = get_media_service()
service.sync_downloads()

with st.container(border=True):
    left, right = st.columns([1.2, 1.0])
    with left:
        st.subheader("Acoes rapidas")
        with st.form("downloads-manual-magnet-form", clear_on_submit=True):
            magnet_value = st.text_area(
                "Link magnet",
                placeholder="Cole um ou mais links magnet, um por linha.",
                height=120,
            )
            magnet_submitted = st.form_submit_button("Adicionar magnet", width="stretch")

        if magnet_submitted:
            magnets = [line.strip() for line in magnet_value.splitlines() if line.strip()]
            if not magnets:
                st.warning("Informe ao menos um link magnet.")
            else:
                added = 0
                for magnet in magnets:
                    service.add_torrent_from_magnet(
                        magnet,
                        api_key=st.session_state.get("gemini_api_key") or None,
                        model=st.session_state.get("gemini_model"),
                    )
                    added += 1
                st.success(f"{added} magnet(s) adicionados.")
                st.rerun()

    with right:
        st.subheader("Anexar .torrent")
        uploaded_files = st.file_uploader(
            "Arquivos .torrent",
            type=["torrent"],
            accept_multiple_files=True,
            key="downloads_torrent_uploader",
        )
        if st.button("Processar anexos", width="stretch"):
            files = uploaded_files or []
            if not files:
                st.warning("Selecione ao menos um arquivo .torrent.")
            else:
                for item in files:
                    service.add_torrent_file(
                        filename=item.name,
                        payload=item.getvalue(),
                        api_key=st.session_state.get("gemini_api_key") or None,
                        model=st.session_state.get("gemini_model"),
                    )
                st.success(f"{len(files)} arquivo(s) .torrent processado(s).")
                st.rerun()

downloads = service.list_downloads()
active = sum(item.status in ACTIVE_STATUSES or item.status in {"queued", "downloading"} for item in downloads)
waiting_info = sum(item.status == "needs_info" for item in downloads)
completed = sum(item.status in {"completed", "seeding"} or item.progress >= 1 for item in downloads)
errors = sum(item.status == "error" for item in downloads)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Ativos", active)
m2.metric("Aguardando info", waiting_info)
m3.metric("Concluidos", completed)
m4.metric("Erros", errors)

with st.container(border=True):
    cleanup_left, cleanup_right = st.columns([1.4, 0.8])
    cleanup_left.subheader("Limpeza")
    cleanup_left.caption("Remove a fila/historico local e para torrents ativos para encerrar seed.")
    confirm_cleanup = cleanup_right.checkbox("Confirmar limpeza", key="confirm_download_cleanup")
    if cleanup_right.button("Parar torrents e limpar historico", width="stretch", disabled=not confirm_cleanup):
        stopped = service.clear_download_history(stop_torrents=True)
        st.success(f"Historico limpo. {stopped} torrent(s) removido(s) do cliente.")
        st.rerun()

tabs = st.tabs(["Fila unificada", "Torrents em detalhe"])

with tabs[0]:
    if not downloads:
        st.info("Nenhum download registrado ainda.")
    for item in downloads:
        with st.container(border=True):
            top_left, top_right = st.columns([1.8, 1.0])
            top_left.markdown(f"### {item.display_name}")
            top_left.caption(
                f"Fonte: {item.source_kind} | Tipo: {item.media_type} | Atualizado: {format_timestamp(item.updated_at)}"
            )
            top_right.write(f"Status: `{item.status}`")
            top_right.write(f"Destino: `{item.target_path}`")
            confirm_delete = top_right.checkbox("Confirmar remocao", key=f"confirm-delete-{item.id}")
            delete_label = "Parar seed e remover" if item.source_kind == "torrent" else "Remover da lista"
            if top_right.button(delete_label, key=f"delete-download-{item.id}", width="stretch", disabled=not confirm_delete):
                service.delete_download(item.id, stop_torrent=True)
                st.success("Item removido.")
                st.rerun()
            st.progress(float(item.progress), text=f"{item.progress * 100:.1f}%")
            if item.status == "needs_info":
                st.info("Aguardando metadados no chat para iniciar este download.")
            if item.error_message:
                st.error(item.error_message)
            if item.status == "error" and item.source_kind in {"youtube", "youtube_playlist"}:
                if st.button("Tentar novamente", key=f"retry-{item.id}", width="stretch"):
                    service.retry_youtube_download(item.id)
                    st.rerun()
            if item.details_json and item.details_json != "{}":
                with st.expander("Detalhes"):
                    try:
                        st.json(json.loads(item.details_json))
                    except Exception:
                        st.code(item.details_json)

with tabs[1]:
    render_dashboard(service.torrent_service)
