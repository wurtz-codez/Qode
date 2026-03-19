"""Tests for KuzuDB adapter schema and CSV utilities."""

from __future__ import annotations

import asyncio

import pytest

from qode.data.csv_generator import (
    BufferedCSVWriter,
    escape_csv_field,
    escape_csv_number,
    is_binary_content,
    sanitize_utf8,
    stream_all_csvs_to_disk,
)
from qode.data.kuzu_schema import (
    EMBEDDING_TABLE_NAME,
    NODE_TABLES,
    REL_TABLE_NAME,
    REL_TYPES,
    SCHEMA_QUERIES,
)


def test_schema_constants_and_queries() -> None:
    assert "File" in NODE_TABLES
    assert REL_TABLE_NAME == "CodeRelation"
    assert "CALLS" in REL_TYPES
    assert EMBEDDING_TABLE_NAME == "CodeEmbedding"
    expected_len = len(NODE_TABLES) + 1 + 1
    assert len(SCHEMA_QUERIES) == expected_len


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, '""'),
        ("plain", '"plain"'),
        ('quote"here', '"quote""here"'),
        ("line\r\nfeed", '"line\nfeed"'),
    ],
)
def test_escape_csv_field(value: object | None, expected: str) -> None:
    assert escape_csv_field(value) == expected


@pytest.mark.parametrize(
    "value,default_value,expected",
    [
        (None, -1, "-1"),
        (None, 0, "0"),
        (2.5, -1, "2.5"),
    ],
)
def test_escape_csv_number(
    value: float | None,
    default_value: float,
    expected: str,
) -> None:
    assert escape_csv_number(value, default_value) == expected


def test_sanitize_utf8_removes_invalid_chars() -> None:
    raw = "A\x01B\r\nC\ud800D\uffffE"
    cleaned = sanitize_utf8(raw)
    assert cleaned == "AB\nCDE"


def test_is_binary_content_detection() -> None:
    assert is_binary_content("") is False
    assert is_binary_content("Hello world\n") is False
    binary_like = "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0e" + ("A" * 90)
    assert is_binary_content(binary_like) is True


def test_buffered_csv_writer_flush_and_rows(tmp_path) -> None:
    csv_path = tmp_path / "sample.csv"
    writer = BufferedCSVWriter(str(csv_path), "col1,col2")
    asyncio.run(writer.add_row("a,b"))
    asyncio.run(writer.add_row("c,d"))
    assert writer.rows == 2
    asyncio.run(writer.flush())
    asyncio.run(writer.finish())

    content = csv_path.read_text(encoding="utf-8")
    assert content == "col1,col2\na,b\nc,d\n"


def test_stream_all_csvs_to_disk(tmp_path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    source_path = repo_path / "src"
    source_path.mkdir()
    file_path = source_path / "main.py"
    file_path.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    class FakeNode:
        def __init__(self, node_id: str, label: str, properties: dict) -> None:
            self.id = node_id
            self.label = label
            self.properties = properties

    class FakeRel:
        def __init__(
            self,
            source_id: str,
            target_id: str,
            rel_type: str,
            reason: str,
        ) -> None:
            self.source_id = source_id
            self.target_id = target_id
            self.type = rel_type
            self.reason = reason
            self.confidence = 0.9
            self.step = 1

    class FakeGraph:
        def __init__(self, nodes, rels) -> None:
            self._nodes = nodes
            self._rels = rels

        def iter_nodes(self):
            return iter(self._nodes)

        def iter_relationships(self):
            return iter(self._rels)

        def iterNodes(self):  # noqa: N802
            return iter(self._nodes)

        def iterRelationships(self):  # noqa: N802
            return iter(self._rels)

    nodes = [
        FakeNode(
            "File:src/main.py",
            "File",
            {"name": "main.py", "filePath": "src/main.py"},
        ),
        FakeNode(
            "Folder:src",
            "Folder",
            {"name": "src", "filePath": "src"},
        ),
        FakeNode(
            "Function:hello",
            "Function",
            {
                "name": "hello",
                "filePath": "src/main.py",
                "startLine": 1,
                "endLine": 2,
                "isExported": True,
                "description": "greeting",
            },
        ),
    ]
    rels = [
        FakeRel(
            "Folder:src",
            "File:src/main.py",
            "CONTAINS",
            "folder contains file",
        ),
    ]
    graph = FakeGraph(nodes, rels)

    csv_dir = tmp_path / "csv"
    result = asyncio.run(stream_all_csvs_to_disk(graph, str(repo_path), str(csv_dir)))

    assert (csv_dir / "relations.csv").exists()
    assert result["relRows"] == 1
    assert result["nodeFiles"]["File"]["rows"] == 1
    assert result["nodeFiles"]["Folder"]["rows"] == 1
    assert result["nodeFiles"]["Function"]["rows"] == 1

    rel_lines = (csv_dir / "relations.csv").read_text(encoding="utf-8").splitlines()
    assert rel_lines[0] == "from,to,type,confidence,reason,step"
    assert len(rel_lines) == 2
