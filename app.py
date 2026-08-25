"""Ask my documents — upload a document set, then ask questions answered only from it.

    streamlit run app.py

The sidebar exposes the knobs that actually change behaviour (chunk size, overlap, top-k,
reranker, the two abstain thresholds) so the effect of each is visible live rather than
buried in a config file.
"""

from __future__ import annotations

import streamlit as st

from src.config import (
    CANDIDATE_K,
    DEFAULT_CHUNKING,
    DEFAULT_CORPUS,
    MIN_COSINE,
    MIN_RERANK_SCORE,
    TOP_K,
    UPLOAD_CORPUS,
    ChunkConfig,
    list_corpora,
)
from src import llm
from src.pipeline import ask, ingest, save_uploads
from src import store

st.set_page_config(page_title="Ask my documents", page_icon="📄", layout="wide")


@st.cache_resource(show_spinner="Loading embedding + reranker models…")
def warm_models():
    from src.embedder import get_embedder, get_reranker

    return get_embedder().dim, get_reranker().model_name


def sidebar() -> dict:
    st.sidebar.header("Documents")

    corpora = list_corpora()
    default_index = corpora.index(UPLOAD_CORPUS) if UPLOAD_CORPUS in corpora else 0
    corpus = st.sidebar.selectbox(
        "Corpus", corpora or [DEFAULT_CORPUS], index=default_index if corpora else 0,
        help="Upload your own set below, or use the bundled placeholder pack.",
    )

    st.sidebar.divider()
    st.sidebar.header("Chunking")
    strategy = st.sidebar.selectbox(
        "Strategy", ["recursive", "heading", "fixed"], index=0,
        help=(
            "recursive: split on natural boundaries, headings respected. "
            "heading: one chunk per clause. "
            "fixed: blind character windows — the naive baseline."
        ),
    )
    chunk_size = st.sidebar.select_slider(
        "Chunk size (characters)", options=[300, 500, 800, 1200, 1600, 2000],
        value=DEFAULT_CHUNKING.chunk_size,
    )
    overlap = st.sidebar.select_slider(
        "Overlap (characters)", options=[0, 60, 100, 150, 200, 300],
        value=DEFAULT_CHUNKING.overlap,
        help="Characters repeated between neighbours, so a fact spanning a boundary "
             "survives whole in at least one chunk.",
    )

    st.sidebar.divider()
    st.sidebar.header("Retrieval")
    top_k = st.sidebar.slider("Passages shown to the model (top-k)", 1, 10, TOP_K)
    candidate_k = st.sidebar.slider("Candidates from the vector store", 5, 50, CANDIDATE_K)
    use_reranker = st.sidebar.toggle(
        "Cross-encoder reranking", value=True,
        help="Rescore candidates with a model that reads query and passage together. "
             "Turn it off to see the bi-encoder's raw ordering.",
    )

    st.sidebar.divider()
    st.sidebar.header("Abstain thresholds")
    min_cosine = st.sidebar.slider("Min cosine similarity", 0.0, 1.0, MIN_COSINE, 0.01)
    min_rerank = st.sidebar.slider("Min rerank score", 0.0, 1.0, MIN_RERANK_SCORE, 0.01)
    st.sidebar.caption(
        "Unrelated text still scores ~0.5 cosine on this embedding model, so a 0.5 "
        "threshold would never refuse anything. The reranker is the decisive gate."
    )

    st.sidebar.divider()
    st.sidebar.header("Answer model")
    provider = st.sidebar.radio(
        "Provider", list(llm.PROVIDERS),
        index=list(llm.PROVIDERS).index(llm.provider_name())
        if llm.provider_name() in llm.PROVIDERS else 0,
        help="Only the final answer wording changes. Retrieval and the refusal gates are "
             "identical across providers — swapping provider cannot fix a wrong figure.",
    )
    provider_status = llm.status(provider)
    if provider_status.ready:
        st.sidebar.success(provider_status.detail)
    else:
        st.sidebar.warning(
            f"{provider_status.detail}\n\nFalling back to retrieval-only mode: the app "
            "quotes the winning passage instead of writing prose. Retrieval, citations "
            "and refusals all still work."
        )
    force_extractive = st.sidebar.toggle(
        "Force retrieval-only mode", value=not provider_status.ready
    )

    return {
        "corpus": corpus,
        "provider": provider,
        "cfg": ChunkConfig(strategy, chunk_size, overlap),
        "top_k": top_k,
        "candidate_k": candidate_k,
        "use_reranker": use_reranker,
        "min_cosine": min_cosine,
        "min_rerank": min_rerank,
        "force_extractive": force_extractive,
        "provider_ready": provider_status.ready,
    }


def upload_panel(opts: dict) -> None:
    st.subheader("1 · Add your documents")
    uploaded = st.file_uploader(
        "PDF, Markdown, HTML, or plain text",
        type=["pdf", "md", "markdown", "txt", "html", "htm"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    col_a, col_b = st.columns([1, 2])
    with col_a:
        replace = st.checkbox("Replace existing uploads", value=True)
    if uploaded:
        with col_b:
            st.caption(f"{len(uploaded)} file(s) ready · "
                       f"{sum(len(f.getvalue()) for f in uploaded) / 1024:,.0f} KB")

    if st.button("Ingest documents", type="primary", disabled=not uploaded):
        names = save_uploads(
            [(f.name, f.getvalue()) for f in uploaded], UPLOAD_CORPUS, replace=replace
        )
        if not names:
            st.error("None of those files had a supported extension.")
            return
        with st.spinner(f"Chunking and embedding {len(names)} document(s)…"):
            report = ingest(opts["cfg"], corpus_id=UPLOAD_CORPUS, verbose=False)
        st.session_state["last_ingest"] = report
        st.session_state["active_corpus"] = UPLOAD_CORPUS
        st.success(
            f"Indexed {report['documents']} document(s) into {report['chunks']} chunks."
        )
        st.rerun()


def ingest_report(report: dict) -> None:
    cols = st.columns(4)
    cols[0].metric("Documents", report["documents"])
    cols[1].metric("Chunks", report["chunks"])
    cols[2].metric("Median chunk", f"{report['chunk_chars_median']} ch")
    cols[3].metric("Vector dim", report["embedding_dim"])
    with st.expander("Files in this index"):
        st.dataframe(report["files"], use_container_width=True, hide_index=True)


def render_answer(result) -> None:
    if result.mode == "abstained":
        st.warning(result.text)
    elif result.mode in {"unverified"}:
        st.error(result.text)
    else:
        st.markdown(result.text)

    if result.citations:
        st.subheader("Sources")
        for c in result.citations:
            # `label` already carries "p.N" for PDF sources (see Hit.citation()).
            eff = f" · effective {c['effective_date']}" if c.get("effective_date") else ""
            with st.expander(
                f"[{c['n']}] {c['label']} — score {c['score']:.3f}", expanded=False
            ):
                st.caption(f"{c['document_id']}{eff}")
                st.markdown(f"> {c['snippet'].replace(chr(10), chr(10) + '> ')}")
                st.caption(c["relpath"])

    with st.expander(
        f"Retrieved passages ({len(result.hits)}) and diagnostics", expanded=False
    ):
        st.json(result.diagnostics, expanded=False)
        for i, hit in enumerate(result.hits, start=1):
            rr = f"{hit.rerank_score:.3f}" if hit.rerank_score is not None else "—"
            st.markdown(
                f"**[{i}] {hit.citation()}** · cosine `{hit.cosine:.3f}` · rerank `{rr}`"
            )
            st.text(hit.text[:900])
            st.divider()


def main() -> None:
    st.title("Ask my documents")
    st.caption(
        "Answers come only from the indexed documents, every claim carries a citation, "
        "and the app refuses rather than guessing when the documents don't cover the "
        "question."
    )

    opts = sidebar()
    warm_models()

    upload_panel(opts)
    if "last_ingest" in st.session_state:
        ingest_report(st.session_state["last_ingest"])

    st.divider()
    st.subheader("2 · Ask a question")

    corpus = opts["corpus"]
    if not store.collection_exists(opts["cfg"], corpus):
        st.info(
            f"No index yet for **{corpus}** at *{opts['cfg'].describe()}*. "
            "Upload documents above, or build this configuration now."
        )
        if st.button(f"Build index for {corpus}"):
            with st.spinner("Chunking and embedding…"):
                report = ingest(opts["cfg"], corpus_id=corpus, verbose=False)
            st.session_state["last_ingest"] = report
            st.rerun()
        return

    with st.form("ask", clear_on_submit=False):
        question = st.text_input(
            "Question", placeholder="What is the compulsory deductible for a car above 1500cc?"
        )
        c1, c2 = st.columns(2)
        doc_type = c1.text_input(
            "Filter by doc_type (optional)", placeholder="endorsement",
            help="Metadata filter applied before the vector search.",
        )
        effective_after = c2.text_input(
            "Only documents effective on/after (optional)", placeholder="2026-01-01"
        )
        submitted = st.form_submit_button("Ask", type="primary")

    if submitted and question.strip():
        with st.spinner("Retrieving and checking before answering…"):
            result = ask(
                question.strip(),
                cfg=opts["cfg"],
                corpus_id=corpus,
                top_k=opts["top_k"],
                candidate_k=opts["candidate_k"],
                use_reranker=opts["use_reranker"],
                doc_type=doc_type.strip() or None,
                effective_on_or_after=effective_after.strip() or None,
                min_cosine=opts["min_cosine"],
                min_rerank_score=opts["min_rerank"],
                provider=opts["provider"],
                force_extractive=opts["force_extractive"],
                surface="web",
            )
        render_answer(result)


if __name__ == "__main__":
    main()
