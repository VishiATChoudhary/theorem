"""One writer per store directory, enforced rather than assumed.

Before this, two `Store` objects on one path both allocated `#s-1`, both
wrote it, and after a reopen one of the two nodes was gone. No error was
raised at any point. Silent loss is the worst failure a store can have,
so the second opener is now refused.
"""

import subprocess
import sys

import pytest

from theorem.engine.storage import Store, StoreLocked


def put(store, name):
    nid = store.next_id("supplier")
    store.apply(
        {"op": "put_node", "id": nid, "cls": "supplier", "props": {"name": name}}
    )
    return nid


def test_second_opener_is_refused(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(StoreLocked) as e:
        Store(tmp_path)
    assert str(tmp_path) in str(e.value)
    store.close()


def test_the_refusal_names_the_holder(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(StoreLocked) as e:
        Store(tmp_path)
    assert str(store._pid) in str(e.value)  # so an operator can find it
    store.close()


def test_the_lost_write_now_raises(tmp_path):
    """The exact sequence that used to lose a node."""
    a = Store(tmp_path)
    put(a, "VoltaChem")
    with pytest.raises(StoreLocked):
        b = Store(tmp_path)
        put(b, "Ionix")
    a.close()
    reopened = Store(tmp_path)
    assert len(reopened.nodes) == 1
    reopened.close()


def test_close_releases(tmp_path):
    a = Store(tmp_path)
    put(a, "VoltaChem")
    a.close()
    b = Store(tmp_path)
    assert len(b.nodes) == 1
    b.close()


def test_close_is_idempotent(tmp_path):
    store = Store(tmp_path)
    store.close()
    store.close()


def test_context_manager_releases(tmp_path):
    with Store(tmp_path) as store:
        put(store, "VoltaChem")
    with Store(tmp_path) as store:
        assert len(store.nodes) == 1


def test_a_reader_can_opt_out(tmp_path):
    """`lock=False` is for tools that only read an idle directory."""
    store = Store(tmp_path)
    put(store, "VoltaChem")
    reader = Store(tmp_path, lock=False)
    assert len(reader.nodes) == 1
    store.close()


def test_a_second_process_is_refused(tmp_path):
    """The lock is held against other processes, not merely other objects."""
    store = Store(tmp_path)
    put(store, "VoltaChem")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from theorem.engine.storage import Store, StoreLocked\n"
            "try:\n"
            "    Store(sys.argv[1])\n"
            "except StoreLocked:\n"
            "    print('refused')\n",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "refused", probe.stderr
    store.close()


def test_the_lock_survives_a_dead_holder(tmp_path):
    """A crashed process must not leave the directory permanently locked."""
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys; from theorem.engine.storage import Store\n"
            "s = Store(sys.argv[1])\n"
            "nid = s.next_id('supplier')\n"
            "s.apply({'op':'put_node','id':nid,'cls':'supplier','props':{'name':'X'}})\n"
            "os._exit(9)\n",  # no unwinding, no close: a hard crash
            str(tmp_path),
        ],
    )
    assert crashed.returncode == 9
    store = Store(tmp_path)  # the OS dropped the dead process's lock
    assert len(store.nodes) == 1  # and the write it committed is still there
    store.close()
