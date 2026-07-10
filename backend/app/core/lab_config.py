"""
Lab configuration management.

Stores lab settings in lab_config.json.
Loaded on startup; editable via Lab Setup in the UI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app.core.models import (
    LabSettings, DocumentLibraryEntry, OptimisationLibraryEntry
)

_CONFIG_PATH = Path(os.getenv("LAB_CONFIG_PATH", "lab_config.json"))
_DOCS_DIR    = Path(os.getenv("LAB_DOCS_DIR", "lab_documents"))

_LAB_SETTINGS: Optional[LabSettings] = None


def _seed_optimisation_library(settings: LabSettings) -> None:
    if settings.optimisation_library:
        return
    settings.optimisation_library = [
        OptimisationLibraryEntry(
            name="scikit-optimize (GP-BO)",
            description=(
                "Gaussian Process Bayesian Optimisation with Expected Improvement. "
                "Suitable for low-dimensional continuous spaces with noisy observations. "
                "Already installed in MAESTRO."
            ),
            capabilities=["single-objective", "continuous", "noisy", "low-dimensional"],
            install_cmd="pip install scikit-optimize",
            docs_url="https://scikit-optimize.github.io/",
            enabled=True,
            is_default=True,
        ),
        OptimisationLibraryEntry(
            name="Random Search",
            description=(
                "Uniform random sampling. No surrogate model. "
                "Useful as a baseline or when the search space is poorly understood."
            ),
            capabilities=["single-objective", "continuous", "baseline"],
            install_cmd="",
            docs_url="",
            enabled=True,
            is_default=True,
        ),
        OptimisationLibraryEntry(
            name="Honegumi (Ax Platform)",
            description=(
                "Template generator for Bayesian optimisation built on Meta's Ax Platform. "
                "Supports multi-objective, multi-task, batch, categorical, and constrained "
                "optimisation. Best for complex materials science tasks."
            ),
            capabilities=[
                "multi-objective", "multi-task", "batch", "categorical",
                "constrained", "high-dimensional",
            ],
            install_cmd="pip install ax-platform honegumi",
            docs_url="https://honegumi.readthedocs.io/",
            enabled=True,
            is_default=False,
        ),
        OptimisationLibraryEntry(
            name="Optuna",
            description=(
                "Hyperparameter optimisation with TPE sampler. "
                "Good for mixed (continuous + categorical) spaces and pruning of bad trials."
            ),
            capabilities=["single-objective", "multi-objective", "categorical", "pruning"],
            install_cmd="pip install optuna",
            docs_url="https://optuna.org/",
            enabled=True,
            is_default=False,
        ),
        OptimisationLibraryEntry(
            name="DEAP (Evolutionary Algorithms)",
            description=(
                "Distributed Evolutionary Algorithms in Python. "
                "Supports genetic algorithms and evolution strategies. "
                "Good for combinatorial and discrete spaces."
            ),
            capabilities=["multi-objective", "discrete", "combinatorial", "evolutionary"],
            install_cmd="pip install deap",
            docs_url="https://deap.readthedocs.io/",
            enabled=True,
            is_default=False,
        ),
    ]


def load_lab_settings() -> LabSettings:
    global _LAB_SETTINGS
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            _LAB_SETTINGS = LabSettings(**data)
            if not _LAB_SETTINGS.optimisation_library:
                _seed_optimisation_library(_LAB_SETTINGS)
                save_lab_settings(_LAB_SETTINGS)
        except Exception as e:
            print(f"[WARN] Could not load lab_config.json: {e}. Using defaults.")
            _LAB_SETTINGS = LabSettings()
            _seed_optimisation_library(_LAB_SETTINGS)
    else:
        _LAB_SETTINGS = LabSettings()
        _seed_optimisation_library(_LAB_SETTINGS)
        save_lab_settings(_LAB_SETTINGS)
        print(f"[INFO] Created default lab_config.json at {_CONFIG_PATH}")
    return _LAB_SETTINGS


def get_lab_settings() -> LabSettings:
    global _LAB_SETTINGS
    if _LAB_SETTINGS is None:
        load_lab_settings()
    return _LAB_SETTINGS


def save_lab_settings(settings: LabSettings) -> None:
    global _LAB_SETTINGS
    _LAB_SETTINGS = settings
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings.model_dump(), f, indent=2)


def update_lab_settings(updates: dict) -> LabSettings:
    current = get_lab_settings()
    data    = current.model_dump()
    data.update(updates)
    updated = LabSettings(**data)
    save_lab_settings(updated)
    return updated


def ensure_docs_dir() -> None:
    _DOCS_DIR.mkdir(exist_ok=True)


def add_document_to_library(
    document_id: str,
    filename:    str,
    title:       Optional[str],
    summary:     Optional[str],
    uploaded_at: str,
    file_bytes:  bytes,
    doc_type:    str = "paper",
) -> DocumentLibraryEntry:
    ensure_docs_dir()
    file_path = _DOCS_DIR / f"{document_id}.pdf"
    with open(file_path, "wb") as f:
        f.write(file_bytes)
    entry = DocumentLibraryEntry(
        document_id=document_id,
        filename=filename,
        title=title,
        summary=summary,
        uploaded_at=uploaded_at,
        file_path=str(file_path),
        doc_type=doc_type,
    )
    settings = get_lab_settings()
    settings.document_library = [
        d for d in settings.document_library if d.document_id != document_id
    ]
    settings.document_library.append(entry)
    save_lab_settings(settings)
    return entry


def remove_document_from_library(document_id: str) -> bool:
    settings = get_lab_settings()
    original = len(settings.document_library)
    settings.document_library = [
        d for d in settings.document_library if d.document_id != document_id
    ]
    if len(settings.document_library) < original:
        save_lab_settings(settings)
        file_path = _DOCS_DIR / f"{document_id}.pdf"
        if file_path.exists():
            file_path.unlink()
        return True
    return False


def get_document_library() -> list[DocumentLibraryEntry]:
    return get_lab_settings().document_library


def load_library_documents_into_store() -> None:
    from app.core.documents import DOCUMENTS, create_document
    library = get_document_library()
    if not library:
        return
    loaded = 0
    for entry in library:
        if entry.document_id in DOCUMENTS:
            continue
        file_path = Path(entry.file_path)
        if not file_path.exists():
            print(f"[WARN] Library document not found on disk: {entry.filename}")
            continue
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            doc = create_document(entry.filename, file_bytes)
            DOCUMENTS.pop(doc.document_id, None)
            doc.document_id = entry.document_id
            DOCUMENTS[entry.document_id] = doc
            loaded += 1
        except Exception as e:
            print(f"[WARN] Could not reload library document {entry.filename}: {e}")
    if loaded:
        print(f"[INFO] Loaded {loaded} document(s) from library into memory")

    # Migrate resources and protocols from lab_config.json to SQLite if present
    _migrate_resources_and_protocols()


def _migrate_resources_and_protocols() -> None:
    """One-time migration of resources/protocols from lab_config.json to SQLite."""
    from app.core.database import get_all_resources, upsert_resource, get_all_protocols, upsert_protocol
    settings = get_lab_settings()

    # Migrate resources
    if hasattr(settings, "resource_inventory") and settings.resource_inventory:
        existing_ids = {r["resource_id"] for r in get_all_resources()}
        migrated = 0
        for r in settings.resource_inventory:
            if r.resource_id not in existing_ids:
                upsert_resource(r.model_dump())
                migrated += 1
        if migrated:
            print(f"[INFO] Migrated {migrated} resource(s) from lab_config.json to SQLite")

    # Migrate protocols
    if hasattr(settings, "protocols") and settings.protocols:
        existing_ids = {p["protocol_id"] for p in get_all_protocols()}
        migrated = 0
        for p in settings.protocols:
            if p.protocol_id not in existing_ids:
                upsert_protocol(p.model_dump())
                migrated += 1
        if migrated:
            print(f"[INFO] Migrated {migrated} protocol(s) from lab_config.json to SQLite")