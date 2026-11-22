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


def is_allowed_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == INTERNAL_DOMAIN or host.endswith("." + INTERNAL_DOMAIN)


def external_urls(text: str) -> list[str]:
    return [u for u in URL_RE.findall(text) if not is_allowed_host(u)]


def egress_filter(text: str) -> str:
    """Strip markdown images, markdown links and bare URLs to non-allowlisted hosts."""

    def _md(match: re.Match[str]) -> str:
        return match.group(0) if is_allowed_host(match.group(2)) else REMOVED

    text = _MD_IMAGE_OR_LINK.sub(_md, text)
    return URL_RE.sub(lambda m: m.group(0) if is_allowed_host(m.group(0)) else REMOVED, text)
