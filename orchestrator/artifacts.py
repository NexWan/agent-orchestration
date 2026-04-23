from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class ArtifactType(Enum):
    PRODUCT_BRIEF = "product_brief"
    ARCHITECTURE = "architecture"
    BACKEND_SOURCE = "backend_source"
    FRONTEND_SOURCE = "frontend_source"
    TEST_SUITE = "test_suite"
    QA_REPORT = "qa_report"
    DOCKER_ASSETS = "docker_assets"
    VALIDATION_REPORT = "validation_report"


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    artifact_type: str
    producer: str
    path: str
    created_at: str


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "artifacts.json"
        self._records: dict[str, ArtifactRecord] = {}
        self._load()

    def register_file(
        self,
        artifact_type: ArtifactType,
        producer: str,
        path: str | Path,
    ) -> ArtifactRecord:
        file_path = Path(path).resolve()
        artifact_id = f"{artifact_type.value}:{producer}:{file_path}"
        record = ArtifactRecord(
            artifact_id=artifact_id,
            artifact_type=artifact_type.value,
            producer=producer,
            path=str(file_path),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[artifact_id] = record
        self._save()
        return record

    def register_tree(
        self,
        artifact_type: ArtifactType,
        producer: str,
        root: str | Path,
    ) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        root_path = Path(root)
        if not root_path.exists():
            return records
        for path in sorted(root_path.rglob("*")):
            if path.is_file():
                records.append(self.register_file(artifact_type, producer, path))
        return records

    def list_records(self) -> list[ArtifactRecord]:
        return list(self._records.values())

    def find_by_type(self, artifact_type: ArtifactType) -> list[ArtifactRecord]:
        return [
            record
            for record in self._records.values()
            if record.artifact_type == artifact_type.value
        ]

    def export_for_prompt(self, artifact_types: list[ArtifactType] | None = None) -> list[dict[str, str]]:
        records = self.list_records()
        if artifact_types is not None:
            allowed = {artifact_type.value for artifact_type in artifact_types}
            records = [record for record in records if record.artifact_type in allowed]
        return [asdict(record) for record in records]

    def _load(self) -> None:
        if not self.manifest_path.exists():
            return
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        for item in payload:
            record = ArtifactRecord(**item)
            self._records[record.artifact_id] = record

    def _save(self) -> None:
        payload = [asdict(record) for record in self._records.values()]
        self.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
