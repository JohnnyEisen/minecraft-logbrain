from pathlib import Path

from brain_system.core import BrainCore


def test_signature_required_rejects_without_public_keys(tmp_path: Path):
    dlcs = tmp_path / "dlcs"
    dlcs.mkdir()

    dlc_file = dlcs / "x.py"
    dlc_file.write_text("class X: pass\n", encoding="utf-8")

    brain = BrainCore(config_path=None)
    brain._config_raw["dlc_signature_required"] = True
    brain._config_raw["dlc_public_key_pem_files"] = []

    loaded = brain.load_dlc_file(str(dlc_file))
    assert loaded == 0
