from fastapi import Request
from config import settings


def extract_client_ip(request: Request) -> str:
    """
    Safely resolves the true visitor IP address.
    If the direct connection originates from a configured trusted reverse proxy,
    parses X-Forwarded-For or X-Real-IP headers.
    Otherwise, returns the direct peer host.
    """
    direct_ip = request.client.host if request.client else "127.0.0.1"

    is_trusted = False
    for trusted in settings.trusted_proxies:
        if direct_ip == trusted or trusted == "*":
            is_trusted = True
            break

    if is_trusted:
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            # Standard format: <client>, <proxy1>, <proxy2>
            parts = [p.strip() for p in x_forwarded_for.split(",") if p.strip()]
            if parts:
                return parts[0]

        x_real_ip = request.headers.get("x-real-ip")
        if x_real_ip and x_real_ip.strip():
            return x_real_ip.strip()

    return direct_ip
