import json

import numpy as np
import pytest

from eal import storage
from eal.sources.faulty import BiasedSource, PrngSource
from eal.sources.os_source import OsSource
from eal.sources.qpu_sim import QpuSim


@pytest.mark.parametrize("n", [1, 7, 8, 1001, 4097, 100_000])
def test_round_trip(tmp_path, n):
    b = OsSource().read(n)
    path = storage.save_batch(b, "s1", tmp_path)
    back = storage.load_batch(path)
    assert np.array_equal(back.bits, b.bits) and back.n_bits == n
    assert back.batch_hash == b.batch_hash
    for f in ("batch_id", "source_id", "source_type", "source_version",
              "is_local", "is_simulated", "created_at", "params"):
        assert getattr(back, f) == getattr(b, f)


def test_file_name_pattern_and_no_overwrite(tmp_path):
    src = PrngSource()
    p1 = storage.save_batch(src.read(1000), "s1", tmp_path)
    p2 = storage.save_batch(src.read(1000), "s1", tmp_path)
    p3 = storage.save_batch(src.read(1000), "s2", tmp_path)
    day = p1.name[:10]
    assert p1.name == f"{day}_faulty_prng_s1_001.npy"
    assert p2.name == f"{day}_faulty_prng_s1_002.npy"
    assert p3.name == f"{day}_faulty_prng_s2_001.npy"
    assert p1.with_suffix(".json").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_packed_is_eight_times_smaller(tmp_path):
    p = storage.save_batch(OsSource().read(80_000), "s1", tmp_path)
    assert np.load(p).size == 10_000


def test_json_has_no_bits_and_has_hash(tmp_path):
    b = BiasedSource().read(5000)
    meta = json.loads(storage.save_batch(b, "s1", tmp_path).with_suffix(".json").read_text())
    assert "bits" not in meta
    assert meta["batch_hash"] == b.batch_hash and meta["n_bits"] == 5000
    assert meta["params"]["p"] == 0.55


def test_tampered_bits_rejected(tmp_path):
    p = storage.save_batch(OsSource().read(4096), "s1", tmp_path)
    packed = np.load(p)
    packed[0] ^= 1  # troca um bit
    np.save(p, packed, allow_pickle=False)
    with pytest.raises(ValueError, match="batch_hash"):
        storage.load_batch(p)


def test_tampered_n_bits_rejected(tmp_path):
    p = storage.save_batch(OsSource().read(4096), "s1", tmp_path)
    meta_path = p.with_suffix(".json")
    meta = json.loads(meta_path.read_text())
    meta["n_bits"] = 4000
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="tamanho"):
        storage.load_batch(p)


def test_missing_json_is_incomplete(tmp_path):
    p = storage.save_batch(OsSource().read(100), "s1", tmp_path)
    p.with_suffix(".json").unlink()
    with pytest.raises(FileNotFoundError):
        storage.load_batch(p)


@pytest.mark.parametrize("bad", ["", "s 1", "s_1", "../x", "s/1"])
def test_invalid_session(tmp_path, bad):
    with pytest.raises(ValueError):
        storage.save_batch(OsSource().read(8), bad, tmp_path)


def test_qpu_sim_params_survive(tmp_path):
    b = QpuSim(n_qubits=4, seed=1).read(400)
    back = storage.load_batch(storage.save_batch(b, "s1", tmp_path))
    assert back.params == b.params
    assert back.params["bit_order"].startswith("shot-major")


def test_numpy_values_in_params_are_converted(tmp_path):
    b = BiasedSource().read(64)
    object.__setattr__(b, "params", {"k": np.int64(3), "x": np.float64(0.5)})
    meta = json.loads(storage.save_batch(b, "s1", tmp_path).with_suffix(".json").read_text())
    assert meta["params"] == {"k": 3, "x": 0.5}
