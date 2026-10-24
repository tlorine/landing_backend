"""Trust geo headers only after an explicitly configured edge strips spoofed headers."""

import ipaddress
import re
from dataclasses import dataclass

from fastapi import Request

from app.core.config import settings


@dataclass(frozen=True)
class ClientContext:
    ip: str
    country: str | None


def client_context(request: Request) -> ClientContext:
    peer = request.client.host if request.client else ""
    trusted = False
    try:
        address = ipaddress.ip_address(peer)
        trusted = settings.trust_cloudflare_headers and any(
            address in ipaddress.ip_network(cidr) for cidr in settings.trusted_proxy_cidrs
        )
    except ValueError:
        pass
    if not trusted:
        return ClientContext(peer, None)
    forwarded = request.headers.get("cf-connecting-ip", "").strip()
    try:
        ipaddress.ip_address(forwarded)
    except ValueError:
        forwarded = peer
    country = request.headers.get("cf-ipcountry", "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country) or country == "XX":
        country = None
    return ClientContext(forwarded, country)
