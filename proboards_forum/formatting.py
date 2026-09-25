"""
Message formatting: BBCode rendering, HTML sanitization and smileys.

Everything that ends up on a page passes through :func:`sanitize`, so posts
imported from a ProBoards forum (stored as raw HTML) and posts written here
(stored as BBCode) are both safe to render.
"""
import html
import re

import nh3
from markupsafe import Markup


ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "center", "code", "del", "div", "em",
    "font", "h1", "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre",
    "s", "small", "span", "strike", "strong", "sub", "sup", "table", "tbody",
    "td", "th", "thead", "tr", "u", "ul",
}
ALLOWED_ATTRIBUTES = {
    "*": {"class", "style", "title"},
    "a": {"href"},
    "font": {"color", "face", "size"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
# Only harmless presentational properties survive in style attributes.
ALLOWED_CSS = {
    "background-color", "color", "font-family", "font-size", "font-style",
    "font-weight", "text-align", "text-decoration",
}


def sanitize(markup: str) -> str:
    """Strip anything from HTML that isn't on the allowlist."""
    return nh3.clean(
        markup,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        filter_style_properties=ALLOWED_CSS,
        link_rel="nofollow noopener noreferrer",
        url_schemes={"http", "https", "mailto"},
    )


SMILEYS = {
    ":)": "smile", ";)": "wink", ":D": "grin", ";D": "cheesy",
    ">:(": "angry", ":(": "sad", ":o": "shocked", "8)": "cool",
    ":P": "tongue", ":-[": "embarrassed", ":-X": "lipsrsealed",
    ":-/": "undecided", ":'(": "cry", "::)": "rolleyes",
}
SMILEY_EMOJI = {
    "smile": "\U0001F642", "wink": "\U0001F609", "grin": "\U0001F600",
    "cheesy": "\U0001F601", "angry": "\U0001F620", "sad": "\U0001F641",
    "shocked": "\U0001F62E", "cool": "\U0001F60E", "tongue": "\U0001F61B",
    "embarrassed": "\U0001F633", "lipsrsealed": "\U0001F910",
    "undecided": "\U0001F615", "cry": "\U0001F622",
    "rolleyes": "\U0001F644",
}
# Longest codes first so "::)" wins over ":)". Codes are matched against
# HTML-escaped text, hence the escaping here.
_SMILEY_RE = re.compile(
    r"(?<![\w&;/])("
    + "|".join(
        re.escape(html.escape(code))
        for code in sorted(SMILEYS, key=len, reverse=True)
    )
    + r")(?![\w])"
)


def _smiley(match: re.Match) -> str:
    name = SMILEYS[html.unescape(match.group(1))]
    return (
        f'<span class="smiley" title="{name}">{SMILEY_EMOJI[name]}</span>'
    )


_URL_RE = r"(?:https?://|mailto:|/)[^\s\"'<>\[\]]*"
_COLOR_RE = r"#[0-9a-fA-F]{3,6}|[a-zA-Z]{3,20}"

# (pattern, replacement) pairs applied repeatedly so nested tags work.
_SIMPLE_TAGS = [
    (r"\[b\](.*?)\[/b\]", r"<strong>\1</strong>"),
    (r"\[i\](.*?)\[/i\]", r"<em>\1</em>"),
    (r"\[u\](.*?)\[/u\]", r"<u>\1</u>"),
    (r"\[s\](.*?)\[/s\]", r"<s>\1</s>"),
    (r"\[sub\](.*?)\[/sub\]", r"<sub>\1</sub>"),
    (r"\[sup\](.*?)\[/sup\]", r"<sup>\1</sup>"),
    (r"\[center\](.*?)\[/center\]",
     r'<div style="text-align: center">\1</div>'),
    (r"\[left\](.*?)\[/left\]", r'<div style="text-align: left">\1</div>'),
    (r"\[right\](.*?)\[/right\]",
     r'<div style="text-align: right">\1</div>'),
    (rf"\[color=({_COLOR_RE})\](.*?)\[/color\]",
     r'<span style="color: \1">\2</span>'),
    (r"\[size=([1-7])\](.*?)\[/size\]", r'<font size="\1">\2</font>'),
    (r"\[font=([\w ,-]{1,40})\](.*?)\[/font\]",
     r'<span style="font-family: \1">\2</span>'),
    (rf"\[url=({_URL_RE})\](.*?)\[/url\]", r'<a href="\1">\2</a>'),
    (rf"\[url\]({_URL_RE})\[/url\]", r'<a href="\1">\1</a>'),
    (r"\[email\]([^\s\[\]@]+@[^\s\[\]]+)\[/email\]",
     r'<a href="mailto:\1">\1</a>'),
    (rf"\[img\]({_URL_RE})\[/img\]", r'<img src="\1" alt="">'),
    (r"\[quote\](.*?)\[/quote\]",
     r'<blockquote class="quote"><div class="quote-body">\1</div>'
     r"</blockquote>"),
    (r"\[quote=([^\]]{1,64})\](.*?)\[/quote\]",
     r'<blockquote class="quote"><div class="quote-header">'
     r'Quote from \1</div><div class="quote-body">\2</div></blockquote>'),
    (r"\[hr\]", r"<hr>"),
]
_SIMPLE_TAGS = [
    (re.compile(pattern, re.IGNORECASE | re.DOTALL), repl)
    for pattern, repl in _SIMPLE_TAGS
]
_CODE_RE = re.compile(r"\[code\](.*?)\[/code\]", re.IGNORECASE | re.DOTALL)
_LIST_RE = re.compile(
    r"\[list(=1)?\](.*?)\[/list\]", re.IGNORECASE | re.DOTALL
)
_AUTOLINK_RE = re.compile(
    r'(?<![="\'>/])\b(https?://[^\s<>"\'\[\]]+[^\s<>"\'\[\].,;:!?)])'
)


def _render_list(match: re.Match) -> str:
    tag = "ol" if match.group(1) else "ul"
    items = [
        item.strip() for item in re.split(r"\[\*\]", match.group(2))
        if item.strip()
    ]
    return f"<{tag}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{tag}>"


def bbcode_to_html(text: str) -> str:
    """
    Convert BBCode to HTML. The input is HTML-escaped first, so raw HTML
    typed into a post shows up literally rather than being rendered.
    """
    text = html.escape(text.replace("\r\n", "\n"), quote=True)

    # Pull code blocks out first so nothing inside them gets formatted.
    code_blocks = []

    def _stash_code(match: re.Match) -> str:
        code_blocks.append(match.group(1).strip("\n"))
        return f"\x00{len(code_blocks) - 1}\x00"

    text = _CODE_RE.sub(_stash_code, text)

    # Undo escaping of quotes inside tag arguments, e.g. [quote="name"].
    text = re.sub(r"\[quote=&quot;(.*?)&quot;\]", r"[quote=\1]", text)

    for _ in range(10):
        previous = text
        text = _LIST_RE.sub(_render_list, text)
        for pattern, repl in _SIMPLE_TAGS:
            text = pattern.sub(repl, text)
        if text == previous:
            break

    text = _AUTOLINK_RE.sub(r'<a href="\1">\1</a>', text)
    text = _SMILEY_RE.sub(_smiley, text)
    text = text.replace("\n", "<br>\n")
    # Block elements don't need a line break right after them.
    text = re.sub(
        r"(</?(?:blockquote|div|ul|ol|li|hr)[^>]*>)<br>\n", r"\1\n", text
    )

    def _restore_code(match: re.Match) -> str:
        return f"<pre class=\"code\"><code>{code_blocks[int(match.group(1))]}"\
               "</code></pre>"

    text = re.sub(r"\x00(\d+)\x00", _restore_code, text)
    return text


def render(body: str, body_format: str = "bbcode") -> Markup:
    """Render a stored message body to safe HTML."""
    if not body:
        return Markup("")
    if body_format == "html":
        markup = body
    else:
        markup = bbcode_to_html(body)
    return Markup(sanitize(markup))


def html_to_text(markup: str) -> str:
    """Rough plain-text version of HTML, for quoting imported posts."""
    text = re.sub(r"<br\s*/?>", "\n", markup, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|blockquote)>", "\n", text,
                  flags=re.IGNORECASE)
    text = nh3.clean(text, tags=set())
    return html.unescape(text).strip()


def snippet(body: str, body_format: str = "bbcode", length: int = 200) -> str:
    """Short plain-text preview of a message, for search results."""
    if body_format == "html":
        text = html_to_text(body)
    else:
        text = re.sub(r"\[/?[a-zA-Z*][^\]]*\]", "", body)
    text = " ".join(text.split())
    if len(text) > length:
        text = text[:length].rsplit(" ", 1)[0] + "…"
    return text
