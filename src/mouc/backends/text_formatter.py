"""Markdown text formatting utilities for document backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import mistune


@dataclass
class InlineText:
    """Plain text inline element."""

    text: str


@dataclass
class InlineBold:
    """Bold text inline element."""

    children: list[InlineElement]


@dataclass
class InlineItalic:
    """Italic text inline element."""

    children: list[InlineElement]


@dataclass
class InlineCode:
    """Inline code element."""

    text: str


@dataclass
class InlineLink:
    """Link inline element."""

    url: str
    children: list[InlineElement]


# Union type for inline elements
InlineElement = InlineText | InlineBold | InlineItalic | InlineCode | InlineLink


@dataclass
class Paragraph:
    """Paragraph block element."""

    children: list[InlineElement]


@dataclass
class CodeBlock:
    """Code block element."""

    code: str
    language: str | None = None


@dataclass
class ListItem:
    """List item element."""

    children: list[BlockElement]


@dataclass
class List:
    """List block element."""

    ordered: bool
    items: list[ListItem]


# Union type for block elements
BlockElement = Paragraph | CodeBlock | List | ListItem


def _convert_inline_tokens(tokens: list[dict[str, Any]]) -> list[InlineElement]:
    """Convert mistune inline tokens to our InlineElement structures.

    Args:
        tokens: List of inline tokens from mistune AST

    Returns:
        List of InlineElement objects
    """
    elements: list[InlineElement] = []

    for token in tokens:
        token_type = token["type"]

        if token_type == "text":
            elements.append(InlineText(text=token["raw"]))
        elif token_type == "strong":
            children = _convert_inline_tokens(token["children"])
            elements.append(InlineBold(children=children))
        elif token_type == "emphasis":
            children = _convert_inline_tokens(token["children"])
            elements.append(InlineItalic(children=children))
        elif token_type == "codespan":
            elements.append(InlineCode(text=token["raw"]))
        elif token_type == "link":
            children = _convert_inline_tokens(token["children"])
            elements.append(InlineLink(url=token["attrs"]["url"], children=children))
        elif token_type in {"softbreak", "linebreak"}:
            elements.append(InlineText(text=" "))
        # Ignore other inline types for now (images, etc.)

    return elements


def _convert_block_tokens(tokens: list[dict[str, Any]]) -> list[BlockElement]:
    """Convert mistune block tokens to our BlockElement structures.

    Args:
        tokens: List of block tokens from mistune AST

    Returns:
        List of BlockElement objects
    """
    elements: list[BlockElement] = []

    for token in tokens:
        token_type = token["type"]

        if token_type == "paragraph":
            children = _convert_inline_tokens(token["children"])
            elements.append(Paragraph(children=children))
        elif token_type == "block_code":
            code = token["raw"]
            language = token.get("attrs", {}).get("info")
            elements.append(CodeBlock(code=code.rstrip(), language=language))
        elif token_type == "list":
            ordered: bool = token["attrs"]["ordered"]
            items: list[ListItem] = []
            for item_token in token["children"]:
                if item_token["type"] == "list_item":
                    item_children = _convert_block_tokens(item_token["children"])
                    items.append(ListItem(children=item_children))
            elements.append(List(ordered=ordered, items=items))
        # Ignore other block types for now (headings, blockquotes, tables, etc.)

    return elements


def parse_markdown(text: str) -> list[BlockElement]:
    """Parse markdown text into structured block elements.

    Args:
        text: Markdown-formatted text

    Returns:
        List of block elements (paragraphs, lists, code blocks)
    """
    # Use ASTRenderer to get AST tokens
    markdown = mistune.create_markdown(renderer="ast")
    result = markdown(text)

    # When using 'ast' renderer, result is always a list of tokens
    assert isinstance(result, list), "AST renderer must return a list"

    # Convert AST tokens to our BlockElement structures
    return _convert_block_tokens(result)
