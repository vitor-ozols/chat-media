from __future__ import annotations

import streamlit as st

from media_manager.service import get_media_service
from torrent_manager.utils import format_timestamp
from ui_shell import configure_page


configure_page("Historico", "Consulte tudo o que ja foi solicitado ao agente e os arquivos baixados.")

service = get_media_service()
downloads = service.list_downloads()
messages = service.list_chat_messages()

left, right = st.columns([1.3, 1.0])

with left:
    st.subheader("Arquivos baixados")
    if downloads:
        st.dataframe(
            [
                {
                    "Nome": item.display_name,
                    "Fonte": item.source_kind,
                    "Tipo": item.media_type,
                    "Status": item.status,
                    "Destino": item.target_path,
                    "Criado em": format_timestamp(item.created_at),
                    "Concluido em": format_timestamp(item.completed_at),
                }
                for item in downloads
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("Ainda nao ha downloads registrados.")

with right:
    st.subheader("Historico do chat")
    if messages:
        for item in messages:
            with st.container(border=True):
                st.caption(f"{item['role']} | modelo: {item.get('model') or '-'}")
                st.write(item["content"])
    else:
        st.info("Ainda nao ha mensagens gravadas.")
