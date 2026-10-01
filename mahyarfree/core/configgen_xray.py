"""Xray-core fallback engine.

sing-box is the primary engine, but a few transports that Iranian panels love
(notably ``xhttp``/``splithttp`` and mKCP) are only implemented in Xray-core,
so those nodes are handed to this generator instead.
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import rules


def _is_ip(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _domain_rules() -> List[str]:
    """Iranian domains expressed in Xray's inline ``domain:`` rule syntax."""
    out: List[str] = ["regexp:.*\\.ir$"]
    for domain in rules.IRAN_DOMAINS:
        if domain.startswith("."):
            continue
        out.append(f"domain:{domain}")
    return out


def _stream_settings(spec: Dict[str, Any]) -> Dict[str, Any]:
    tr = spec.get("transport") or {}
    tls = spec.get("tls") or {}
    ttype = tr.get("type", "tcp")
    host = tr.get("host") or ""
    stream: Dict[str, Any] = {}

    if ttype == "ws":
        stream["network"] = "ws"
        ws: Dict[str, Any] = {"path": tr.get("path") or "/"}
        if host:
            ws["host"] = host
        early = (spec.get("extra_params") or {}).get("early_data")
        if early:
            try:
                ws["maxEarlyData"] = int(early)
                ws["earlyDataHeaderName"] = "Sec-WebSocket-Protocol"
            except ValueError:
                pass
        stream["wsSettings"] = ws
    elif ttype == "grpc":
        stream["network"] = "grpc"
        stream["grpcSettings"] = {
            "serviceName": tr.get("service_name", ""),
            "multiMode": False,
        }
    elif ttype in ("http", "h2"):
        stream["network"] = "h2"
        h2: Dict[str, Any] = {"path": tr.get("path") or "/"}
        if host:
            h2["host"] = [host]
        stream["httpSettings"] = h2
    elif ttype == "httpupgrade":
        stream["network"] = "httpupgrade"
        hu: Dict[str, Any] = {"path": tr.get("path") or "/"}
        if host:
            hu["host"] = host
        stream["httpupgradeSettings"] = hu
    elif ttype in ("xhttp", "splithttp"):
        stream["network"] = "xhttp"
        xhttp: Dict[str, Any] = {"path": tr.get("path") or "/", "mode": tr.get("mode") or "auto"}
        if host:
            xhttp["host"] = host
        extra = tr.get("extra") or {}
        if extra:
            xhttp["extra"] = extra
        stream["xhttpSettings"] = xhttp
    elif ttype == "kcp":
        stream["network"] = "kcp"
        stream["kcpSettings"] = {
            "mtu": 1350, "tti": 50, "uplinkCapacity": 12, "downlinkCapacity": 100,
            "congestion": False, "readBufferSize": 2, "writeBufferSize": 2,
            "header": {"type": "none"},
            "seed": tr.get("path") or None,
        }
    else:
        stream["network"] = "tcp"
        header = (tr.get("headers") or {}).get("type")
        if header and header != "none":
            stream["tcpSettings"] = {"header": {"type": header}}

    # ------------------------------------------------------------- security
    reality = tls.get("reality") or {}
    sni = tls.get("sni") or ("" if _is_ip(spec.get("server", "")) else spec.get("server", ""))

    if reality.get("enabled") and reality.get("public_key"):
        stream["security"] = "reality"
        reality_settings: Dict[str, Any] = {
            "serverName": sni or host or spec.get("server", ""),
            "fingerprint": tls.get("fingerprint") or "chrome",
            "publicKey": reality["public_key"],
            "shortId": reality.get("short_id", ""),
            "spiderX": reality.get("spider_x") or "/",
        }
        if tls.get("allow_insecure"):
            reality_settings["allowInsecure"] = True
        stream["realitySettings"] = reality_settings
    elif tls.get("enabled"):
        stream["security"] = "tls"
        tls_settings: Dict[str, Any] = {}
        if sni:
            tls_settings["serverName"] = sni
        if tls.get("alpn"):
            tls_settings["alpn"] = list(tls["alpn"])
        if tls.get("fingerprint"):
            tls_settings["fingerprint"] = tls["fingerprint"]
        if tls.get("allow_insecure"):
            tls_settings["allowInsecure"] = True
        stream["tlsSettings"] = tls_settings
    else:
        stream["security"] = "none"

    return stream


def _outbound_object(spec: Dict[str, Any], tag: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    protocol = spec.get("protocol", "")
    server = spec.get("server", "")
    port = int(spec.get("port") or 443)
    extra = spec.get("extra_params") or {}

    outbound: Dict[str, Any] = {"tag": tag, "streamSettings": _stream_settings(spec)}

    if protocol == "vless":
        user: Dict[str, Any] = {"id": spec.get("uuid", ""), "encryption": "none"}
        if spec.get("flow"):
            user["flow"] = spec["flow"]
        outbound["protocol"] = "vless"
        outbound["settings"] = {"vnext": [{"address": server, "port": port, "users": [user]}]}
    elif protocol == "vmess":
        outbound["protocol"] = "vmess"
        outbound["settings"] = {"vnext": [{
            "address": server, "port": port,
            "users": [{
                "id": spec.get("uuid", ""),
                "alterId": int(spec.get("alter_id") or 0),
                "security": spec.get("security") or "auto",
            }],
        }]}
    elif protocol == "trojan":
        outbound["protocol"] = "trojan"
        outbound["settings"] = {"servers": [{"address": server, "port": port, "password": spec.get("password", "")}]}
    elif protocol == "shadowsocks":
        outbound["protocol"] = "shadowsocks"
        outbound["settings"] = {"servers": [{
            "address": server, "port": port,
            "method": spec.get("method", ""), "password": spec.get("password", ""),
            "uot": bool(extra.get("udp_over_tcp")),
        }]}
    elif protocol == "shadowsocksr":
        outbound["protocol"] = "shadowsocks"
        outbound["settings"] = {"servers": [{
            "address": server, "port": port,
            "method": spec.get("method", ""), "password": spec.get("password", ""),
            "protocol": extra.get("ssr_protocol", "origin"),
            "protocolParam": extra.get("ssr_protocol_param", ""),
            "obfs": extra.get("ssr_obfs", "plain"),
            "obfsParam": extra.get("ssr_obfs_param", ""),
        }]}
    elif protocol == "socks":
        outbound["protocol"] = "socks"
        outbound["settings"] = {"servers": [{
            "address": server, "port": port,
            "users": ([{"user": spec.get("uuid", ""), "pass": spec.get("password", "")}]
                      if spec.get("uuid") else []),
        }]}
    elif protocol == "http":
        outbound["protocol"] = "http"
        outbound["settings"] = {"servers": [{
            "address": server, "port": port,
            "users": ([{"user": spec.get("uuid", ""), "pass": spec.get("password", "")}]
                      if spec.get("uuid") else []),
        }]}
    else:
        raise ValueError(f"unsupported protocol for xray: {protocol}")

    if settings.get("mux"):
        outbound["mux"] = {
            "enabled": True,
            "concurrency": int(settings.get("mux_concurrency") or 8),
            "xudpConcurrency": 16,
        }

    if settings.get("fragment"):
        outbound.setdefault("streamSettings", {})["sockopt"] = {
            "dialerProxy": "", "tcpNoDelay": True,
            "tcpFastOpen": False, "domainStrategy": "UseIP",
        }
    return outbound


def build_config(
    specs: List[Dict[str, Any]],
    active_id: str,
    settings: Dict[str, Any],
    *,
    log_path: str = "",
    cache_path: str = "",
) -> Dict[str, Any]:
    routing = settings.get("routing", "rule")
    socks_port = int(settings.get("socks_port", 20808))
    http_port = int(settings.get("http_port", 20809))

    active = next((s for s in specs if s.get("id") == active_id), None)
    if active is None and specs:
        active = specs[0]
    if active is None:
        raise ValueError("no servers available")

    outbounds: List[Dict[str, Any]] = [_outbound_object(active, "proxy", settings)]
    outbounds.append({"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIP"}})
    outbounds.append({"tag": "block", "protocol": "blackhole", "settings": {"response": {"type": "http"}}})

    inbounds: List[Dict[str, Any]] = [
        {
            "tag": "socks-in",
            "listen": "127.0.0.1",
            "port": socks_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True, "userLevel": 0},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": False},
        },
        {
            "tag": "http-in",
            "listen": "127.0.0.1",
            "port": http_port,
            "protocol": "http",
            "settings": {"allowTransparent": False, "userLevel": 0},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": False},
        },
    ]

    routing_rules: List[Dict[str, Any]] = [
        {"type": "field", "port": "53", "outboundTag": "direct"},
        {"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"},
        {"type": "field", "ip": ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                 "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10"],
         "outboundTag": "direct"},
        {"type": "field", "domain": _domain_rules(), "ip": rules.IRAN_CIDRS, "outboundTag": "direct"},
    ]
    if routing == "rule" and settings.get("block_ads", True):
        routing_rules.insert(0, {"type": "field", "domain": [f"domain:{d}" for d in rules.AD_DOMAINS],
                                 "outboundTag": "block"})

    final_tag = "direct" if routing == "direct" else "proxy"

    config: Dict[str, Any] = {
        "log": {"loglevel": settings.get("log_level", "warning"), "access": ""},
        "dns": {
            "servers": [
                {"address": "223.5.5.5", "domains": _domain_rules()},
                {"address": settings.get("dns_remote") or "https://1.1.1.1/dns-query"},
                "1.1.1.1",
            ],
            "queryStrategy": "UseIPv4",
        },
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": routing_rules,
            "balancers": [],
        },
        "policy": {
            "levels": {"0": {"handshake": 4, "connIdle": 300, "uplinkOnly": 2, "downlinkOnly": 5}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True, "statsOutboundUplink": True, "statsOutboundDownlink": True},
        },
        "stats": {},
        "api": {"tag": "api", "services": ["StatsService"]},
    }
    if routing != "direct":
        config["routing"]["rules"].append({"type": "field", "network": "tcp,udp", "outboundTag": final_tag})
    return config
