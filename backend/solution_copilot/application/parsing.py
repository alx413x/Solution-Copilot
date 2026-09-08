"""Bounded, offline extraction with source locations; no model or network calls."""

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

import pymupdf
from docx import Document as WordDocument
from docx.table import Table

from solution_copilot.application.errors import AppError
from solution_copilot.config import get_settings

MIMES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
PARAMETERS = {
    "version": "s02-v1",
    "target": 700,
    "overlap": 100,
    "count_unit": "unicode_character",
    "index_status": "pending",
}


def invalid(message, code="INVALID_FILE"):
    return AppError(422, code, message)


def text_decode(data):
    try:
        value = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise invalid("文本编码不支持，请另存为 UTF-8 后上传。") from None
    if any(ord(c) < 32 and c not in "\n\r\t\f" for c in value):
        raise invalid("文件包含二进制或控制字符，请上传纯文本。")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def validate_file(name, mime, data):
    extension = PurePath(name).suffix.lower()
    if extension not in MIMES:
        raise invalid("仅支持 TXT、Markdown、PDF、DOCX。")
    allowed = {MIMES[extension], "application/octet-stream"}
    if extension == ".md":
        allowed.add("text/plain")
    if (mime or "application/octet-stream").split(";")[0].lower() not in allowed:
        raise invalid("扩展名与文件类型不一致。")
    if not data:
        raise invalid("文件为空，请选择有内容的文件。")
    if len(data) > get_settings().upload_max_bytes:
        raise AppError(413, "FILE_TOO_LARGE", "文件超过上传大小限制。")
    if extension in {".txt", ".md"}:
        text_decode(data)
    elif extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise invalid("PDF 文件签名无效，请重新导出。")
    else:
        try:
            with ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 2000
                    or sum(e.file_size for e in entries) > 100 * 1024 * 1024
                    or any(e.flag_bits & 1 for e in entries)
                ):
                    raise invalid("DOCX 展开内容过大或已加密，请简化文档。")
                names = archive.namelist()
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise invalid("不是有效的 DOCX 文档。")
                if any("vbaproject" in n.lower() for n in names):
                    raise invalid("不支持包含宏的文档。")
        except BadZipFile:
            raise invalid("DOCX 文件签名无效，请重新保存。") from None
    return extension, MIMES[extension]


@dataclass
class Block:
    text: str
    path: list[str]
    location: dict
    page: int | None = None
    table: bool = False


def extract(data, extension):
    if extension in {".txt", ".md"}:
        path = []
        lines = text_decode(data).splitlines()
        index = 0
        while index < len(lines):
            start = index
            line = lines[index]
            heading = re.match(r"^(#{1,6})\s+(.+)$", line) if extension == ".md" else None
            if heading:
                path = path[: len(heading[1]) - 1] + [heading[2]]
            table = (
                extension == ".md"
                and "|" in line
                and index + 1 < len(lines)
                and bool(re.match(r"^[\s|:\-]+$", lines[index + 1]))
            )
            if table:
                index += 2
                while index < len(lines) and "|" in lines[index]:
                    index += 1
            else:
                index += 1
                while (
                    index < len(lines)
                    and lines[index].strip()
                    and not re.match(r"^#{1,6}\s", lines[index])
                    and not heading
                    and "|" not in lines[index]
                ):
                    index += 1
            value = "\n".join(lines[start:index]).strip()
            if value:
                yield Block(
                    value, list(path), {"line_start": start + 1, "line_end": index}, table=table
                )
    elif extension == ".pdf":
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise invalid("PDF 已加密，请解除密码后重新上传。", "PDF_ENCRYPTED")
            if pdf.page_count > 1000:
                raise invalid("PDF 超过 1000 页，请拆分上传。", "DOCUMENT_TOO_LARGE")
            for number, page in enumerate(pdf, 1):
                for block in page.get_text("blocks", sort=True):
                    if block[6] == 0 and block[4].strip():
                        yield Block(block[4].strip(), [], {"bbox": list(block[:4])}, number)
    else:
        document = WordDocument(BytesIO(data))
        path = []
        for index, item in enumerate(document.iter_inner_content(), 1):
            if isinstance(item, Table):
                rows = [" | ".join(cell.text for cell in row.cells) for row in item.rows]
                yield Block("\n".join(rows), list(path), {"body_block": index}, table=True)
            else:
                heading = re.match(r"Heading (\d)", item.style.name if item.style else "")
                if heading:
                    path = path[: int(heading[1]) - 1] + [item.text]
                if item.text.strip():
                    yield Block(item.text.strip(), list(path), {"body_block": index})


def chunks(data, extension, checkpoint=lambda: None):
    """S02 uses explicit character counts, not misleading model-specific token estimates."""
    output = []
    total = 0
    for block in extract(data, extension):
        checkpoint()
        total += len(block.text)
        if total > get_settings().document_max_chars:
            raise invalid("提取文本过大，请拆分文档。", "DOCUMENT_TOO_LARGE")
        pieces = []
        if block.table:
            rows = block.text.splitlines()
            header = rows[0]
            current = header
            for row in rows[1:]:
                if len(current) + len(row) > 700 and current != header:
                    pieces.append(current)
                    current = header
                current += "\n" + row
            pieces.append(current)
        else:
            start = 0
            while start < len(block.text):
                end = min(start + 700, len(block.text))
                pieces.append(block.text[start:end])
                if end == len(block.text):
                    break
                start = end - 100
        for part, content in enumerate(pieces):
            output.append(
                {
                    "ordinal": len(output),
                    "content": content,
                    "token_count": None,
                    "page_number": block.page,
                    "section_path": block.path,
                    "data": {
                        **block.location,
                        "part": part,
                        "table": block.table,
                        "count_unit": "unicode_character",
                        "character_count": len(content),
                    },
                }
            )
    if not output:
        raise invalid("未提取到文本；扫描 PDF 请先 OCR，空文档请补充内容。", "NO_TEXT")
    return output
