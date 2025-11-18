"""Tests for markdown text formatting."""

from mouc.backends.text_formatter import (
    CodeBlock,
    InlineBold,
    InlineCode,
    InlineItalic,
    InlineLink,
    InlineText,
    List,
    Paragraph,
    parse_markdown,
)


def test_parse_plain_text():
    """Test parsing plain text."""
    result = parse_markdown("Hello world")
    assert len(result) == 1
    assert isinstance(result[0], Paragraph)
    assert len(result[0].children) == 1
    assert isinstance(result[0].children[0], InlineText)
    assert result[0].children[0].text == "Hello world"


def test_parse_bold_text():
    """Test parsing bold text."""
    result = parse_markdown("This is **bold** text")
    assert len(result) == 1
    assert isinstance(result[0], Paragraph)
    children = result[0].children
    assert len(children) == 3
    assert isinstance(children[0], InlineText)
    assert children[0].text == "This is "
    assert isinstance(children[1], InlineBold)
    assert isinstance(children[2], InlineText)
    assert children[2].text == " text"


def test_parse_italic_text():
    """Test parsing italic text."""
    result = parse_markdown("This is *italic* text")
    assert len(result) == 1
    assert isinstance(result[0], Paragraph)
    children = result[0].children
    assert len(children) == 3
    assert isinstance(children[0], InlineText)
    assert isinstance(children[1], InlineItalic)
    assert isinstance(children[2], InlineText)


def test_parse_inline_code():
    """Test parsing inline code."""
    result = parse_markdown("Use `code` here")
    assert len(result) == 1
    assert isinstance(result[0], Paragraph)
    children = result[0].children
    assert len(children) == 3
    assert isinstance(children[0], InlineText)
    assert isinstance(children[1], InlineCode)
    assert children[1].text == "code"
    assert isinstance(children[2], InlineText)


def test_parse_link():
    """Test parsing links."""
    result = parse_markdown("Click [here](https://example.com) to visit")
    assert len(result) == 1
    assert isinstance(result[0], Paragraph)
    children = result[0].children
    assert len(children) == 3
    assert isinstance(children[0], InlineText)
    assert isinstance(children[1], InlineLink)
    assert children[1].url == "https://example.com"
    assert isinstance(children[2], InlineText)


def test_parse_code_block():
    """Test parsing code blocks."""
    result = parse_markdown("```python\nprint('hello')\n```")
    assert len(result) == 1
    assert isinstance(result[0], CodeBlock)
    assert result[0].code == "print('hello')"
    assert result[0].language == "python"


def test_parse_unordered_list():
    """Test parsing unordered lists."""
    result = parse_markdown("- Item 1\n- Item 2\n- Item 3")
    assert len(result) == 1
    assert isinstance(result[0], List)
    assert not result[0].ordered
    assert len(result[0].items) == 3


def test_parse_ordered_list():
    """Test parsing ordered lists."""
    result = parse_markdown("1. First\n2. Second\n3. Third")
    assert len(result) == 1
    assert isinstance(result[0], List)
    assert result[0].ordered
    assert len(result[0].items) == 3


def test_parse_mixed_formatting():
    """Test parsing text with mixed formatting."""
    result = parse_markdown(
        "This has **bold** and *italic* and `code` and [link](https://example.com)"
    )
    assert len(result) == 1
    assert isinstance(result[0], Paragraph)
    children = result[0].children
    # Should have: text, bold, text, italic, text, code, text, link
    assert len(children) >= 7


def test_parse_multiple_paragraphs():
    """Test parsing multiple paragraphs."""
    result = parse_markdown("First paragraph\n\nSecond paragraph")
    assert len(result) == 2
    assert isinstance(result[0], Paragraph)
    assert isinstance(result[1], Paragraph)


def test_parse_nested_formatting():
    """Test parsing nested bold/italic."""
    result = parse_markdown("***bold and italic***")
    assert len(result) == 1
    assert isinstance(result[0], Paragraph)
    # This should parse as nested bold and italic
    children = result[0].children
    assert len(children) == 1
