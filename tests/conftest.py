import pytest

from theorem.engine.storage import Store
from theorem.schema import Schema


@pytest.fixture
def schema():
    return Schema.supply_chain()


def _node(store, cls, **props):
    nid = store.next_id(cls)
    store.apply({"op": "put_node", "id": nid, "cls": cls, "props": props})
    return nid


def _edge(store, etype, **roles):
    store.apply(
        {"op": "put_edge", "id": store.next_id("edge"), "type": etype, "roles": roles}
    )


@pytest.fixture
def fixture_store(tmp_path):
    """Supply-chain fixture. Two distinct suppliers both named "Ionix".

    products: PowerBank Pro (2025), SolarCharger X (2023), GridPack (2026)
    parts: lithium cell (4.2), copper wire (1.1), solar film (7.5), casing (2.0)
    suppliers: VoltaChem/DE, Ionix/KR, Ionix/JP
    """
    store = Store(tmp_path / "db")
    pb = _node(store, "product", name="PowerBank Pro", launch_year=2025)
    sc = _node(store, "product", name="SolarCharger X", launch_year=2023)
    gp = _node(store, "product", name="GridPack", launch_year=2026)
    cell = _node(store, "part", name="lithium cell", unit_cost=4.2)
    wire = _node(store, "part", name="copper wire", unit_cost=1.1)
    film = _node(store, "part", name="solar film", unit_cost=7.5)
    casing = _node(store, "part", name="casing", unit_cost=2.0)
    volta = _node(store, "supplier", name="VoltaChem", country="DE")
    ionix_kr = _node(store, "supplier", name="Ionix", country="KR")
    ionix_jp = _node(store, "supplier", name="Ionix", country="JP")

    _edge(store, "uses", whole=pb, component=cell)
    _edge(store, "uses", whole=pb, component=wire)
    _edge(store, "uses", whole=sc, component=film)
    _edge(store, "uses", whole=gp, component=cell)
    _edge(store, "uses", whole=gp, component=casing)

    _edge(store, "supplied_by", item=cell, source=volta)
    _edge(store, "supplied_by", item=cell, source=ionix_kr)
    _edge(store, "supplied_by", item=wire, source=ionix_kr)
    _edge(store, "supplied_by", item=casing, source=ionix_jp)
    _edge(store, "supplied_by", item=film, source=volta)

    store.ids = dict(
        pb=pb,
        sc=sc,
        gp=gp,
        cell=cell,
        wire=wire,
        film=film,
        casing=casing,
        volta=volta,
        ionix_kr=ionix_kr,
        ionix_jp=ionix_jp,
    )
    return store
