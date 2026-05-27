from urllib.parse import unquote, urlparse


def canonical_article_url(url: str) -> str:
    """URL normalisée pour éviter les doublons (www, slash, encodage +, etc.)."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme or "https"
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = unquote(parsed.path.rstrip("/"))
    return f"{scheme}://{host}{path}"
