"""A calibration must not silently score a draw made with different inputs."""

import argparse
import copy
import json

import pytest

from experiments.day import gen_calibrate as calibration
from test_gen_inventory import params


def job(tmp_path):
    return params(), 71, 2., str(tmp_path / "seed71.csv")


def test_identical_cached_draw_is_verified_without_regeneration(tmp_path, monkeypatch):
    task = job(tmp_path)
    out = tmp_path / "seed71.csv"
    assert calibration._gen(task) == str(out)
    original = out.read_bytes()
    def unexpected(*args, **kwargs):
        raise AssertionError("matching cache regenerated")
    monkeypatch.setattr(calibration.tape_gen, "generate", unexpected)
    assert calibration._gen(task) == str(out)
    assert out.read_bytes() == original
    manifest = json.loads(calibration._provenance_path(out).read_text())
    assert manifest["sha256"] == calibration._file_digest(out)
    assert manifest["identity"]["seed"] == 71


@pytest.mark.parametrize("field", ["params", "seed", "seconds"])
def test_changed_draw_inputs_are_rejected_without_overwriting(tmp_path, field):
    task = job(tmp_path)
    calibration._gen(task)
    out = tmp_path / "seed71.csv"
    original = out.read_bytes()
    changed = list(copy.deepcopy(task))
    if field == "params":
        changed[0]["latent"]["impact_traded"] = True
    elif field == "seed":
        changed[1] += 1
    else:
        changed[2] += 1
    with pytest.raises(ValueError, match="cached draw parameters"):
        calibration._gen(changed)
    assert out.read_bytes() == original


def test_legacy_and_modified_tapes_are_not_reused(tmp_path):
    task = job(tmp_path)
    out = tmp_path / "seed71.csv"
    out.write_text("unverified legacy draw\n")
    with pytest.raises(ValueError, match="no provenance"):
        calibration._gen(task)
    out.unlink()
    calibration._gen(task)
    raw = out.read_bytes()
    out.write_bytes(raw.replace(b"Insert", b"INsert", 1))  # unchanged length still fails the checksum
    with pytest.raises(ValueError, match="content does not match"):
        calibration._gen(task)


def test_failed_generation_does_not_publish_partial_tape(tmp_path, monkeypatch):
    def fail(params, seed, seconds, out, latent):
        out.write_text("partial\n")
        raise RuntimeError("interrupted")
    monkeypatch.setattr(calibration.tape_gen, "generate", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        calibration._gen(job(tmp_path))
    assert not (tmp_path / "seed71.csv").exists()
    assert not list(tmp_path.iterdir())


def test_latent_addition_verifies_same_tape_then_reuses_both(tmp_path, monkeypatch):
    task = job(tmp_path)
    calibration._gen(task)
    out, lat = tmp_path / "seed71.csv", tmp_path / "seed71_latent.csv"
    original = out.read_bytes()
    assert calibration._gen_latent(task) == str(lat)
    assert out.read_bytes() == original and lat.exists()
    def unexpected(*args, **kwargs):
        raise AssertionError("matching latent cache regenerated")
    monkeypatch.setattr(calibration.tape_gen, "generate", unexpected)
    assert calibration._gen_latent(task) == str(lat)


def test_failed_latent_verification_keeps_previous_outputs(tmp_path, monkeypatch):
    task = job(tmp_path)
    calibration._gen(task)
    out, lat = tmp_path / "seed71.csv", tmp_path / "seed71_latent.csv"
    original = out.read_bytes()
    lat.write_text("previous latent\n")
    def bad(params, seed, seconds, path, latent):
        path.write_text("different draw\n")
        latent.write_text("different latent\n")
    monkeypatch.setattr(calibration.tape_gen, "generate", bad)
    with pytest.raises(RuntimeError, match="regeneration.*differs"):
        calibration._gen_latent(task)
    assert out.read_bytes() == original and lat.read_text() == "previous latent\n"


def test_write_refuses_mixed_directory_before_changing_its_description(tmp_path):
    model = tmp_path / "base.json"
    model.write_text(json.dumps(params()))
    directory = tmp_path / "draws"
    directory.mkdir()
    (directory / "params.json").write_text("{}\n")
    readme = directory / "README.txt"
    readme.write_text("original description\n")
    args = argparse.Namespace(params=model, opts=None, dir=directory, seeds="71", seconds=2.,
                              latent_seeds="", jobs=1)
    with pytest.raises(ValueError, match="params.json differs"):
        calibration.cmd_write(args)
    assert readme.read_text() == "original description\n"
