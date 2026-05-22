"""
ChromaDB Vector Memory Store — HTTP client implementation.
Connects to the ChromaDB server (Docker) via REST API.
No native C++ compilation needed.
"""
from __future__ import annotations
from typing import Any

import httpx
import structlog

from config import settings

log = structlog.get_logger()

_BASE: str = ""


def _base() -> str:
    global _BASE
    if not _BASE:
        _BASE = f"http://{settings.CHROMA_HOST}:{settings.CHROMA_PORT}/api/v1"
    return _BASE


def _collection_name(application_id: str, kind: str) -> str:
    return f"{settings.CHROMA_COLLECTION_PREFIX}_{application_id[:8]}_{kind}"


class ChromaMemoryStore:
    """
    Semantic vector memory for QAptain.
    Each application gets dedicated collections per knowledge type.
    """

    def _get_or_create_collection(self, name: str) -> str | None:
        """Return collection ID, creating if needed. Returns None if ChromaDB unreachable."""
        base = _base()
        try:
            # Try to get existing collection
            r = httpx.get(f"{base}/collections/{name}", timeout=5)
            if r.status_code == 200:
                return r.json()["id"]

            # Create if not found
            if r.status_code == 404:
                r2 = httpx.post(f"{base}/collections", json={
                    "name": name,
                    "metadata": {"hnsw:space": "cosine"},
                    "get_or_create": True,
                }, timeout=5)
                if r2.status_code in (200, 201):
                    return r2.json()["id"]
        except Exception as e:
            log.warning("ChromaDB unavailable", error=str(e))
        return None

    def _count(self, collection_id: str) -> int:
        try:
            r = httpx.get(f"{_base()}/collections/{collection_id}/count", timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return 0

    def store_module_knowledge(
        self,
        application_id: str,
        module_id: str,
        module_name: str,
        description: str,
        tags: list[str],
        pages: list[dict],
        workflows: list[dict],
    ) -> str:
        collection_id = self._get_or_create_collection(_collection_name(application_id, "modules"))
        if not collection_id:
            return f"module_{module_id}"

        content = self._build_module_document(module_name, description, tags, pages, workflows)
        doc_id = f"module_{module_id}"
        try:
            httpx.post(f"{_base()}/collections/{collection_id}/upsert", json={
                "ids": [doc_id],
                "documents": [content],
                "metadatas": [{"module_id": module_id, "module_name": module_name,
                               "application_id": application_id, "tags": ",".join(tags)}],
            }, timeout=10)
        except Exception as e:
            log.warning("ChromaDB upsert failed", error=str(e))
        return doc_id

    def store_workflow_knowledge(
        self,
        application_id: str,
        workflow_id: str,
        workflow_name: str,
        description: str,
        workflow_type: str,
        stages: list[dict],
    ) -> str:
        collection_id = self._get_or_create_collection(_collection_name(application_id, "workflows"))
        if not collection_id:
            return f"workflow_{workflow_id}"

        content = f"Workflow: {workflow_name}\nType: {workflow_type}\nDescription: {description}\nStages:\n"
        for i, stage in enumerate(stages, 1):
            content += f"  {i}. {stage.get('name', stage.get('description', ''))}\n"

        doc_id = f"workflow_{workflow_id}"
        try:
            httpx.post(f"{_base()}/collections/{collection_id}/upsert", json={
                "ids": [doc_id],
                "documents": [content],
                "metadatas": [{"workflow_id": workflow_id, "workflow_name": workflow_name,
                               "workflow_type": workflow_type, "application_id": application_id}],
            }, timeout=10)
        except Exception as e:
            log.warning("ChromaDB upsert failed", error=str(e))
        return doc_id

    def store_selector_memory(
        self,
        application_id: str,
        element_id: str,
        semantic_label: str,
        successful_selector: str,
        selector_type: str,
        confidence: float,
    ) -> str:
        collection_id = self._get_or_create_collection(_collection_name(application_id, "selectors"))
        if not collection_id:
            return f"selector_{element_id}"

        content = f"Element: {semantic_label}\nSuccessful selector ({selector_type}): {successful_selector}"
        doc_id = f"selector_{element_id}"
        try:
            httpx.post(f"{_base()}/collections/{collection_id}/upsert", json={
                "ids": [doc_id],
                "documents": [content],
                "metadatas": [{"element_id": element_id, "semantic_label": semantic_label,
                               "selector": successful_selector, "selector_type": selector_type,
                               "confidence": str(confidence)}],
            }, timeout=10)
        except Exception as e:
            log.warning("ChromaDB upsert failed", error=str(e))
        return doc_id

    def store_execution_learning(
        self,
        application_id: str,
        run_id: str,
        scenario_title: str,
        outcome: str,
        key_learnings: str,
    ) -> str:
        collection_id = self._get_or_create_collection(_collection_name(application_id, "learnings"))
        if not collection_id:
            return f"learning_{run_id}"

        content = f"Scenario: {scenario_title}\nOutcome: {outcome}\nLearnings:\n{key_learnings}"
        doc_id = f"learning_{run_id}"
        try:
            httpx.post(f"{_base()}/collections/{collection_id}/upsert", json={
                "ids": [doc_id],
                "documents": [content],
                "metadatas": [{"run_id": run_id, "scenario": scenario_title,
                               "outcome": outcome, "application_id": application_id}],
            }, timeout=10)
        except Exception as e:
            log.warning("ChromaDB upsert failed", error=str(e))
        return doc_id

    def query_module_context(
        self,
        application_id: str,
        query: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        try:
            collection_id = self._get_or_create_collection(_collection_name(application_id, "modules"))
            if not collection_id or self._count(collection_id) == 0:
                return []
            r = httpx.post(f"{_base()}/collections/{collection_id}/query", json={
                "query_texts": [query],
                "n_results": min(n_results, self._count(collection_id)),
            }, timeout=15)
            if r.status_code == 200:
                return self._format_results(r.json())
        except Exception as e:
            log.warning("ChromaDB query failed", error=str(e))
        return []

    def query_relevant_selectors(
        self,
        application_id: str,
        semantic_label: str,
        n_results: int = 3,
    ) -> list[dict[str, Any]]:
        try:
            collection_id = self._get_or_create_collection(_collection_name(application_id, "selectors"))
            if not collection_id or self._count(collection_id) == 0:
                return []
            r = httpx.post(f"{_base()}/collections/{collection_id}/query", json={
                "query_texts": [semantic_label],
                "n_results": min(n_results, self._count(collection_id)),
            }, timeout=15)
            if r.status_code == 200:
                return self._format_results(r.json())
        except Exception as e:
            log.warning("Selector query failed", error=str(e))
        return []

    def query_workflow_context(
        self,
        application_id: str,
        scenario_title: str,
        n_results: int = 3,
    ) -> list[dict[str, Any]]:
        try:
            collection_id = self._get_or_create_collection(_collection_name(application_id, "workflows"))
            if not collection_id or self._count(collection_id) == 0:
                return []
            r = httpx.post(f"{_base()}/collections/{collection_id}/query", json={
                "query_texts": [scenario_title],
                "n_results": min(n_results, self._count(collection_id)),
            }, timeout=15)
            if r.status_code == 200:
                return self._format_results(r.json())
        except Exception as e:
            log.warning("Workflow query failed", error=str(e))
        return []

    def delete_application_memory(self, application_id: str) -> None:
        for kind in ["modules", "workflows", "selectors", "learnings"]:
            try:
                name = _collection_name(application_id, kind)
                r = httpx.get(f"{_base()}/collections/{name}", timeout=5)
                if r.status_code == 200:
                    cid = r.json()["id"]
                    httpx.delete(f"{_base()}/collections/{cid}", timeout=5)
            except Exception:
                pass

    def _build_module_document(
        self,
        name: str,
        description: str,
        tags: list[str],
        pages: list[dict],
        workflows: list[dict],
    ) -> str:
        doc = f"Module: {name}\nDescription: {description or 'No description'}\n"
        if tags:
            doc += f"Tags: {', '.join(tags)}\n"
        if pages:
            doc += "Pages:\n"
            for p in pages[:10]:
                doc += f"  - {p.get('title', '')} ({p.get('page_type', '')})\n"
        if workflows:
            doc += "Workflows:\n"
            for w in workflows[:10]:
                doc += f"  - {w.get('name', '')} ({w.get('workflow_type', '')})\n"
        return doc

    def _format_results(self, results: dict) -> list[dict]:
        formatted = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, distances):
            formatted.append({
                "content": doc,
                "metadata": meta,
                "relevance": max(0.0, 1.0 - (dist or 0)),
            })
        return formatted


_store: ChromaMemoryStore | None = None


def get_memory_store() -> ChromaMemoryStore:
    global _store
    if _store is None:
        _store = ChromaMemoryStore()
    return _store
