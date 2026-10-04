"""Native file-format operations for staged application settings.

The registry is internal; supporting another format does not require changing
command selection or transport. AEM intent metadata remains TOML separately.
"""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, DecimalException
import json
import math
from typing import Protocol

import tomlkit

from .model import Error


class SettingsFormat(Protocol):
    """Native document operations consumed by the format-independent workflow."""

    def empty_document(self) -> object: ...
    def parse(self, text: str) -> object: ...
    def fields(self, document: object) -> dict[tuple[str, ...], object]: ...
    def identity(self, value: object) -> object: ...
    def put(self, document: object, path: tuple[str, ...], value: object = None, *, delete: bool = False) -> None: ...
    def dump(self, document: object) -> str: ...


class TomlFormat:
    """TOML-specific parsing, field identity, equality, and preserving edits.

    Ordinary tables expose their leaves; arrays (including arrays of tables)
    and empty tables are indivisible values. No parser nodes escape this adapter
    into persisted ownership or CLI reports.
    """

    @staticmethod
    def empty_document():
        return tomlkit.document()

    @staticmethod
    def parse(text):
        try:
            return tomlkit.parse(text)
        except (ValueError, TypeError) as exc:
            raise Error(f"Invalid TOML settings: {exc}") from exc

    @staticmethod
    def fields(document):
        result = {}

        def visit(node, path):
            if isinstance(node, dict) and node:
                for key, value in node.items():
                    visit(value, (*path, key))
            elif path:
                result[path] = node

        visit(document, ())
        return result

    @staticmethod
    def identity(value):
        if isinstance(value, tomlkit.items.String):
            # Normalize physical newlines in the original TOML token, before
            # decoding escapes. Unwrapped strings cannot distinguish a file's
            # CRLF from an intentional \\r\\n or \\u000D escape sequence.
            token = value.as_string()
            normalized = (tomlkit.parse("value = " + token.replace("\r\n", "\n"))["value"].unwrap()
                          if "\r\n" in token else value.unwrap())
            return ("str", normalized)
        # Recurse before unwrapping containers so nested strings retain their
        # original tokens. Documents and snapshots themselves remain untouched.
        if isinstance(value, dict):
            return ("table", tuple(sorted((k, TomlFormat.identity(v)) for k, v in value.items())))
        if isinstance(value, list):
            return ("array", tuple(TomlFormat.identity(v) for v in value))
        value = value.unwrap() if hasattr(value, "unwrap") else value
        if isinstance(value, float):
            return ("float", "nan" if math.isnan(value) else value.hex())
        return (type(value).__name__, value)

    @staticmethod
    def put(document, path, value=None, *, delete=False):
        node = document
        parents = []
        for key in path[:-1]:
            if key not in node:
                if delete:
                    return
                node[key] = tomlkit.table()
            if not isinstance(node[key], dict):
                if delete:
                    return
                raise Error(f"Field structure conflict at {json.dumps(list(path))}")
            parents.append((node, key))
            node = node[key]
        if delete:
            node.pop(path[-1], None)
            # Empty parent tables introduced by removing their last leaf are
            # containers, not retained empty-table ownership declarations.
            for parent, key in reversed(parents):
                if parent[key]:
                    break
                del parent[key]
        else:
            node[path[-1]] = deepcopy(value)

    @staticmethod
    def dump(document):
        return tomlkit.dumps(document)


@dataclass
class JsonNode:
    """A semantic value with its original token and container locations.

    Array children support formatting new files but stay atomic to ownership.
    Locations are private to the document and rebuilt after every text edit.
    """

    start: int
    end: int
    raw: str
    value: object
    children: dict | list | None = None
    key_starts: dict | None = None


@dataclass
class JsonDocument:
    text: str
    root: JsonNode
    fresh: bool = False


class JsonFormat:
    """Strict JSON objects with exact numbers and local, preserving text edits.

    The standard decoder validates the complete input, including atomic arrays.
    Object spans locate edits; they are never persisted as ownership values.
    Decimal equality makes numeric spelling irrelevant without rounding through
    binary floats. Raw tokens preserve that spelling when values are copied.
    """

    @staticmethod
    def _pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate object key")
            result[key] = value
        return result

    @staticmethod
    def _constant(value):
        raise ValueError("nonstandard numeric constant")

    @staticmethod
    def empty_document():
        document = JsonFormat.parse("{}\n")
        document.fresh = True
        return document

    @staticmethod
    def parse(text):
        decoder = json.JSONDecoder(parse_int=Decimal, parse_float=Decimal,
                                   parse_constant=JsonFormat._constant,
                                   object_pairs_hook=JsonFormat._pairs)
        try:
            value = decoder.decode(text)
            if not isinstance(value, dict):
                raise ValueError("top-level value must be an object")

            def whitespace(offset):
                while offset < len(text) and text[offset] in " \t\r\n":
                    offset += 1
                return offset

            def node(offset, parsed):
                start = whitespace(offset)
                if isinstance(parsed, dict):
                    children, keys = {}, {}
                    cursor = whitespace(start + 1)
                    for key, child in parsed.items():
                        keys[key] = cursor
                        _, cursor = decoder.raw_decode(text, cursor)
                        cursor = whitespace(cursor)
                        entry = node(cursor + 1, child)  # skip the validated colon
                        children[key] = entry
                        cursor = whitespace(entry.end)
                        if text[cursor] == ",":
                            cursor = whitespace(cursor + 1)
                    end = cursor + 1  # closing brace
                    return JsonNode(start, end, text[start:end], parsed, children, keys)
                if isinstance(parsed, list):
                    children = []
                    cursor = whitespace(start + 1)
                    for child in parsed:
                        entry = node(cursor, child)
                        children.append(entry)
                        cursor = whitespace(entry.end)
                        if text[cursor] == ",":
                            cursor = whitespace(cursor + 1)
                    end = cursor + 1  # closing bracket
                    return JsonNode(start, end, text[start:end], parsed, children)
                _, end = decoder.raw_decode(text, start)
                return JsonNode(start, end, text[start:end], parsed)

            return JsonDocument(text, node(0, value))
        except (ValueError, TypeError, RecursionError, DecimalException) as exc:
            # Do not include document fragments or configuration values in errors.
            detail = f" at line {exc.lineno}, column {exc.colno}" if isinstance(exc, json.JSONDecodeError) else ""
            raise Error(f"Invalid JSON settings{detail}: expected a strict object with unique keys") from exc

    @staticmethod
    def fields(document):
        result = {}

        def visit(node, path):
            if isinstance(node.children, dict) and node.children:
                for key, child in node.children.items():
                    visit(child, (*path, key))
            elif path:
                result[path] = node

        visit(document.root, ())
        return result

    @staticmethod
    def identity(value):
        if isinstance(value, JsonNode):
            value = value.value
        if isinstance(value, dict):
            return ("object", tuple(sorted((key, JsonFormat.identity(v)) for key, v in value.items())))
        if isinstance(value, list):
            return ("array", tuple(JsonFormat.identity(v) for v in value))
        if isinstance(value, Decimal):
            return ("number", value)
        return (type(value).__name__, value)

    @staticmethod
    def _edit(document, start, end, replacement):
        updated = JsonFormat.parse(document.text[:start] + replacement + document.text[end:])
        document.text, document.root = updated.text, updated.root

    @staticmethod
    def put(document, path, value=None, *, delete=False):
        node = document.root
        for index, key in enumerate(path[:-1]):
            if key not in node.children:
                if delete:
                    return
                # Build the missing branch as one insertion, leaving existing
                # containers and unmanaged siblings untouched.
                raw = value.raw
                for part in reversed(path[index + 1:]):
                    raw = "{" + json.dumps(part) + ": " + raw + "}"
                branch = JsonFormat.parse("{" + json.dumps(key) + ": " + raw + "}")
                JsonFormat.put(document, path[:index + 1], branch.root.children[key])
                return
            node = node.children[key]
            if not isinstance(node.children, dict):
                if delete:
                    return
                raise Error(f"Field structure conflict at {json.dumps(list(path))}")
        key = path[-1]
        if delete:
            if key not in node.children:
                return
            keys = list(node.children)
            index = keys.index(key)
            if len(keys) == 1:
                start, end = node.key_starts[key], node.children[key].end
            elif index < len(keys) - 1:
                start, end = node.key_starts[key], node.key_starts[keys[index + 1]]
            else:
                # Remove the preceding comma, retaining whitespace after the
                # previous value and the closing brace's original indentation.
                start = document.text.index(",", node.children[keys[index - 1]].end, node.key_starts[key])
                end = node.children[key].end
            JsonFormat._edit(document, start, end, "")
            if len(path) > 1:
                parent_path = path[:-1]
                parent = document.root
                for part in parent_path:
                    parent = parent.children[part]
                if parent.children == {}:
                    JsonFormat.put(document, parent_path, delete=True)
            return
        if key in node.children:
            current = node.children[key]
            if JsonFormat.identity(current) != JsonFormat.identity(value):
                JsonFormat._edit(document, current.start, current.end, value.raw)
            return

        text = document.text
        multiline = "\n" in node.raw or document.fresh
        eol = "\r\n" if "\r\n" in text else "\n"
        line_start = text.rfind("\n", 0, node.start) + 1
        parent_indent = text[line_start:node.start]
        parent_indent = parent_indent[:len(parent_indent) - len(parent_indent.lstrip(" \t"))]
        indent = parent_indent + "  "
        if node.children:
            first_start = next(iter(node.key_starts.values()))
            candidate = text[text.rfind("\n", 0, first_start) + 1:first_start]
            if candidate and not candidate.strip(" \t\r"):
                indent = candidate
        entry = json.dumps(key) + ": " + value.raw
        if node.children:
            last = next(reversed(node.children.values()))
            insertion = "," + (eol + indent if multiline else " ") + entry
            JsonFormat._edit(document, last.end, last.end, insertion)
        else:
            tail = text[node.start + 1:node.end - 1]
            insertion = (eol + indent if multiline else "") + entry
            if multiline and "\n" not in tail:
                insertion += eol + parent_indent
            JsonFormat._edit(document, node.start + 1, node.start + 1, insertion)

    @staticmethod
    def dump(document):
        if document.fresh:
            # New files have no layout to preserve. Format their containers
            # consistently while retaining exact scalar tokens from the stage.
            def pretty(node, level):
                if node.children is None:
                    return node.raw
                if isinstance(node.children, dict):
                    entries = [json.dumps(key) + ": " + pretty(child, level + 1)
                               for key, child in node.children.items()]
                    opening, closing = "{", "}"
                else:
                    entries = [pretty(child, level + 1) for child in node.children]
                    opening, closing = "[", "]"
                if not entries:
                    return opening + closing
                indent = "  " * (level + 1)
                return opening + "\n" + indent + (",\n" + indent).join(entries) + "\n" + "  " * level + closing

            return pretty(document.root, 0) + "\n"
        return document.text


FORMATS = {"toml": TomlFormat(), "json": JsonFormat()}
