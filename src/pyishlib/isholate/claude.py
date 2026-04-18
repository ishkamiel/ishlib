# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""isholate-specific ``--claude`` and ``--claude-base`` support.

This module owns everything related to the ``--claude`` / ``--claude-base``
flags: mounting host Claude configuration into the container, and the
host-side network isolation machinery (Incus managed bridge + ipset +
iptables + systemd unit) used by ``--no-network --claude``.

Kept out of :mod:`pyishlib.container` on purpose — the container backend
is tool-agnostic; anything that is specific to the Claude API lives here.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..container import incus as _incus
from ..container.incus import IncusContainer

log = logging.getLogger(__name__)


def _say(msg: str, *, quiet: bool = False) -> None:  # noqa: ARG001
    """Log an isholate progress message at INFO level.

    ``quiet`` is accepted for backwards compatibility and ignored — level
    filtering is done by the logging handler configured in
    :func:`~pyishlib.isholate.cli.main`.
    """
    log.info(msg)


# ---------------------------------------------------------------------------
# Claude mount helpers
# ---------------------------------------------------------------------------


def _add_claude_mounts(
    name: str, home: Path, username: str, *, quiet: bool = False
) -> None:
    """Mount the host's Claude config (``~/.claude/`` and ``~/.claude.json``).

    Adds read-write disk devices with ``shift=true`` so the in-container
    user can read and write the host user's Claude credentials and state.
    Either source can be missing; only existing paths are mounted.
    """
    container = IncusContainer(name)
    mounted: List[str] = []

    claude_dir = home / ".claude"
    if claude_dir.is_dir():
        container.add_mount(
            "isholate-claude",
            claude_dir,
            f"/home/{username}/.claude",
            shift=True,
        )
        mounted.append(str(claude_dir))

    claude_json = home / ".claude.json"
    if claude_json.is_file():
        container.add_mount(
            "isholate-claude-json",
            claude_json,
            f"/home/{username}/.claude.json",
            shift=True,
        )
        mounted.append(str(claude_json))

    if mounted:
        _say(f"exposing host Claude config: {', '.join(mounted)}", quiet=quiet)
    else:
        _say(
            "warning: --claude requested but no host Claude config found "
            "(~/.claude or ~/.claude.json)",
            quiet=quiet,
        )


# Fields copied verbatim from the host's ``~/.claude.json`` into the
# synthesised in-container copy.  ``oauthAccount`` is the field Claude Code
# actually uses to decide "the user is logged in"; the others suppress
# first-run prompts without leaking session / project state.
_CLAUDE_JSON_AUTH_ALLOWLIST: "tuple[str, ...]" = (
    "oauthAccount",
    "userID",
    "firstStartTime",
)


def _build_minimal_claude_json(home: Path) -> Optional[Dict[str, Any]]:
    """Return a minimal ``.claude.json`` payload for ``--claude-base``.

    Reads the host's ``~/.claude.json`` and returns only the auth-identity
    fields from :data:`_CLAUDE_JSON_AUTH_ALLOWLIST`, plus a hard-coded
    ``hasCompletedOnboarding=True`` so the container skips onboarding.

    Returns ``None`` when the host file is missing, unparsable, or lacks
    an ``oauthAccount`` — in all three cases the container cannot be made
    to recognise the credentials and the caller should warn instead.
    """
    src = home / ".claude.json"
    if not src.is_file():
        return None
    try:
        with open(src, encoding="utf-8") as f:
            host_cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(host_cfg, dict):
        return None
    if not isinstance(host_cfg.get("oauthAccount"), dict):
        return None

    minimal: Dict[str, Any] = {"hasCompletedOnboarding": True}
    for key in _CLAUDE_JSON_AUTH_ALLOWLIST:
        if key in host_cfg:
            minimal[key] = host_cfg[key]
    return minimal


def _push_minimal_claude_json(
    container: IncusContainer,
    username: str,
    container_uid: int,
    data: Dict[str, Any],
) -> bool:
    """Serialise *data* and push it to ``/home/{username}/.claude.json``.

    Writes the file owned by the container user's uid/gid (gid mirrors uid
    to match the common Ubuntu ``useradd -m`` default) with mode 0600.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".claude.json", delete=False
    ) as tmp:
        json.dump(data, tmp, indent=2)
        tmp_path = Path(tmp.name)
    try:
        return container.push_file(
            tmp_path,
            f"/home/{username}/.claude.json",
            uid=container_uid,
            gid=container_uid,
            mode=0o600,
        )
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _install_claude_base_auth(
    name: str,
    home: Path,
    username: str,
    container_uid: int,
    *,
    quiet: bool = False,
) -> None:
    """Set up minimal Claude auth inside an ephemeral container.

    Mounts ``~/.claude/.credentials.json`` read-write (with ``shift=true``)
    so token refresh writes back to the host, and pushes a synthesised
    ``~/.claude.json`` built from :func:`_build_minimal_claude_json`
    (the :data:`_CLAUDE_JSON_AUTH_ALLOWLIST` fields from the host plus a
    hard-coded ``hasCompletedOnboarding=True``) so Claude Code inside the
    container recognises the credentials without inheriting host session
    / project state.
    """
    container = IncusContainer(name)

    rel = ".claude/.credentials.json"
    src = home / rel
    if src.is_file():
        container.add_mount(
            "isholate-claude-cred",
            src,
            f"/home/{username}/{rel}",
            shift=True,
        )
        _say(f"exposing host Claude credentials: {src}", quiet=quiet)
    else:
        _say(
            "warning: --claude-base requested but ~/.claude/.credentials.json not found",
            quiet=quiet,
        )
        return

    minimal = _build_minimal_claude_json(home)
    if minimal is None:
        _say(
            "warning: --claude-base could not build a synthetic ~/.claude.json "
            "(host ~/.claude.json missing, unreadable, or has no oauthAccount); "
            "Claude inside the container will likely prompt for login",
            quiet=quiet,
        )
        return

    if _push_minimal_claude_json(container, username, container_uid, minimal):
        _say(
            f"installed synthetic ~/.claude.json in '{name}' "
            "(minimal auth config only; session state isolated)",
            quiet=quiet,
        )
    else:
        _say(
            "warning: --claude-base failed to push synthetic ~/.claude.json; "
            "Claude inside the container will likely prompt for login",
            quiet=quiet,
        )


# ---------------------------------------------------------------------------
# Network isolation — Claude DNS allowlist + host firewall
# ---------------------------------------------------------------------------

# Domain suffixes the Claude CLI needs to reach when running inside a
# locked-down container.
_CLAUDE_ALLOW_DOMAINS = (
    "anthropic.com",
    "claude.ai",
    "statsig.com",
    "statsigapi.net",
    "sentry.io",
)

# Incus managed network used when --no-network --claude is in effect.
_CLAUDE_NETWORK_NAME = "isholate-claude"

# Upstream DNS server the bridge forwards allowlisted queries to.
_CLAUDE_DNS_UPSTREAM = "1.1.1.1"

# Host-side firewall state names.
_CLAUDE_IPSET_NAME = "isholate-claude-allowed"
_CLAUDE_IPTABLES_CHAIN = "ISHOLATE-CLAUDE"

# Where the persistent apply script and systemd unit are installed.
_CLAUDE_FIREWALL_APPLY_SCRIPT = "/usr/local/libexec/isholate-claude-firewall"
_CLAUDE_FIREWALL_SYSTEMD_UNIT = "/etc/systemd/system/isholate-claude-firewall.service"


def _build_claude_raw_dnsmasq() -> str:
    """Build the ``raw.dnsmasq`` value for the isholate-claude bridge.

    Combines ``local=/#/`` (catch-all NXDOMAIN), ``server=/<domain>/<upstream>``
    for each allowlisted domain, and an ``ipset=`` directive so dnsmasq
    populates the host ipset on every successful lookup.
    """
    lines = ["local=/#/"]
    for domain in _CLAUDE_ALLOW_DOMAINS:
        lines.append(f"server=/{domain}/{_CLAUDE_DNS_UPSTREAM}")
    ipset_spec = "/".join(_CLAUDE_ALLOW_DOMAINS)
    lines.append(f"ipset=/{ipset_spec}/{_CLAUDE_IPSET_NAME}")
    return "\n".join(lines)


def _ensure_claude_network(*, quiet: bool = False) -> str:
    """Ensure the ``isholate-claude`` Incus managed network exists and is current.

    Creates the bridge on first use and always updates ``raw.dnsmasq`` +
    ``ipv4.firewall`` + ``ipv4.nat`` so upgrades that change the allowlist
    or toggle flags are picked up.

    Inlined here (rather than delegating to
    :func:`pyishlib.container.incus.ensure_managed_network`) so the
    Claude-specific network/dnsmasq configuration stays alongside the
    rest of the ``--claude`` support in this module.
    """
    show_r = _incus._run(
        ["incus", "network", "show", _CLAUDE_NETWORK_NAME],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if show_r.returncode != 0:
        _say(
            f"creating Incus managed network '{_CLAUDE_NETWORK_NAME}' "
            "(one-time setup for --no-network --claude)...",
            quiet=quiet,
        )
        _incus._run_checked(
            [
                "incus",
                "network",
                "create",
                _CLAUDE_NETWORK_NAME,
                "ipv4.address=auto",
                "ipv4.nat=true",
                "ipv4.firewall=false",
                "ipv6.address=none",
            ],
            f"create isholate-claude bridge '{_CLAUDE_NETWORK_NAME}'",
            stdin=subprocess.DEVNULL,
        )

    raw_dnsmasq = _build_claude_raw_dnsmasq()
    _incus._run_checked(
        [
            "incus",
            "network",
            "set",
            _CLAUDE_NETWORK_NAME,
            "raw.dnsmasq",
            raw_dnsmasq,
        ],
        "configure DNS allowlist on isholate-claude bridge",
        stdin=subprocess.DEVNULL,
    )
    _incus._run_checked(
        [
            "incus",
            "network",
            "set",
            _CLAUDE_NETWORK_NAME,
            "ipv4.firewall",
            "false",
        ],
        "disable Incus auto-firewall on isholate-claude bridge",
        stdin=subprocess.DEVNULL,
    )
    _incus._run_checked(
        [
            "incus",
            "network",
            "set",
            _CLAUDE_NETWORK_NAME,
            "ipv4.nat",
            "true",
        ],
        "ensure NAT is enabled on isholate-claude bridge",
        stdin=subprocess.DEVNULL,
    )
    return _CLAUDE_NETWORK_NAME


# The shell script that (re-)applies the ipset + iptables rules.
_CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT = f"""#!/bin/sh
# Managed by isholate.  Do not edit by hand — changes are overwritten on
# the next `isholate --no-network --claude` invocation that needs to
# reinstall rules.
set -eu

SET={_CLAUDE_IPSET_NAME}
CHAIN={_CLAUDE_IPTABLES_CHAIN}
BRIDGE={_CLAUDE_NETWORK_NAME}

# 1. Ensure the ipset exists.
ipset create "$SET" hash:ip family inet timeout 3600 -exist

# 2. Ensure our chain exists and contains exactly our ruleset.
iptables -N "$CHAIN" 2>/dev/null || true
iptables -F "$CHAIN"

iptables -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

BRIDGE_IP=$(ip -4 addr show "$BRIDGE" 2>/dev/null | awk '/inet /{{split($2,a,"/"); print a[1]; exit}}')
if [ -n "$BRIDGE_IP" ]; then
    iptables -A "$CHAIN" -d "$BRIDGE_IP" -p udp --dport 53 -j ACCEPT
    iptables -A "$CHAIN" -d "$BRIDGE_IP" -p tcp --dport 53 -j ACCEPT
fi

iptables -A "$CHAIN" -p tcp --dport 443 -m set --match-set "$SET" dst -j ACCEPT

iptables -A "$CHAIN" -j DROP

# 3. FORWARD jump.
while iptables -C FORWARD -i "$BRIDGE" -j "$CHAIN" 2>/dev/null; do
    iptables -D FORWARD -i "$BRIDGE" -j "$CHAIN"
done
iptables -I FORWARD -i "$BRIDGE" -j "$CHAIN"

# 4. Return direction.
while iptables -C FORWARD -o "$BRIDGE" -m conntrack \\
    --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; do
    iptables -D FORWARD -o "$BRIDGE" -m conntrack \\
        --ctstate ESTABLISHED,RELATED -j ACCEPT
done
iptables -I FORWARD -o "$BRIDGE" -m conntrack \\
    --ctstate ESTABLISHED,RELATED -j ACCEPT
"""

_CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT = f"""# Managed by isholate.
[Unit]
Description=isholate-claude bridge firewall rules (ipset + iptables)
Documentation=https://github.com/ishkamiel/ishlib
After=network-online.target incus.service
Wants=network-online.target
PartOf=incus.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={_CLAUDE_FIREWALL_APPLY_SCRIPT}

[Install]
WantedBy=multi-user.target
"""


def _claude_firewall_on_disk_matches() -> bool:
    """Return True if the installed apply script + systemd unit match the
    embedded content.
    """
    for path, expected in (
        (_CLAUDE_FIREWALL_APPLY_SCRIPT, _CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT),
        (_CLAUDE_FIREWALL_SYSTEMD_UNIT, _CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT),
    ):
        try:
            with open(path, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            return False
        if current != expected:
            return False
    return True


def _claude_firewall_rules_in_place() -> bool:
    """Return True if the host-side ipset + iptables rules are already set up.

    Probes on-disk content and systemd enablement — both checks avoid sudo
    so the common happy path (rules already installed) never prompts.
    """
    if not _claude_firewall_on_disk_matches():
        return False

    unit_name = Path(_CLAUDE_FIREWALL_SYSTEMD_UNIT).name
    try:
        enabled_r = _incus._run(
            ["systemctl", "is-enabled", unit_name],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False
    if enabled_r.returncode != 0:
        return False
    return True


def _build_claude_firewall_install_script() -> str:
    """Return the bootstrap shell script run under ``sudo``."""
    apply_script = _CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT
    unit = _CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT
    return (
        "set -eu\n"
        f"mkdir -p {os.path.dirname(_CLAUDE_FIREWALL_APPLY_SCRIPT)}\n"
        f"cat > {_CLAUDE_FIREWALL_APPLY_SCRIPT} <<'ISHOLATE_APPLY_EOF'\n"
        f"{apply_script}"
        "ISHOLATE_APPLY_EOF\n"
        f"chmod +x {_CLAUDE_FIREWALL_APPLY_SCRIPT}\n"
        f"cat > {_CLAUDE_FIREWALL_SYSTEMD_UNIT} <<'ISHOLATE_UNIT_EOF'\n"
        f"{unit}"
        "ISHOLATE_UNIT_EOF\n"
        "systemctl daemon-reload\n"
        "systemctl enable isholate-claude-firewall.service >/dev/null\n"
        f"{_CLAUDE_FIREWALL_APPLY_SCRIPT}\n"
    )


_CLAUDE_FIREWALL_REQUIRED_TOOLS: "tuple[tuple[str, str], ...]" = (
    ("ipset", "install the 'ipset' package (apt/dnf install ipset)"),
    (
        "iptables",
        "install the 'iptables' package "
        "(apt install iptables / dnf install iptables-nft)",
    ),
    (
        "systemctl",
        "systemd is required for the boot-time firewall restore unit; "
        "isholate currently only supports systemd hosts for --no-network --claude",
    ),
)


def _preflight_claude_host_tools() -> Optional[str]:
    """Return an actionable error message if any required host tool is missing."""
    missing: "list[str]" = []
    for tool, hint in _CLAUDE_FIREWALL_REQUIRED_TOOLS:
        if shutil.which(tool) is None:
            missing.append(f"  - {tool}: {hint}")
    if missing:
        return (
            "cannot enable Claude network isolation — missing host tools:\n"
            + "\n".join(missing)
            + "\nInstall the packages above and re-run with"
            " --no-network --claude or --no-network --claude-base."
        )
    if shutil.which("sudo") is None:
        return (
            "sudo not found on PATH; cannot install host-side firewall rules "
            "automatically.\n"
            "Install sudo and re-run, or follow the documented manual firewall "
            "installation steps as root."
        )
    return None


def _install_claude_firewall(*, quiet: bool = False) -> None:
    """Install the host-side ipset + iptables rules under ``sudo``."""
    _say(
        "installing host-side firewall rules for --no-network --claude "
        "(requires sudo on first run)...",
        quiet=quiet,
    )

    msg = _preflight_claude_host_tools()
    if msg is not None:
        raise RuntimeError(msg)

    script = _build_claude_firewall_install_script()
    result = _incus._run(
        ["sudo", "/bin/sh", "-c", script],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "failed to install host-side firewall rules "
            f"(sudo exit status {result.returncode}).  "
            "Re-run with --no-network --claude after resolving the sudo issue, "
            "or install the rules manually (see isholate docs)."
        )


def _apply_network_restrictions(
    name: str, *, allow_claude: bool, quiet: bool = False
) -> None:
    """Lock down network egress for the ephemeral container.

    Both paths operate at the Incus layer via device overrides — nothing is
    configured inside the container.
    """
    if not allow_claude:
        _say(
            f"--no-network: detaching eth0 from '{name}' via Incus device override...",
            quiet=quiet,
        )
        _incus._run(
            ["incus", "config", "device", "remove", name, "eth0"],
            check=False,
            stdin=subprocess.DEVNULL,
        )
        _incus._run_checked(
            ["incus", "config", "device", "add", name, "eth0", "none"],
            "detach eth0 via Incus device override (--no-network)",
        )
        return

    network = _ensure_claude_network(quiet=quiet)

    if not _claude_firewall_rules_in_place():
        _install_claude_firewall(quiet=quiet)

    _say(
        f"--no-network --claude: switching '{name}' to the '{network}' bridge...",
        quiet=quiet,
    )
    _incus._run(
        ["incus", "config", "device", "remove", name, "eth0"],
        check=False,
        stdin=subprocess.DEVNULL,
    )
    _incus._run_checked(
        [
            "incus",
            "config",
            "device",
            "add",
            name,
            "eth0",
            "nic",
            f"network={network}",
            "name=eth0",
        ],
        f"attach eth0 to '{network}' bridge (--no-network --claude)",
    )
