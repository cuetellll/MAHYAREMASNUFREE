"""Build a complete sing-box runtime configuration from a node spec."""

from __future__ import annotations

from typing import Any, Dict, List

from . import rules

# --------------------------------------------------------------------------
# outbound construction
# --------------------------------------------------------------------------


def _tls_block(spec: Dict[str, Any], *, force: bool = False, fragment: bool = False) -> Dict[str, Any] | None:
    tls = spec.get("tls") or {}
    enabled = bool(tls.get("enabled")) or force
    if not enabled:
        return None
    block: Dict[str, Any] = {"enabled": True}
    server = spec.get("server", "")
    sni = tls.get("sni") or ""
    if not sni:
        # SNI must never be a bare IP address
        sni = "" if _is_ip(server) else server
    if sni:
        block["server_name"] = sni
    if tls.get("alpn"):
        block["alpn"] = list(tls["alpn"])
    if tls.get("allow_insecure"):
        block["insecure"] = True
    fp = tls.get("fingerprint")
    if fp:
        block["utls"] = {"enabled": True, "fingerprint": fp}

    reality = tls.get("reality") or {}
    if reality.get("enabled") and reality.get("public_key"):
        block["reality"] = {
            "enabled": True,
            "public_key": reality["public_key"],
            "short_id": reality.get("short_id", ""),
        }
        if reality.get("spider_x"):
            block["reality"]["spider_x"] = reality["spider_x"]
        block.setdefault("utls", {"enabled": True, "fingerprint": fp or "chrome"})

    if fragment:
        block["fragment"] = True
        block["fragment_fallback_delay"] = "500ms"
    return block


def _is_ip(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _dns_server(tag: str, address: str, detour: str) -> Dict[str, Any]:
    """Convert a DoH/DoT/UDP address into the sing-box >=1.12 DNS server shape."""
    address = (address or "").strip()
    lowered = address.lower()
    entry: Dict[str, Any] = {"tag": tag, "detour": detour}

    if lowered.startswith("https://"):
        rest = address[8:]
        host, _, path = rest.partition("/")
        entry["type"] = "https"
        entry["server"] = host
        if path:
            entry["path"] = "/" + path
    elif lowered.startswith("tls://"):
        entry["type"] = "tls"
        entry["server"] = address[6:]
    elif lowered.startswith("quic://"):
        entry["type"] = "quic"
        entry["server"] = address[7:]
    elif lowered.startswith("h3://"):
        entry["type"] = "h3"
        entry["server"] = address[5:]
    elif lowered.startswith("tcp://"):
        entry["type"] = "tcp"
        entry["server"] = address[6:]
    elif lowered.startswith("udp://"):
        entry["type"] = "udp"
        entry["server"] = address[6:]
    elif lowered.startswith("dhcp://"):
        entry["type"] = "dhcp"
        server = address[7:]
        if server:
            entry["server"] = server
    else:
        entry["type"] = "udp"
        entry["server"] = address
    return entry


def _transport_block(spec: Dict[str, Any]) -> Dict[str, Any] | None:
    tr = spec.get("transport") or {}
    ttype = tr.get("type", "tcp")
    host = tr.get("host") or ""
    if ttype == "ws":
        block: Dict[str, Any] = {"type": "ws", "path": tr.get("path") or "/"}
        if host:
            block["headers"] = {"Host": host}
        early = (spec.get("extra_params") or {}).get("early_data")
        if early:
            try:
                block["max_early_data"] = int(early)
                block["early_data_header_name"] = "Sec-WebSocket-Protocol"
            except ValueError:
                pass
        return block
    if ttype == "grpc":
        return {"type": "grpc", "service_name": tr.get("service_name", "")}
    if ttype == "http":
        block = {"type": "http", "path": tr.get("path") or "/"}
        if host:
            block["host"] = [host]
        return block
    if ttype == "httpupgrade":
        block = {"type": "httpupgrade", "path": tr.get("path") or "/"}
        if host:
            block["host"] = host
        return block
    if ttype == "quic":
        return {"type": "quic"}
    return None


def build_outbound(spec: Dict[str, Any], tag: str = "proxy", settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    settings = settings or {}
    protocol = spec.get("protocol", "")
    fragment = bool(settings.get("fragment"))
    mux = bool(settings.get("mux"))

    out: Dict[str, Any] = {
        "tag": tag,
        "server": spec.get("server", ""),
        "server_port": int(spec.get("port") or 443),
    }

    tls = _tls_block(spec, fragment=fragment)
    transport = _transport_block(spec)
    extra = spec.get("extra_params") or {}

    if protocol == "vless":
        out["type"] = "vless"
        out["uuid"] = spec.get("uuid", "")
        if spec.get("flow"):
            out["flow"] = spec["flow"]
        if tls:
            out["tls"] = tls
        if transport:
            out["transport"] = transport

    elif protocol == "vmess":
        out["type"] = "vmess"
        out["uuid"] = spec.get("uuid", "")
        out["security"] = spec.get("security") or "auto"
        out["alter_id"] = int(spec.get("alter_id") or 0)
        if tls:
            out["tls"] = tls
        if transport:
            out["transport"] = transport

    elif protocol == "trojan":
        out["type"] = "trojan"
        out["password"] = spec.get("password", "")
        if spec.get("flow"):
            out["flow"] = spec["flow"]
        out["tls"] = tls or {"enabled": True, "server_name": spec.get("server", "")}
        if transport:
            out["transport"] = transport

    elif protocol == "shadowsocks":
        out["type"] = "shadowsocks"
        out["method"] = spec.get("method", "")
        out["password"] = spec.get("password", "")
        if extra.get("plugin"):
            out["plugin"] = extra["plugin"]
            opts = extra.get("plugin_opts") or {}
            if opts:
                out["plugin_opts"] = ";".join(f"{k}={v}" for k, v in opts.items())
        if extra.get("udp_over_tcp"):
            out["udp_over_tcp"] = True

    elif protocol == "hysteria2":
        out["type"] = "hysteria2"
        out["password"] = spec.get("password", "")
        out["tls"] = tls or {"enabled": True}
        obfs = extra.get("obfs")
        if obfs:
            out["obfs"] = {"type": obfs, "password": extra.get("obfs_password", "")}
        for key, field in (("up", "up_mbps"), ("down", "down_mbps")):
            if extra.get(key):
                try:
                    out[field] = int(float(extra[key]))
                except ValueError:
                    pass

    elif protocol == "tuic":
        out["type"] = "tuic"
        out["uuid"] = spec.get("uuid", "")
        out["password"] = spec.get("password", "")
        out["tls"] = tls or {"enabled": True}
        if extra.get("congestion_control"):
            out["congestion_control"] = extra["congestion_control"]
        if extra.get("udp_relay_mode"):
            out["udp_relay_mode"] = extra["udp_relay_mode"]

    elif protocol == "socks":
        out["type"] = "socks"
        out["version"] = "5"
        if spec.get("uuid"):
            out["username"] = spec["uuid"]
            out["password"] = spec.get("password", "")

    elif protocol == "http":
        out["type"] = "http"
        if spec.get("uuid"):
            out["username"] = spec["uuid"]
            out["password"] = spec.get("password", "")

    else:
        raise ValueError(f"unsupported protocol for sing-box: {protocol}")

    if mux:
        out["multiplex"] = {
            "enabled": True,
            "protocol": "h2mux",
            "max_streams": int(settings.get("mux_concurrency") or 8),
            "padding": True,
        }

    return out


# --------------------------------------------------------------------------
# full config
# --------------------------------------------------------------------------

def build_config(
    specs: List[Dict[str, Any]],
    active_id: str,
    settings: Dict[str, Any],
    *,
    log_path: str = "",
    cache_path: str = "",
) -> Dict[str, Any]:
    mode = settings.get("mode", "system-proxy")
    routing = settings.get("routing", "rule")
    socks_port = int(settings.get("socks_port", 20808))
    http_port = int(settings.get("http_port", 20809))
    clash_port = int(settings.get("clash_port", 20810))

    active = next((s for s in specs if s.get("id") == active_id), None)
    if active is None and specs:
        active = specs[0]
    if active is None:
        raise ValueError("no servers available")

    # ---------------------------------------------------------- outbounds
    outbounds: List[Dict[str, Any]] = [build_outbound(active, "proxy", settings)]
    # NOTE: the tag must not be "direct"; sing-box refuses a DNS `detour` that
    # points at an "empty" direct outbound, so give it one harmless dial option.
    outbounds.append({"type": "direct", "tag": "bypass", "udp_fragment": True})
    # sing-box 1.11+ : reject is an action, but a block outbound is still handy
    outbounds.append({"type": "block", "tag": "block"})

    for spec in specs:
        if spec.get("id") == active.get("id"):
            continue
        try:
            outbounds.append(build_outbound(spec, f"node::{spec['id']}", settings))
        except Exception:
            continue

    node_tags = [f"node::{s['id']}" for s in specs if s.get("id") != active.get("id")]

    if node_tags:
        outbounds.append({
            "type": "urltest",
            "tag": "auto",
            "outbounds": ["proxy", *node_tags],
            "url": "http://cp.cloudflare.com/generate_204",
            "interval": "3m",
            "tolerance": 50,
            "idle_timeout": "30m",
        })
    outbounds.append({
        "type": "selector",
        "tag": "select",
        "outbounds": (["proxy"] + (["auto"] if node_tags else []) + ["bypass"]),
        "default": "proxy",
        "interrupt_exist_connections": False,
    })

    # ----------------------------------------------------------- inbounds
    inbounds: List[Dict[str, Any]] = [{
        "type": "mixed",
        "tag": "mixed-in",
        "listen": "127.0.0.1",
        "listen_port": socks_port,
    }]
    if http_port and http_port != socks_port:
        inbounds.append({
            "type": "http",
            "tag": "http-in",
            "listen": "127.0.0.1",
            "listen_port": http_port,
        })
    if mode == "tun":
        inbounds.append({
            "type": "tun",
            "tag": "tun-in",
            "interface_name": "mahyarfree",
            "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
            "mtu": 9000,
            "auto_route": True,
            "strict_route": True,
            "stack": "mixed",
            "endpoint_independent_nat": False,
        })

    # ---------------------------------------------------------------- dns
    dns: Dict[str, Any] = {
        "servers": [
            _dns_server("dns-remote", settings.get("dns_remote") or "https://1.1.1.1/dns-query", "proxy"),
            _dns_server("dns-direct", settings.get("dns_direct") or "https://223.5.5.5/dns-query", "bypass"),
        ],
        "rules": [
            {"domain_suffix": rules.IRAN_DOMAINS, "server": "dns-direct"},
        ],
        "final": "dns-remote",
        "strategy": "prefer_ipv4",
    }

    # -------------------------------------------------------------- route
    route_rules: List[Dict[str, Any]] = [{"action": "sniff"}]
    if settings.get("dns_hijack", True):
        route_rules.append({"protocol": "dns", "action": "hijack-dns"})
    route_rules.append({"ip_is_private": True, "outbound": "bypass"})
    route_rules.append({"domain_suffix": [".lan", ".local", ".localdomain"], "outbound": "bypass"})
    route_rules.append({"ip_cidr": ["224.0.0.0/4", "255.255.255.255/32"], "outbound": "bypass"})
    # never send the local resolver itself through the tunnel
    route_rules.append({"ip_cidr": ["223.5.5.5/32", "119.29.29.29/32", "1.0.0.1/32"], "outbound": "bypass"})

    if routing == "rule":
        if settings.get("block_ads", True):
            route_rules.append({"domain_suffix": rules.AD_DOMAINS, "action": "reject"})
        route_rules.append({"domain_suffix": rules.IRAN_DOMAINS, "outbound": "bypass"})
        route_rules.append({"domain_keyword": rules.IRAN_KEYWORDS, "outbound": "bypass"})
        route_rules.append({"ip_cidr": rules.IRAN_CIDRS, "outbound": "bypass"})

    final_outbound = "bypass" if routing == "direct" else "select"

    route: Dict[str, Any] = {
        "rules": route_rules,
        "final": final_outbound,
        "auto_detect_interface": True,
        "default_domain_resolver": {"server": "dns-direct"},
    }
    if mode == "tun":
        route["auto_detect_interface"] = True

    config: Dict[str, Any] = {
        "log": {
            "level": settings.get("log_level", "warn"),
            "timestamp": True,
            **({"output": log_path} if log_path else {}),
        },
        "dns": dns,
        "inbounds": inbounds,
        "outbounds": outbounds,
        "route": route,
        "experimental": {
            "clash_api": {"external_controller": f"127.0.0.1:{clash_port}"},
            **({
                "cache_file": {"enabled": True, "path": cache_path, "store_fakeip": False}
            } if cache_path else {}),
        },
    }
    return config
