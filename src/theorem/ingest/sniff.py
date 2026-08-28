import csv
import io
import json
import zipfile


def sniff(data: bytes, filename: str = "") -> str:
    """Detect file type from magic bytes and content.

    Returns one of: "pdf" "docx" "xlsx" "pptx" "zip" "png" "jpeg" "webp" "gif"
                    "csv" "json" "jsonl" "markdown" "text" "binary"

    Magic bytes always win over filename hints.
    """

    # Step 1: Check magic bytes (binary formats first)
    if data.startswith(b"%PDF"):
        return "pdf"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    if data.startswith(b"RIFF") and len(data) >= 12:
        if data[8:12] == b"WEBP":
            return "webp"

    if data.startswith(b"GIF8"):
        return "gif"

    if data.startswith(b"PK\x03\x04"):
        # It's a ZIP file, check if it's OOXML (docx, xlsx, pptx)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                namelist = z.namelist()
                # Check for OOXML formats
                if any(name.startswith("word/") for name in namelist):
                    return "docx"
                if any(name.startswith("xl/") for name in namelist):
                    return "xlsx"
                if any(name.startswith("ppt/") for name in namelist):
                    return "pptx"
        except (zipfile.BadZipFile, Exception):
            pass
        return "zip"

    # Step 2: Try to decode as text
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"

    # Check for binary content indicators (null bytes, control chars)
    if _is_binary_content(data):
        return "binary"

    # Step 3: Detect text formats
    # Try JSON (whole body as single JSON object/array)
    try:
        json.loads(text)
        return "json"
    except (json.JSONDecodeError, ValueError):
        pass

    # Try JSONL (every non-empty line is valid JSON, and >1 line)
    lines = text.splitlines()
    non_empty_lines = [line for line in lines if line.strip()]
    if len(non_empty_lines) > 1:
        all_valid_json = all(_is_json(line.strip()) for line in non_empty_lines)
        if all_valid_json:
            return "jsonl"

    # Check for Markdown
    if filename.endswith(".md") or (text and text[0] == "#"):
        return "markdown"

    # Check for CSV
    if filename.endswith(".csv"):
        return "csv"

    # Try CSV sniffer (>=2 lines with same comma count >=1)
    if len(lines) >= 2:
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(text, delimiters=",")
            # If sniffer succeeded and found comma delimiter, it's likely CSV
            if dialect.delimiter == ",":
                return "csv"
        except (csv.Error, Exception):
            pass

    # Default to text
    return "text"


def _is_json(s: str) -> bool:
    """Check if a string is valid JSON."""
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _is_binary_content(data: bytes) -> bool:
    """Check if data contains binary indicators like null bytes or control chars."""
    # Null bytes are a strong indicator of binary
    if b"\x00" in data:
        return True
    # Check for high proportion of control characters
    control_count = sum(
        1 for byte in data if byte < 0x09 or (0x0E <= byte < 0x20) or byte >= 0x7F
    )
    if len(data) > 0 and control_count / len(data) > 0.3:
        return True
    return False
