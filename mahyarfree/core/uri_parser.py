"""Share-link -> normalized node specification.

Supports the link formats that Iranian V2Ray subscriptions usually carry:

    vless://   vmess://   trojan://   ss://   ssr://
    hysteria2:// (hy2://)   tuic://   socks://   http(s)://

A parsed node is a plain dict ("spec") that the sing-box / Xray config
generators turn into real outbound objects.  Nothing here touches the
network, which keeps it trivially unit-testable.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_B64_RE = re.compile(r"^[A-Za-z0-9+/\-_=\s]+$")


def b64decode_any(value: str) -> bytes:
    """Decode standard / urlsafe base64 with or without padding."""
    if value is None:
        return b""
    text = value.strip().replace("\n", "").replace("\r", "").replace(" ", "")
    text = text.replace("-", "+").replace("_", "/")
    pad = len(text) % 4
    if pad:
        text += "=" * (4 - pad)
    try:
        return base64.b64decode(text)
    except (binascii.Error, ValueError):
        return b""


def b64decode_text(value: str) -> str:
    raw = b64decode_any(value)
    if not raw:
        return ""
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def looks_like_uri_line(line: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", line.strip()))


def _first(params: Dict[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        if key in params and params[key] not in (None, ""):
            return str(params[key])
    return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, str):
            value = value.strip()
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "t")


def _split_host_port(hostport: str, default_port: int = 443) -> tuple[str, int]:
    hostport = (hostport or "").strip()
    if hostport.startswith("["):                      # [::1]:443
        end = hostport.find("]")
        host = hostport[1:end]
        rest = hostport[end + 1:]
        port = _to_int(rest.lstrip(":"), default_port)
        return host, port
    if hostport.count(":") == 1:
        host, _, port = hostport.partition(":")
        return host, _to_int(port, default_port)
    if ":" in hostport:                                # bare ipv6
        return hostport, default_port
    return hostport, default_port


def node_id(spec: Dict[str, Any]) -> str:
    """Stable id so that favourites/selection survive subscription updates."""
    basis = "|".join(
        str(spec.get(key, ""))
        for key in ("protocol", "server", "port", "uuid", "password", "transport")
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _empty_spec() -> Dict[str, Any]:
    return {
        "protocol": "",
        "name": "",
        "server": "",
        "port": 0,
        "uuid": "",
        "password": "",
        "method": "",
        "alter_id": 0,
        "flow": "",
        "security": "",          # vmess cipher / ss method
        "tls": {
            "enabled": False,
            "sni": "",
            "alpn": [],
            "fingerprint": "",
            "allow_insecure": False,
            "reality": {"enabled": False, "public_key": "", "short_id": "", "spider_x": ""},
        },
        "transport": {
            "type": "tcp",       # tcp | ws | grpc | http | httpupgrade | quic | xhttp | kcp
            "path": "",
            "host": "",
            "service_name": "",
            "headers": {},
            "mode": "",
            "extra": {},
        },
        "sockopt": {},
        "raw": "",
        "extra_params": {},
    }


def _apply_tls(spec: Dict[str, Any], params: Dict[str, str]) -> None:
    security = (_first(params, "security", default="none") or "none").lower()
    tls = spec["tls"]
    if security in ("tls", "xtls", "reality"):
        tls["enabled"] = True
    if security == "reality":
        tls["reality"]["enabled"] = True

    sni = _first(params, "sni", "peer", "host")
    if sni:
        tls["sni"] = sni

    alpn = _first(params, "alpn")
    if alpn:
        tls["alpn"] = [a for a in urllib.parse.unquote(alpn).split(",") if a]

    fp = _first(params, "fp", "fingerprint")
    if fp:
        tls["fingerprint"] = fp

    tls["allow_insecure"] = _to_bool(
        _first(params, "allowInsecure", "insecure", "allow_insecure", default="0")
    )

    if security == "reality":
        pbk = _first(params, "pbk", "publicKey", "public_key")
        sid = _first(params, "sid", "shortId", "short_id")
        spx = _first(params, "spx", "spiderX", "spider_x")
        if pbk:
            tls["reality"]["public_key"] = pbk
        if sid:
            tls["reality"]["short_id"] = sid
        if spx:
            tls["reality"]["spider_x"] = urllib.parse.unquote(spx)
        if not tls["fingerprint"]:
            tls["fingerprint"] = "chrome"


def _apply_transport(spec: Dict[str, Any], params: Dict[str, str]) -> None:
    net = (_first(params, "type", "network", "net", default="tcp") or "tcp").lower()
    tr = spec["transport"]

    if net in ("ws", "websocket"):
        tr["type"] = "ws"
        tr["path"] = urllib.parse.unquote(_first(params, "path", default="/")) or "/"
        tr["host"] = _first(params, "host", "sni")
    elif net in ("grpc", "gun"):
        tr["type"] = "grpc"
        tr["service_name"] = _first(params, "serviceName", "servicename", "path")
        if tr["service_name"].startswith("/"):
            tr["service_name"] = tr["service_name"][1:]
    elif net in ("h2", "http"):
        tr["type"] = "http"
        tr["path"] = urllib.parse.unquote(_first(params, "path", default="/")) or "/"
        tr["host"] = _first(params, "host")
    elif net in ("httpupgrade",):
        tr["type"] = "httpupgrade"
        tr["path"] = urllib.parse.unquote(_first(params, "path", default="/")) or "/"
        tr["host"] = _first(params, "host")
    elif net in ("quic",):
        tr["type"] = "quic"
    elif net in ("xhttp", "splithttp"):
        tr["type"] = "xhttp"
        tr["path"] = urllib.parse.unquote(_first(params, "path", default="/")) or "/"
        tr["host"] = _first(params, "host", "sni")
        tr["mode"] = _first(params, "mode", default="auto")
        extra_raw = _first(params, "extra")
        if extra_raw:
            try:
                tr["extra"] = json.loads(urllib.parse.unquote(extra_raw))
            except Exception:
                tr["extra"] = {}
    elif net in ("kcp", "mkcp"):
        tr["type"] = "kcp"
        tr["path"] = _first(params, "path", "seed")
    elif net in ("tcp", "raw", ""):
        tr["type"] = "tcp"
        header = _first(params, "headerType", "header")
        if header and header != "none":
            tr["headers"] = {"type": header}
    else:
        tr["type"] = net

    # ws / httpupgrade / xhttp early-data
    if tr["type"] == "ws":
        ed = _first(params, "ed", "eh")
        if ed:
            spec["extra_params"]["early_data"] = ed


# --------------------------------------------------------------------------
# per-protocol parsers
# --------------------------------------------------------------------------

def parse_vless(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.hostname:
        return None
    params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}

    spec = _empty_spec()
    spec["protocol"] = "vless"
    spec["uuid"] = urllib.parse.unquote(parsed.username or "")
    spec["server"] = parsed.hostname
    spec["port"] = parsed.port or 443
    spec["name"] = urllib.parse.unquote(parsed.fragment) or f"{spec['server']}:{spec['port']}"
    spec["flow"] = _first(params, "flow")

    _apply_tls(spec, params)
    _apply_transport(spec, params)

    encryption = _first(params, "encryption", default="none")
    if encryption and encryption != "none":
        spec["extra_params"]["encryption"] = encryption

    return spec


def parse_vmess(uri: str) -> Optional[Dict[str, Any]]:
    payload = uri[len("vmess://"):].strip()
    text = b64decode_text(payload)
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    spec = _empty_spec()
    spec["protocol"] = "vmess"
    spec["server"] = str(data.get("add", "")).strip()
    spec["port"] = _to_int(data.get("port"), 443)
    spec["uuid"] = str(data.get("id", "")).strip()
    spec["alter_id"] = _to_int(data.get("aid"), 0)
    spec["security"] = str(data.get("scy") or data.get("security") or "auto").strip() or "auto"
    spec["name"] = str(data.get("ps") or f"{spec['server']}:{spec['port']}")
    if not spec["server"]:
        return None

    tls_mode = str(data.get("tls", "")).lower()
    if tls_mode in ("tls", "reality", "true"):
        spec["tls"]["enabled"] = True
    sni = str(data.get("sni") or data.get("host") or "")
    if sni:
        spec["tls"]["sni"] = sni
    if data.get("alpn"):
        spec["tls"]["alpn"] = [a for a in str(data["alpn"]).split(",") if a]
    if data.get("fp"):
        spec["tls"]["fingerprint"] = str(data["fp"])
    spec["tls"]["allow_insecure"] = _to_bool(data.get("verify_cert"), True) is False and "verify_cert" in data
    if tls_mode == "reality":
        spec["tls"]["reality"]["enabled"] = True
        spec["tls"]["reality"]["public_key"] = str(data.get("pbk", ""))
        spec["tls"]["reality"]["short_id"] = str(data.get("sid", ""))
        spec["tls"]["reality"]["spider_x"] = str(data.get("spx", ""))
        if not spec["tls"]["fingerprint"]:
            spec["tls"]["fingerprint"] = "chrome"

    net = str(data.get("net", "tcp")).lower()
    tr = spec["transport"]
    path = str(data.get("path", "") or "")
    host = str(data.get("host", "") or "")
    if net == "ws":
        tr["type"] = "ws"
        tr["path"] = path or "/"
        tr["host"] = host
    elif net == "grpc":
        tr["type"] = "grpc"
        tr["service_name"] = (str(data.get("path", "")) or "").lstrip("/")
    elif net in ("h2", "http"):
        tr["type"] = "http"
        tr["path"] = path or "/"
        tr["host"] = host
    elif net == "httpupgrade":
        tr["type"] = "httpupgrade"
        tr["path"] = path or "/"
        tr["host"] = host
    elif net == "quic":
        tr["type"] = "quic"
    elif net in ("xhttp", "splithttp"):
        tr["type"] = "xhttp"
        tr["path"] = path or "/"
        tr["host"] = host
        tr["mode"] = str(data.get("mode", "auto") or "auto")
        if isinstance(data.get("extra"), dict):
            tr["extra"] = data["extra"]
    elif net == "kcp":
        tr["type"] = "kcp"
        tr["path"] = path

    return spec


def parse_trojan(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.hostname:
        return None
    params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}

    spec = _empty_spec()
    spec["protocol"] = "trojan"
    spec["password"] = urllib.parse.unquote(parsed.username or "")
    spec["server"] = parsed.hostname
    spec["port"] = parsed.port or 443
    spec["name"] = urllib.parse.unquote(parsed.fragment) or f"{spec['server']}:{spec['port']}"
    spec["tls"]["enabled"] = True

    _apply_tls(spec, params)
    spec["tls"]["enabled"] = True
    _apply_transport(spec, params)

    sni = _first(params, "sni", "peer")
    if sni:
        spec["tls"]["sni"] = sni
    if _first(params, "allowInsecure", "insecure"):
        spec["tls"]["allow_insecure"] = _to_bool(_first(params, "allowInsecure", "insecure"))

    spec["flow"] = _first(params, "flow")
    return spec


def parse_shadowsocks(uri: str) -> Optional[Dict[str, Any]]:
    body = uri[len("ss://"):]
    fragment = ""
    if "#" in body:
        body, _, fragment = body.partition("#")
    query = ""
    if "?" in body:
        body, _, query = body.partition("?")
    params = {k: v[0] for k, v in urllib.parse.parse_qs(query, keep_blank_values=True).items()}

    method = password = ""
    host = ""
    port = 0

    if "@" in body:
        userinfo, _, hostpart = body.rpartition("@")
        decoded = b64decode_text(userinfo)
        if decoded and ":" in decoded:
            method, _, password = decoded.partition(":")
        elif ":" in userinfo:
            method, _, password = userinfo.partition(":")
        else:
            method, _, password = urllib.parse.unquote(userinfo).partition(":")
        host, port = _split_host_port(hostpart, 8388)
    else:
        decoded = b64decode_text(body)
        if not decoded:
            return None
        if "@" not in decoded:
            return None
        userinfo, _, hostpart = decoded.rpartition("@")
        method, _, password = userinfo.partition(":")
        host, port = _split_host_port(hostpart, 8388)

    if not host or not method:
        return None

    spec = _empty_spec()
    spec["protocol"] = "shadowsocks"
    spec["method"] = method
    spec["password"] = password
    spec["server"] = host
    spec["port"] = port or 8388
    spec["name"] = urllib.parse.unquote(fragment) or f"{host}:{port}"

    plugin = _first(params, "plugin")
    if plugin:
        parts = plugin.split(";")
        spec["extra_params"]["plugin"] = parts[0]
        plugin_opts = {}
        for chunk in parts[1:]:
            if "=" in chunk:
                k, _, v = chunk.partition("=")
                plugin_opts[k] = v
            elif chunk:
                plugin_opts[chunk] = "true"
        spec["extra_params"]["plugin_opts"] = plugin_opts

    if _first(params, "udp-over-tcp", "uot"):
        spec["extra_params"]["udp_over_tcp"] = True

    return spec


def parse_ssr(uri: str) -> Optional[Dict[str, Any]]:
    payload = b64decode_text(uri[len("ssr://"):].strip())
    if not payload:
        return None
    parts = payload.split(":")
    if len(parts) < 6:
        return None
    host, port, protocol, method, obfs, password_b64 = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
    password = b64decode_text(password_b64) or password_b64
    query = ""
    if "/?" in password_b64:
        password_b64, _, query = password_b64.partition("/?")
        password = b64decode_text(password_b64) or password_b64
    params = {}
    if query:
        for pair in query.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                params[k] = b64decode_text(v) or v

    spec = _empty_spec()
    spec["protocol"] = "shadowsocksr"
    spec["server"] = host
    spec["port"] = _to_int(port, 8388)
    spec["method"] = method
    spec["password"] = password
    spec["name"] = params.get("remarks") or f"{host}:{port}"
    spec["extra_params"].update({
        "ssr_protocol": protocol,
        "ssr_obfs": obfs,
        "ssr_protocol_param": params.get("protoparam", ""),
        "ssr_obfs_param": params.get("obfsparam", ""),
    })
    return spec


def parse_hysteria2(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.hostname:
        return None
    params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}

    spec = _empty_spec()
    spec["protocol"] = "hysteria2"
    spec["server"] = parsed.hostname
    spec["port"] = parsed.port or 443
    spec["password"] = urllib.parse.unquote(parsed.username or "")
    if parsed.password:
        spec["password"] = f"{spec['password']}:{urllib.parse.unquote(parsed.password)}"
    spec["name"] = urllib.parse.unquote(parsed.fragment) or f"{spec['server']}:{spec['port']}"
    spec["tls"]["enabled"] = True
    spec["tls"]["allow_insecure"] = _to_bool(_first(params, "insecure", "allowInsecure", default="0"))
    sni = _first(params, "sni", "peer")
    if sni:
        spec["tls"]["sni"] = sni
    if _first(params, "alpn"):
        spec["tls"]["alpn"] = [a for a in urllib.parse.unquote(_first(params, "alpn")).split(",") if a]

    spec["extra_params"].update({
        "obfs": _first(params, "obfs"),
        "obfs_password": _first(params, "obfs-password", "obfs_password"),
        "up": _first(params, "up", "upmbps"),
        "down": _first(params, "down", "downmbps"),
    })
    return spec


def parse_tuic(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.hostname:
        return None
    params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}

    spec = _empty_spec()
    spec["protocol"] = "tuic"
    spec["server"] = parsed.hostname
    spec["port"] = parsed.port or 443
    spec["uuid"] = urllib.parse.unquote(parsed.username or "")
    spec["password"] = urllib.parse.unquote(parsed.password or "")
    spec["name"] = urllib.parse.unquote(parsed.fragment) or f"{spec['server']}:{spec['port']}"
    spec["tls"]["enabled"] = True
    spec["tls"]["allow_insecure"] = _to_bool(_first(params, "allow_insecure", "insecure", default="0"))
    sni = _first(params, "sni", "peer")
    if sni:
        spec["tls"]["sni"] = sni
    if _first(params, "alpn"):
        spec["tls"]["alpn"] = [a for a in urllib.parse.unquote(_first(params, "alpn")).split(",") if a]

    spec["extra_params"].update({
        "congestion_control": _first(params, "congestion_control", "congestion"),
        "udp_relay_mode": _first(params, "udp_relay_mode"),
    })
    return spec


def parse_socks_http(uri: str) -> Optional[Dict[str, Any]]:
    parsed = urllib.parse.urlsplit(uri)
    if not parsed.hostname:
        return None
    scheme = parsed.scheme.lower()
    spec = _empty_spec()
    spec["protocol"] = "socks" if scheme.startswith("socks") else "http"
    spec["server"] = parsed.hostname
    spec["port"] = parsed.port or (1080 if spec["protocol"] == "socks" else 8080)
    spec["uuid"] = urllib.parse.unquote(parsed.username or "")
    spec["password"] = urllib.parse.unquote(parsed.password or "")
    spec["name"] = urllib.parse.unquote(parsed.fragment) or f"{spec['server']}:{spec['port']}"
    return spec


PARSERS = {
    "vless": parse_vless,
    "vmess": parse_vmess,
    "trojan": parse_trojan,
    "trojan-go": parse_trojan,
    "ss": parse_shadowsocks,
    "ssr": parse_ssr,
    "hysteria2": parse_hysteria2,
    "hy2": parse_hysteria2,
    "tuic": parse_tuic,
    "socks": parse_socks_http,
    "socks5": parse_socks_http,
    "http": parse_socks_http,
    "https": parse_socks_http,
}


def parse_uri(uri: str) -> Optional[Dict[str, Any]]:
    uri = (uri or "").strip()
    if not uri or "://" not in uri:
        return None
    scheme = uri.split("://", 1)[0].lower()
    parser = PARSERS.get(scheme)
    if parser is None:
        return None
    try:
        spec = parser(uri)
    except Exception:
        return None
    if not spec or not spec.get("server"):
        return None

    # normalise a couple of protocol specific quirks
    if spec["protocol"] == "vless" and spec["transport"]["type"] == "ws":
        # ws over reality is unusual but legal; keep as-is
        pass

    spec["raw"] = uri
    spec["id"] = node_id(spec)
    spec["name"] = (spec.get("name") or "").strip() or f"{spec['server']}:{spec['port']}"
    return spec


def sniff_core(spec: Dict[str, Any]) -> str:
    """Pick the engine that can actually run this node."""
    tr = spec.get("transport", {})
    ttype = tr.get("type", "tcp")
    if ttype in ("xhttp", "kcp"):
        return "xray"
    if spec.get("protocol") == "shadowsocksr":
        return "xray"
    if ttype == "quic":
        return "sing-box"
    if spec.get("extra_params", {}).get("plugin"):
        return "sing-box"
    return "sing-box"


def parse_subscription_text(text: str) -> List[Dict[str, Any]]:
    """Parse any subscription payload: plain list, base64 blob or JSON."""
    if not text:
        return []

    stripped = text.strip()

    # 1) JSON subscription (some panels return a JSON array of links)
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            data = json.loads(stripped)
            items: List[str] = []
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, str):
                        items.append(entry)
                    elif isinstance(entry, dict):
                        items.append(json.dumps(entry))
            elif isinstance(data, dict):
                for value in data.values():
                    if isinstance(value, list):
                        items.extend(str(v) for v in value)
            text = "\n".join(items)
        except Exception:
            pass

    # 2) whole-body base64 (classic v2ray subscription)
    if not looks_like_uri_line(text.splitlines()[0] if text.splitlines() else ""):
        decoded = b64decode_text(text)
        if decoded and "://" in decoded:
            text = decoded

    specs: List[Dict[str, Any]] = []
    seen = set()
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # a line may itself be base64 encoded
        if not looks_like_uri_line(line) and _B64_RE.match(line) and len(line) > 24:
            candidate = b64decode_text(line)
            if candidate and "://" in candidate:
                line = candidate.strip()
        spec = parse_uri(line)
        if spec is None:
            continue
        key = (spec["server"], spec["port"], spec["protocol"], spec.get("uuid") or spec.get("password"))
        if key in seen:
            continue
        seen.add(key)
        specs.append(spec)
    return specs


def humanize_name(name: str) -> str:
    """Strip noisy panel prefixes and normalise spacing for the UI."""
    clean = re.sub(r"[\u200b-\u200f\u202a-\u202e]", "", name or "").strip()
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean or "Server"


def guess_country(name: str, server: str = "") -> str:
    """Best-effort country flag from the node name (emoji or keywords)."""
    text = f"{name} {server}"
    flags = re.findall(r"[\U0001F1E6-\U0001F1FF]{2}", name or "")
    if flags:
        return flags[0]
    lowered = text.lower()
    table = {
        "🇮🇷": ("iran", "tehran", "ایران", "تهران", "mci", "irancell", "shatel"),
        "🇩🇪": ("germany", "frankfurt", "de-", "آلمان", "فرانکفورت"),
        "🇳🇱": ("netherlands", "amsterdam", "holland", "هلند", "آمستردام"),
        "🇫🇮": ("finland", "helsinki", "فنلاند"),
        "🇸🇪": ("sweden", "stockholm", "سوئد"),
        "🇬🇧": ("england", "london", "uk", "britain", "انگلیس", "لندن"),
        "🇺🇸": ("united states", "america", "usa", "us-", "dallas", "seattle", "آمریکا"),
        "🇫🇷": ("france", "paris", "فرانسه", "پاریس"),
        "🇹🇷": ("turkey", "istanbul", "ترکیه", "استانبول"),
        "🇦🇪": ("emirates", "dubai", "امارات", "دبی"),
        "🇷🇺": ("russia", "moscow", "روسیه", "مسکو"),
        "🇮🇳": ("india", "mumbai", "هند"),
        "🇸🇬": ("singapore", "سنگاپور"),
        "🇯🇵": ("japan", "tokyo", "ژاپن"),
        "🇨🇦": ("canada", "toronto", "کانادا"),
        "🇵🇱": ("poland", "warsaw", "لهستان"),
        "🇦🇹": ("austria", "vienna", "اتریش"),
        "🇨🇭": ("switzerland", "zurich", "سوئیس"),
        "🇮🇹": ("italy", "milan", "ایتالیا"),
        "🇪🇸": ("spain", "madrid", "اسپانیا"),
        "🇦🇲": ("armenia", "ارمنستان"),
        "🇱🇹": ("lithuania", "لیتوانی"),
        "🇱🇻": ("latvia", "لتونی"),
        "🇪🇪": ("estonia", "استونی"),
        "🇷🇴": ("romania", "رومانی"),
        "🇧🇬": ("bulgaria", "بلغارستان"),
        "🇭🇺": ("hungary", "مجارستان"),
        "🇨🇿": ("czech", "praha", "چک"),
        "🇺🇦": ("ukraine", "اوکراین"),
        "🇦🇺": ("australia", "سیدنی", "استرالیا"),
        "🇧🇷": ("brazil", "برزیل"),
        "🇭🇰": ("hong kong", "hongkong", "هنگ کنگ"),
        "🇰🇷": ("korea", "seoul", "کره"),
        "🇨🇳": ("china", "shanghai", "چین"),
    }
    for flag, keys in table.items():
        if any(k in lowered for k in keys):
            return flag
    return "🌐"


_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")


def strip_flags(name: str) -> str:
    """Remove emoji flags from a display name (the UI shows them separately)."""
    cleaned = _FLAG_RE.sub(" ", name or "")
    cleaned = re.sub(r"[\s\-_|•]+", " ", cleaned).strip(" -_|•")
    return cleaned or (name or "").strip()


def is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
