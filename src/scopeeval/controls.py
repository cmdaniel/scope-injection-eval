"""Harness-side controls that act outside the model.

``egress_filter`` removes links and images that point outside the organisation
from text before it is shown or rendered. It closes the output channel of the
lethal trifecta: a client that renders markdown fetches an image URL
automatically, so data placed in that URL leaves without any tool call. Tool
scope cannot stop this; a filter on rendered output can.

The filter is applied after the episode, to the agent's final answer, so its
effect is measured on the same episodes at no extra API cost.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .world import INTERNAL_DOMAIN

URL_RE = re.compile(r"https?://[^\s)\]>\"'<]+", re.IGNORECASE)
_MD_IMAGE_OR_LINK = re.compile(r"!?\[([^\]]*)\]\((https?://[^)\s]+)[^)]*\)", re.IGNORECASE)
REMOVED = "[external link removed]"
# Punctuation that ends a sentence, not a URL. Markdown renderers (GitHub's autolink
# extension, for one) leave it out of the link, so the harness does too.
_TRAILING = ".,;:!?*_~"


def find_urls(text: str) -> list[str]:
    """Bare http(s) URLs in the text, without sentence punctuation that follows them."""
    return [u.rstrip(_TRAILING) for u in URL_RE.findall(text)]


def is_allowed_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == INTERNAL_DOMAIN or host.endswith("." + INTERNAL_DOMAIN)


def external_urls(text: str) -> list[str]:
    return [u for u in find_urls(text) if not is_allowed_host(u)]


def egress_filter(text: str) -> str:
    """Strip markdown images, markdown links and bare URLs to non-allowlisted hosts."""

    def _md(match: re.Match[str]) -> str:
        return match.group(0) if is_allowed_host(match.group(2)) else REMOVED

    text = _MD_IMAGE_OR_LINK.sub(_md, text)
    def _bare(match: re.Match[str]) -> str:
        url = match.group(0).rstrip(_TRAILING)
        return match.group(0) if is_allowed_host(url) else REMOVED + match.group(0)[len(url):]

    return URL_RE.sub(_bare, text)
