from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from app.core.models import (
    DocumentLibraryEntry,
    LabSettings,
    OptimisationLibraryEntry,
)

_CONFIG_PATH = Path(os.getenv("LAB_CONFIG_PATH", "lab_config.json"))
_DOCS_DIR    = Path(os.getenv("LAB_DOCS_DIR", "lab_documents"))

_LAB_SETTINGS: Optional[LabSettings] = None

_DEFAULT_OPTIMISATION_LIBRARY = [
    OptimisationLibraryEntry(
        name="scikit-optimize (GP-BO)",
        description=(
            "Gaussian Process Bayesian Optimisation with Expected Improvement. "
            "Suitable for low-dimensional continuous spaces with noisy observations."
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
            "Supports multi-objective, multi-task, batch, categorical, and constrained optimisation."
        ),
        capabilities=["multi-objective", "multi-task", "batch", "categorical", "constrained", "high-dimensional"],
        install_cmd="pip install ax-platform honegumi",
        docs_url="https://honegumi.readthedocs.io/",
        enabled=True,
        is_default=False,
    ),
    OptimisationLibraryEntry(
        name="Optuna (TPE)",
        description=(
            "Hyperparameter optimisation with Tree-structured Parzen Estimator. "
            "Good for mixed continuous/categorical spaces and pruning of bad trials."
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
        except Exception as e:
            print(f"[WARN] Could not load lab_config.json: {e}. Using defaults.")
            _LAB_SETTINGS = LabSettings()

    if _LAB_SETTINGS is None:
        _LAB_SETTINGS = LabSettings()

    if not _LAB_SETTINGS.optimisation_library:
        _LAB_SETTINGS.optimisation_library = list(_DEFAULT_OPTIMISATION_LIBRARY)
        save_lab_settings(_LAB_SETTINGS)
        if not _CONFIG_PATH.exists():
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
    data = get_lab_settings().model_dump()
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
    file_path.write_bytes(file_bytes)

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
    original_count = len(settings.document_library)
    settings.document_library = [
        d for d in settings.document_library if d.document_id != document_id
    ]
    if len(settings.document_library) < original_count:
        save_lab_settings(settings)
        file_path = _DOCS_DIR / f"{document_id}.pdf"
        if file_path.exists():
            file_path.unlink()
        return True
    return False


def get_document_library() -> list[DocumentLibraryEntry]:
    return get_lab_settings().document_library


_mineru_load_warned = False


def load_library_documents_into_store() -> None:
    global _mineru_load_warned
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
            doc = create_document(
                entry.filename,
                file_path.read_bytes(),
                document_id=entry.document_id,
            )
            if doc.document_id != entry.document_id:
                DOCUMENTS.pop(doc.document_id, None)
                doc.document_id = entry.document_id
                DOCUMENTS[entry.document_id] = doc
            loaded += 1
        except RuntimeError as e:
            if "MinerU" in str(e) and not _mineru_load_warned:
                print("[WARN] MinerU not installed — skipping document pre-loading. Install with: pip install mineru[core]")
                _mineru_load_warned = True
        except Exception as e:
            print(f"[WARN] Could not reload library document {entry.filename}: {e}")

    if loaded:
        print(f"[INFO] Loaded {loaded} document(s) from library into memory")

    _migrate_resources_and_protocols()


def _migrate_resources_and_protocols() -> None:
    from app.core.database import (
        get_all_protocols, get_all_resources,
        upsert_protocol, upsert_resource,
    )
    settings = get_lab_settings()

    if settings.resource_inventory:
        existing_ids = {r["resource_id"] for r in get_all_resources()}
        to_migrate   = [r for r in settings.resource_inventory if r.resource_id not in existing_ids]
        for r in to_migrate:
            upsert_resource(r.model_dump())
        if to_migrate:
            print(f"[INFO] Migrated {len(to_migrate)} resource(s) to SQLite")

    if settings.protocols:
        existing_ids = {p["protocol_id"] for p in get_all_protocols()}
        to_migrate   = [p for p in settings.protocols if p.protocol_id not in existing_ids]
        for p in to_migrate:
            upsert_protocol(p.model_dump())
        if to_migrate:
            print(f"[INFO] Migrated {len(to_migrate)} protocol(s) to SQLite")