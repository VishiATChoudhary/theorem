"""The WAL is bounded, so startup cost is the live data and not the history.

`snapshot()` existed but nothing called it. A long-lived graph therefore
replayed every write it had ever taken, and the WAL grew without limit.
Compaction now happens on a record count, and old runs are pruned.
"""

from theorem.engine.storage import Store


def put(store, name):
    nid = store.next_id("supplier")
    store.apply(
        {"op": "put_node", "id": nid, "cls": "supplier", "props": {"name": name}}
    )
    return nid


def test_the_wal_is_truncated_when_it_passes_the_threshold(tmp_path):
    store = Store(tmp_path, snapshot_every=10)
    for i in range(25):
        put(store, f"s{i}")
    assert list((tmp_path / "runs").glob("run-*.json"))
    assert store.wal_len() < 25  # the replay is now the tail, not the history
    assert len(store.nodes) == 25
    store.close()


def test_everything_survives_an_automatic_snapshot(tmp_path):
    store = Store(tmp_path, snapshot_every=10)
    names = [f"s{i}" for i in range(25)]
    for n in names:
        put(store, n)
    store.close()
    reopened = Store(tmp_path)
    assert sorted(n.props["name"] for n in reopened.nodes.values()) == sorted(names)
    reopened.close()


def test_bulk_writes_also_compact(tmp_path):
    store = Store(tmp_path, snapshot_every=10)
    store.bulk(
        [
            {
                "op": "put_node",
                "id": f"#s-{i}",
                "cls": "supplier",
                "props": {"name": f"s{i}"},
            }
            for i in range(1, 41)
        ]
    )
    assert store.wal_len() == 0
    store.close()
    assert len(Store(tmp_path, lock=False).nodes) == 40


def test_old_runs_are_pruned(tmp_path):
    """Keeping the previous run is the documented fallback for a torn one.
    Keeping all of them is a disk leak proportional to history."""
    store = Store(tmp_path, snapshot_every=5)
    for i in range(60):
        put(store, f"s{i}")
    runs = list((tmp_path / "runs").glob("run-*.json"))
    assert len(runs) <= 2, [r.name for r in runs]
    store.close()
    assert len(Store(tmp_path, lock=False).nodes) == 60


def test_compaction_is_off_by_default_for_small_stores(tmp_path):
    """The default threshold must not fire on a store of a few records,
    where a snapshot costs more than the replay it saves."""
    store = Store(tmp_path)
    for i in range(20):
        put(store, f"s{i}")
    assert store.wal_len() == 20
    store.close()


def test_a_snapshot_can_be_forced(tmp_path):
    store = Store(tmp_path)
    put(store, "VoltaChem")
    store.snapshot()
    assert store.wal_len() == 0
    store.close()


def test_snapshots_are_amortized_not_quadratic(tmp_path):
    """A fixed threshold would snapshot the whole store every N records,
    so loading a large graph would cost O(n^2/N). Each snapshot must cost
    no more than the WAL that triggered it."""
    store = Store(tmp_path, snapshot_every=10)
    written = []
    real = store.snapshot

    def counting_snapshot():
        written.append(len(store.nodes) + len(store.edge_index))
        return real()

    store.snapshot = counting_snapshot
    for i in range(2000):
        put(store, f"s{i}")
    assert sum(written) < 3 * 2000, written
    store.close()
