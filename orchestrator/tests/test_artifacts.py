from orchestrator.artifacts import ArtifactStore, ArtifactType


def test_artifact_store_registers_file_and_tree(tmp_path):
    store = ArtifactStore(tmp_path / ".orchestrator")
    one = tmp_path / "ARCHITECTURE.md"
    one.write_text("# Architecture", encoding="utf-8")

    src_dir = tmp_path / "backend"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')", encoding="utf-8")

    store.register_file(ArtifactType.ARCHITECTURE, "architect", one)
    store.register_tree(ArtifactType.BACKEND_SOURCE, "backend", src_dir)

    architecture_records = store.find_by_type(ArtifactType.ARCHITECTURE)
    backend_records = store.find_by_type(ArtifactType.BACKEND_SOURCE)

    assert len(architecture_records) == 1
    assert architecture_records[0].producer == "architect"
    assert len(backend_records) == 1
    assert backend_records[0].path.endswith("app.py")


def test_artifact_store_persists_manifest(tmp_path):
    root = tmp_path / ".orchestrator"
    store = ArtifactStore(root)
    file_path = tmp_path / "PRODUCT_BRIEF.md"
    file_path.write_text("brief", encoding="utf-8")
    store.register_file(ArtifactType.PRODUCT_BRIEF, "orchestrator", file_path)

    reloaded = ArtifactStore(root)

    assert len(reloaded.find_by_type(ArtifactType.PRODUCT_BRIEF)) == 1
