"""Lexical link identity shared with the standalone update worker."""


def same_destination(actual, expected):
    """Compare recorded link text exactly.

    Do not resolve links or use samefile: a substituted link through an alias
    must not gain ownership merely because it reaches the same current inode.
    """
    return isinstance(actual, str) and isinstance(expected, str) and actual == expected
