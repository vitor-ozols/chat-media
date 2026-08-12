from __future__ import annotations

from pathlib import Path

import streamlit as st

from .config import ensure_app_paths
from .models import ACTIVE_STATUSES, TorrentRecord, TorrentStatus
from .service import TorrentService
from .utils import format_bytes, format_eta, format_rate, format_timestamp, status_css_class, status_label


DOWNLOAD_DESTINATIONS = {
    "Músicas": "/mnt/sata/musics",
    "Séries": "/mnt/sata/series",
    "Filmes": "/mnt/sata/movies",
}


@st.cache_resource(show_spinner=False)
def get_service() -> TorrentService:
    return TorrentService(ensure_app_paths(Path.cwd()))


def compute_metrics(records: list[TorrentRecord]) -> dict[str, int]:
    active = sum(record.status in ACTIVE_STATUSES for record in records)
    completed = sum(record.progress >= 1 for record in records if record.status != TorrentStatus.REMOVED)
    errors = sum(record.status == TorrentStatus.ERROR for record in records)
    total_download_rate = sum(record.download_rate for record in records)
    total_upload_rate = sum(record.upload_rate for record in records)
    total_downloaded = sum(record.downloaded for record in records)
    total_uploaded = sum(record.uploaded for record in records)
    return {
        "active": active,
        "completed": completed,
        "errors": errors,
        "total_download_rate": total_download_rate,
        "total_upload_rate": total_upload_rate,
        "total_downloaded": total_downloaded,
        "total_uploaded": total_uploaded,
    }


def render_sidebar(service: TorrentService) -> None:
    engine = service.get_engine_snapshot()
    st.sidebar.markdown("### Cliente BitTorrent")
    if engine.available:
        st.sidebar.success(engine.message)
    else:
        st.sidebar.error(engine.message)

    st.sidebar.caption("Pasta padrao")
    st.sidebar.code(service.get_default_download_dir())

    st.sidebar.divider()
    st.sidebar.caption("Sessao BitTorrent")
    st.sidebar.write(f"DHT nodes: `{engine.dht_nodes}`")
    st.sidebar.write(f"Peers conectados: `{engine.peers}`")
    st.sidebar.write(f"Download: `{format_rate(engine.download_rate)}`")
    st.sidebar.write(f"Upload: `{format_rate(engine.upload_rate)}`")
    st.sidebar.write(f"Conexao entrante: `{'sim' if engine.has_incoming_connections else 'nao'}`")
    if st.sidebar.button("Atualizar tela", width="stretch"):
        st.rerun()


def render_add_form(service: TorrentService) -> None:
    default_dir = service.get_default_download_dir()
    destination_paths = list(DOWNLOAD_DESTINATIONS.values())
    selected_index = destination_paths.index(default_dir) if default_dir in destination_paths else 2
    with st.form("add-torrent-form", clear_on_submit=False):
        left, right = st.columns([1.6, 1.0])
        with left:
            magnets_raw = st.text_area(
                "Links magnet",
                placeholder="Cole um link por linha, ex.: magnet:?xt=urn:btih:...",
                height=150,
            )
            uploaded_files = st.file_uploader(
                "Arquivos .torrent",
                type=["torrent"],
                accept_multiple_files=True,
            )
        with right:
            download_dir = st.selectbox(
                "Destino final",
                options=destination_paths,
                index=selected_index,
                format_func=lambda path: next(
                    label for label, destination in DOWNLOAD_DESTINATIONS.items() if destination == path
                ),
            )
            st.caption(download_dir)
            start_paused = st.checkbox("Adicionar pausado", value=False)
            submit = st.form_submit_button("Adicionar downloads", width="stretch")

    if not submit:
        return

    magnets = [line.strip() for line in magnets_raw.splitlines() if line.strip()]
    files = uploaded_files or []
    if not magnets and not files:
        st.warning("Informe ao menos um magnet ou arquivo .torrent.")
        return

    selected_dir = service.set_default_download_dir(download_dir)
    added = 0
    failed = 0

    if magnets:
        records = service.add_magnets(magnets, download_dir=selected_dir, start_paused=start_paused)
        added += sum(record.status != TorrentStatus.ERROR for record in records)
        failed += sum(record.status == TorrentStatus.ERROR for record in records)

    for file in files:
        record = service.add_torrent_file(
            filename=file.name,
            payload=file.getvalue(),
            download_dir=selected_dir,
            start_paused=start_paused,
        )
        if record.status == TorrentStatus.ERROR:
            failed += 1
        else:
            added += 1

    if added:
        st.success(f"{added} download(s) adicionados.")
    if failed:
        st.error(f"{failed} item(ns) falharam ao entrar no cliente.")
    st.rerun()


def render_torrent_card(service: TorrentService, record: TorrentRecord) -> None:
    status_html = (
        f"<span class='chip {status_css_class(record.status)}'>"
        f"{status_label(record.status)}</span>"
    )
    with st.container(border=True):
        st.markdown(status_html, unsafe_allow_html=True)
        st.markdown(f"### {record.name}")
        st.markdown(
            f"<p class='muted'>Atualizado em {format_timestamp(record.updated_at)}</p>",
            unsafe_allow_html=True,
        )

        st.progress(record.progress, text=f"{record.progress * 100:.1f}%")

        info_a, info_b, info_c, info_d = st.columns(4)
        info_a.markdown(f"<p><strong>Tamanho:</strong> {format_bytes(record.total_size)}</p>", unsafe_allow_html=True)
        info_a.markdown(f"<p><strong>ETA:</strong> {format_eta(record.eta_seconds)}</p>", unsafe_allow_html=True)
        info_b.markdown(f"<p><strong>Download:</strong> {format_rate(record.download_rate)}</p>", unsafe_allow_html=True)
        info_b.markdown(f"<p><strong>Upload:</strong> {format_rate(record.upload_rate)}</p>", unsafe_allow_html=True)
        info_c.markdown(f"<p><strong>Peers:</strong> {record.peers}</p>", unsafe_allow_html=True)
        info_c.markdown(f"<p><strong>Seeds:</strong> {record.seeds}</p>", unsafe_allow_html=True)
        info_d.markdown(f"<p><strong>Ratio:</strong> {record.ratio:.2f}</p>", unsafe_allow_html=True)
        info_d.markdown(f"<p><strong>Arquivos:</strong> {record.file_count}</p>", unsafe_allow_html=True)

        st.caption(f"Destino: {record.download_dir}")
        if record.info_hash:
            st.caption(f"Info hash: {record.info_hash}")
        if record.error_message:
            st.error(record.error_message)

        button_cols = st.columns([1, 1, 1, 1, 1.25])
        if record.status in {TorrentStatus.PAUSED, TorrentStatus.COMPLETED, TorrentStatus.ERROR}:
            if button_cols[0].button("Retomar", key=f"resume-{record.id}", width="stretch"):
                service.resume_torrent(record.id)
                st.rerun()
        else:
            if button_cols[0].button("Pausar", key=f"pause-{record.id}", width="stretch"):
                service.pause_torrent(record.id)
                st.rerun()

        if button_cols[1].button("Revalidar", key=f"check-{record.id}", width="stretch"):
            service.force_recheck(record.id)
            st.rerun()
        if button_cols[2].button("Reiniciar", key=f"restart-{record.id}", width="stretch"):
            service.restart_torrent(record.id)
            st.rerun()
        if button_cols[3].button("Remover", key=f"remove-{record.id}", width="stretch"):
            service.remove_torrent(record.id, delete_files=False)
            st.rerun()
        with button_cols[4].popover("Excluir dados", width="stretch"):
            st.warning("Isso remove o torrent e os arquivos baixados.")
            if st.button("Confirmar exclusão", key=f"delete-{record.id}", type="primary"):
                service.remove_torrent(record.id, delete_files=True)
                st.rerun()

        if st.toggle("Mostrar arquivos", key=f"files-{record.id}"):
            file_rows = service.list_files(record.id)
            if file_rows:
                st.dataframe(
                    [
                        {
                            "Arquivo": row.path,
                            "Tamanho": format_bytes(row.size),
                            "Baixado": format_bytes(row.downloaded),
                            "Progresso": f"{row.progress * 100:.1f}%",
                        }
                        for row in file_rows
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("Arquivos ainda indisponiveis. Isso e comum enquanto os metadados nao chegaram.")

        if st.toggle("Mostrar eventos", key=f"events-{record.id}"):
            events = service.list_events(limit=20, torrent_id=record.id)
            if events:
                st.dataframe(
                    [
                        {
                            "Quando": format_timestamp(event.created_at),
                            "Nivel": event.level,
                            "Mensagem": event.message,
                        }
                        for event in events
                    ],
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info("Sem eventos para este torrent ainda.")


@st.fragment(run_every="2s")
def render_dashboard(service: TorrentService) -> None:
    all_records = service.list_torrents(include_removed=True)
    metrics = compute_metrics(all_records)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ativos", metrics["active"])
    m2.metric("Concluidos", metrics["completed"])
    m3.metric("Erros", metrics["errors"])
    m4.metric("Taxa total", format_rate(metrics["total_download_rate"]))

    filters = st.columns([1.2, 1.0, 1.0])
    search = filters[0].text_input("Buscar", value=st.session_state.get("torrent_search_filter", ""), key="torrent_search_filter")
    status_filter = filters[1].selectbox(
        "Status",
        ["Todos", "Ativos", "Concluidos", "Pausados", "Erro", "Removidos"],
        index=0,
        key="torrent_status_filter",
    )
    show_removed = filters[2].toggle("Incluir removidos", value=False, key="torrent_show_removed")

    records = all_records if show_removed else [record for record in all_records if record.status != TorrentStatus.REMOVED]
    if search:
        needle = search.lower()
        records = [record for record in records if needle in record.name.lower()]

    if status_filter == "Ativos":
        records = [record for record in records if record.status in ACTIVE_STATUSES]
    elif status_filter == "Concluidos":
        records = [record for record in records if record.status == TorrentStatus.COMPLETED or record.progress >= 1]
    elif status_filter == "Pausados":
        records = [record for record in records if record.status == TorrentStatus.PAUSED]
    elif status_filter == "Erro":
        records = [record for record in records if record.status == TorrentStatus.ERROR]
    elif status_filter == "Removidos":
        records = [record for record in records if record.status == TorrentStatus.REMOVED]

    if not records:
        st.info("Nenhum torrent corresponde aos filtros atuais.")
        return

    for record in records:
        render_torrent_card(service, record)


@st.fragment(run_every="5s")
def render_history(service: TorrentService) -> None:
    events = service.list_events(limit=80)
    if not events:
        st.info("Nenhum evento registrado ainda.")
        return
    st.dataframe(
        [
            {
                "Quando": format_timestamp(event.created_at),
                "Torrent": event.torrent_name or "-",
                "Nivel": event.level,
                "Mensagem": event.message,
            }
            for event in events
        ],
        width="stretch",
        hide_index=True,
    )


def render_page(service: TorrentService | None = None) -> None:
    service = service or get_service()
    render_sidebar(service)

    with st.expander("Adicionar torrent", expanded=False, icon=":material/add_circle:"):
        render_add_form(service)

    tabs = st.tabs(["Downloads", "Atividade"])
    with tabs[0]:
        render_dashboard(service)
    with tabs[1]:
        render_history(service)


def render_download_dir_controls(service: TorrentService) -> None:
    current_dir = service.get_default_download_dir()
    st.subheader("Destino de Download")
    st.caption("Defina aqui a pasta padrao dos novos torrents. Caminhos relativos partem da raiz do app.")
    with st.form("download-dir-form"):
        cols = st.columns([1.8, 0.8, 0.8])
        download_dir = cols[0].text_input("Pasta de destino", value=current_dir)
        use_default = cols[1].form_submit_button("Usar ./downloads", width="stretch")
        save_settings = cols[2].form_submit_button("Salvar destino", width="stretch")

    if use_default:
        resolved = service.set_default_download_dir("downloads")
        st.success(f"Destino atualizado para {resolved}")
        st.rerun()

    if save_settings:
        resolved = service.set_default_download_dir(download_dir)
        st.success(f"Destino atualizado para {resolved}")
        st.rerun()
