import csv
import importlib.util
import io
import json
from pathlib import Path

from .envelope import Envelope, Media, Table
from .sniff import sniff


class IngestError(Exception):
    """Raised when data cannot be ingested due to format issues or missing extras."""

    pass


def normalize(data: bytes, filename: str) -> Envelope:
    """Convert raw bytes to a normalized Envelope.

    Dispatches on detected format from sniff(). Produces Envelope with:
    - body: decoded text or empty for tables/images
    - tables: extracted structured data (CSV, JSON arrays, JSONL)
    - images: extracted media files
    - meta: format metadata
    """
    fmt = sniff(data, filename)

    if fmt == "binary":
        raise IngestError("Binary data cannot be ingested")

    if fmt == "zip":
        raise IngestError("ZIP archives cannot be ingested")

    if fmt == "markdown" or fmt == "text":
        text = data.decode("utf-8")
        return Envelope(
            body=text,
            meta={"format": fmt, "filename": filename},
        )

    if fmt == "csv":
        text = data.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows = [row for row in reader]
        table_name = Path(filename).stem
        return Envelope(
            body="",
            tables=[Table(name=table_name, rows=rows, origin="")],
            meta={"format": "csv", "filename": filename},
        )

    if fmt == "json":
        text = data.decode("utf-8")
        obj = json.loads(text)

        if (
            isinstance(obj, list)
            and obj
            and all(isinstance(item, dict) for item in obj)
        ):
            if _is_homogeneous_list_of_dicts(obj):
                rows = _dictlist_to_rows(obj)
                table_name = Path(filename).stem
                return Envelope(
                    body="",
                    tables=[Table(name=table_name, rows=rows, origin="")],
                    meta={"format": "json", "filename": filename},
                )

        pretty = json.dumps(obj, indent=2)
        body = f"```json\n{pretty}\n```"
        return Envelope(
            body=body,
            meta={"format": "json", "filename": filename},
        )

    if fmt == "jsonl":
        text = data.decode("utf-8")
        lines = text.strip().split("\n")
        objects = [json.loads(line) for line in lines if line.strip()]

        if objects:
            all_keys = set()
            for obj in objects:
                if isinstance(obj, dict):
                    all_keys.update(obj.keys())

            rows = []
            for obj in objects:
                if isinstance(obj, dict):
                    row = {k: str(obj.get(k, "")) for k in all_keys}
                    rows.append(row)

            table_name = Path(filename).stem
            return Envelope(
                body="",
                tables=[Table(name=table_name, rows=rows, origin="")],
                meta={"format": "jsonl", "filename": filename},
            )

        return Envelope(
            body="",
            meta={"format": "jsonl", "filename": filename},
        )

    if fmt == "png" or fmt == "jpeg" or fmt == "webp" or fmt == "gif":
        media = Media(
            data=data,
            format=fmt,
            meta={"bytes": len(data)},
            origin="",
        )
        return Envelope(
            body="",
            images=[media],
            meta={"format": fmt, "filename": filename},
        )

    if fmt == "pdf":
        try:
            spec = importlib.util.find_spec("theorem.extras.pdf")
        except (ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            raise IngestError("PDF support requires: pip install 'theorem[pdf]'")
        raise IngestError("PDF handler not yet implemented (Task 8)")

    if fmt == "docx" or fmt == "xlsx" or fmt == "pptx":
        try:
            spec = importlib.util.find_spec("theorem.extras.office")
        except (ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            raise IngestError(
                "Office format support requires: pip install 'theorem[office]'"
            )
        raise IngestError("Office handler not yet implemented (Task 9)")

    raise IngestError(f"Unknown format: {fmt}")


def _is_homogeneous_list_of_dicts(obj: list) -> bool:
    """Check if a list is homogeneous: all dicts with scalar values and overlapping keys.

    Overlapping means keys share at least one common key or are identical.
    Non-scalar values (lists, dicts, etc.) return False to keep as body.
    """
    if not obj or not all(isinstance(item, dict) for item in obj):
        return False

    if len(obj) == 1:
        return all(_is_scalar(v) for v in obj[0].values())

    all_keys = set()
    for item in obj:
        if not all(_is_scalar(v) for v in item.values()):
            return False
        all_keys.update(item.keys())

    if not all_keys:
        return False

    for item in obj:
        item_keys = set(item.keys())
        if not item_keys.intersection(all_keys):
            return False

    return True


def _is_scalar(value) -> bool:
    """Check if a value is a scalar (str, int, float, bool, None)."""
    return isinstance(value, (str, int, float, bool, type(None)))


def _dictlist_to_rows(obj: list) -> list[dict[str, str]]:
    """Convert list of dicts to rows with string values, union keys, fill missing with empty string."""
    all_keys = set()
    for item in obj:
        if isinstance(item, dict):
            all_keys.update(item.keys())

    rows = []
    for item in obj:
        if isinstance(item, dict):
            row = {k: str(item.get(k, "")) for k in all_keys}
            rows.append(row)
    return rows
