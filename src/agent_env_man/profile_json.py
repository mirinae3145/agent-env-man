"""Exact JSON serialization for profile settings and comparison reports."""

from decimal import Decimal
import json


def dumps(value, *, ensure_ascii=True):
    """Indent JSON by two spaces, retaining Decimal values as exact numbers."""
    def encode(item, level):
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, (dict, list)) and item:
            inner, outer = '  ' * (level + 1), '  ' * level
            entries = ([json.dumps(key, ensure_ascii=ensure_ascii) + ': ' + encode(child, level + 1)
                        for key, child in item.items()] if isinstance(item, dict)
                       else [encode(child, level + 1) for child in item])
            opening, closing = ('{', '}') if isinstance(item, dict) else ('[', ']')
            return opening + '\n' + inner + (',\n' + inner).join(entries) + '\n' + outer + closing
        return json.dumps(item, ensure_ascii=ensure_ascii)

    return encode(value, 0)
