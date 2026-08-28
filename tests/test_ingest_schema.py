from theorem.schema import Schema


def test_every_schema_has_ingestion_builtins():
    s = Schema()
    for cls in ("entity", "piece", "document", "chunk", "media"):
        assert cls in s.classes
    assert s.classes["chunk"].base == "piece"
    assert s.classes["media"].base == "piece"
    assert s.edges["part_of"].roles == {"piece": "piece", "whole": "document"}


def test_supply_chain_table_blob_is_a_piece():
    s = Schema.supply_chain()
    assert s.classes["table_blob"].base == "piece"
    assert "entity" in s.classes  # builtins present in derived schemas too
