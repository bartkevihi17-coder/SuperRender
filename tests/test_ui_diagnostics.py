import hashlib
import json
import zipfile

from app.ui_diagnostics import helper_diagnostics, export_logs


def test_helper_hash_and_error(tmp_path):
    helper = tmp_path / "SuperRenderFrameGen.exe"
    helper.write_bytes(b"fake-test-binary")
    telemetry = tmp_path / "telemetry.json"
    telemetry.write_text(json.dumps({"status": "error", "message": "test error"}))
    record = helper_diagnostics(helper, telemetry)
    assert record["sha256"] == hashlib.sha256(b"fake-test-binary").hexdigest()
    assert record["last_error"] == "test error"


def test_export_logs_only_approved_types(tmp_path):
    source = tmp_path / "logs"
    source.mkdir()
    (source / "run.log").write_text("ok")
    (source / "secret.exe").write_bytes(b"binary")
    destination = tmp_path / "logs.zip"
    assert export_logs(destination, source) == 1
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == ["run.log"]
