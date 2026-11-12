"""Grounded LlamaIndex knowledge vault: ingest, chunk semantically, embed, persist locally,
retrieve with a relevance cut-off, and expose it to LangChain as a tool."""
import hashlib
import json
import statistics
from datetime import datetime, timezone

from langchain_core.tools import tool
from llama_index.core import (Settings, SimpleDirectoryReader, StorageContext, VectorStoreIndex,
                              load_index_from_storage)
from llama_index.core.node_parser import SemanticSplitterNodeParser, SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.embeddings.openai import OpenAIEmbedding

from . import config

SUPPORTED_EXTS = [".md", ".txt"]


def _configure_llamaindex() -> None:
    Settings.embed_model = OpenAIEmbedding(model=config.EMBED_MODEL)
    Settings.llm = None   # retrieval only: the LangChain agent writes the answer (one LLM, one bill)


def _fingerprint() -> str:
    """Hash of the manual's contents + chunking settings. A change triggers a rebuild."""
    h = hashlib.sha256()
    for path in sorted(config.KNOWLEDGE_DIR.iterdir()):
        if path.suffix in SUPPORTED_EXTS:
            h.update(path.name.encode())
            h.update(path.read_bytes())
    h.update(f"{config.EMBED_MODEL}|{config.BREAKPOINT_PERCENTILE}|{config.MIN_CHUNK_CHARS}|"
             f"{config.MAX_CHUNK_CHARS}".encode())
    return h.hexdigest()


def _merge_small(nodes):
    """Merge tiny fragments (e.g. a heading on its own) into the following chunk of the same file."""
    out = []
    for node in nodes:
        prev = out[-1] if out else None
        if (prev is not None and prev.metadata.get("file_name") == node.metadata.get("file_name")
                and len(prev.get_content()) < config.MIN_CHUNK_CHARS):
            prev.set_content(prev.get_content() + "\n" + node.get_content())
        else:
            out.append(node)
    return out


def _cap_size(nodes):
    """Re-split any semantic chunk that is too long to be a precise citation."""
    splitter = SentenceSplitter(chunk_size=config.FALLBACK_CHUNK_TOKENS, chunk_overlap=config.FALLBACK_CHUNK_OVERLAP)
    out = []
    for node in nodes:
        text = node.get_content()
        if len(text) <= config.MAX_CHUNK_CHARS:
            out.append(node)
            continue
        for part in splitter.split_text(text):
            out.append(TextNode(text=part, metadata=dict(node.metadata),
                                excluded_embed_metadata_keys=list(node.excluded_embed_metadata_keys),
                                excluded_llm_metadata_keys=list(node.excluded_llm_metadata_keys)))
    return out


def build_index(force: bool = False):
    """Load the persisted index if the manual is unchanged, otherwise rebuild and persist it."""
    _configure_llamaindex()
    manifest_path = config.STORAGE_DIR / "manifest.json"
    fingerprint = _fingerprint()
    if not force and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("fingerprint") == fingerprint:
            ctx = StorageContext.from_defaults(persist_dir=str(config.STORAGE_DIR))
            return load_index_from_storage(ctx), manifest

    docs = SimpleDirectoryReader(input_dir=str(config.KNOWLEDGE_DIR), required_exts=SUPPORTED_EXTS).load_data()
    if not docs:
        raise RuntimeError(f"No documents found in {config.KNOWLEDGE_DIR}")
    splitter = SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=config.BREAKPOINT_PERCENTILE,
                                          embed_model=Settings.embed_model)
    nodes = splitter.get_nodes_from_documents(docs)
    nodes = [n for n in _cap_size(_merge_small(nodes)) if n.get_content().strip()]

    index = VectorStoreIndex(nodes)
    index.storage_context.persist(persist_dir=str(config.STORAGE_DIR))
    lengths = [len(n.get_content()) for n in nodes]
    manifest = {"fingerprint": fingerprint, "documents": len(docs), "chunks": len(nodes),
                "avg_chunk_chars": round(statistics.mean(lengths)), "min_chunk_chars": min(lengths),
                "max_chunk_chars": max(lengths), "embed_model": config.EMBED_MODEL,
                "built_at": datetime.now(timezone.utc).isoformat()}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return index, manifest


def source_tag(result) -> str:
    return f"[source: {result.node.metadata.get('file_name', 'unknown')}#{result.node.node_id[:8]}]"


class KnowledgeVault:
    def __init__(self, force_rebuild: bool = False):
        self.index, self.manifest = build_index(force_rebuild)
        self.retriever = self.index.as_retriever(similarity_top_k=config.TOP_K)

    def search(self, query: str):
        """Return (results above the relevance cut-off, all raw results)."""
        results = self.retriever.retrieve(query)
        kept = [r for r in results if r.score is not None and r.score >= config.SIMILARITY_CUTOFF]
        return kept, results


def make_knowledge_tool(vault: KnowledgeVault):
    """Wrap the LlamaIndex retriever as a LangChain tool."""

    @tool
    def search_knowledge_vault(query: str) -> str:
        """Search the AfyaPlus knowledge manual: cover plans and limits, coverage percentages, exclusions,
        claims and pre-authorisation rules, the clinical routing protocol and the data protection policy.
        Call this for ANY question about AfyaPlus policy, cover, claims, routing or compliance.

        Args:
            query: A short, specific search phrase, e.g. "Silver plan outpatient coverage percentage".

        Returns:
            Numbered excerpts, each starting with a [source: file#id] tag to cite, or NO_RELEVANT_CONTEXT
            when nothing in the manual is relevant enough to answer from.
        """
        if not query or not query.strip():
            return "RETRIEVAL_ERROR: the query was empty."
        try:
            kept, _ = vault.search(query.strip())
        except Exception as exc:   # embedding/network failure must not crash the agent loop
            return f"RETRIEVAL_ERROR: {type(exc).__name__}: {exc}"
        if not kept:
            return (f"NO_RELEVANT_CONTEXT: no part of the knowledge manual scored above the relevance "
                    f"threshold ({config.SIMILARITY_CUTOFF}). Do not answer from general knowledge.")
        return "\n\n".join(f"{source_tag(r)} (relevance {r.score:.2f})\n{r.node.get_content().strip()}" for r in kept)

    return search_knowledge_vault