from __future__ import annotations

import os
from typing import Any

from flask import Flask, flash, redirect, render_template, request, url_for

from .config_store import (
    MCPServer,
    get_mcp_servers,
    get_policies,
    put_mcp_servers,
    put_policies, 
)
from src.policy import ApprovalCategory, PolicyRule
from .dynamodb_utils import get_approval_table


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    # --- MCP servers ---
    @app.get("/servers")
    def servers() -> str:
        cfg = get_mcp_servers()
        return render_template("servers.html", servers=cfg.servers)

    @app.post("/servers")
    def save_servers() -> Any:
        rows: list[MCPServer] = []
        # Load existing config to preserve env for rows left blank
        existing_cfg = get_mcp_servers()
        existing_by_alias: dict[str, MCPServer] = {s.alias: s for s in existing_cfg.servers}
        aliases = request.form.getlist("alias")
        paths = request.form.getlist("path")
        commands = request.form.getlist("command")
        args_lists = request.form.getlist("args")
        env_blocks = request.form.getlist("env")
        disableds = request.form.getlist("disabled_tools")
        for i, alias in enumerate(aliases):
            alias = (alias or "").strip()
            path = (paths[i] if i < len(paths) else "").strip()
            command = (commands[i] if i < len(commands) else "").strip()
            args_raw = (args_lists[i] if i < len(args_lists) else "").strip()
            env_raw = (env_blocks[i] if i < len(env_blocks) else "").strip()
            # Skip entirely empty rows
            if not alias or (not path and not command):
                continue
            enabled = request.form.get(f"enabled_{i}") is not None
            # Parse comma-separated disabled tools (short names)
            disabled_list: list[str] = []
            raw = disableds[i] if i < len(disableds) else ""
            for name in (raw or "").split(","):
                n = name.strip()
                if n:
                    # Store bare short name
                    disabled_list.append(n.split("__", 1)[-1])
            # Parse args as comma-separated list
            args: list[str] = [a.strip() for a in args_raw.split(",") if a.strip()] if args_raw else []
            # Parse env block as KEY=VALUE per line; preserve existing if left blank
            if env_raw:
                env: dict[str, str] = {}
                for line in env_raw.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k:
                        env[k] = v
            else:
                env = dict(existing_by_alias.get(alias).env) if alias in existing_by_alias else {}
            rows.append(
                MCPServer(
                    alias=alias,
                    path=path or None,
                    command=command or None,
                    args=args,
                    env=env,
                    enabled=enabled,
                    disabled_tools=disabled_list,
                )
            )
        put_mcp_servers(rows)
        flash("Servers saved", "success")
        return redirect(url_for("servers"))

    # --- Policies ---
    @app.get("/policies")
    def policies() -> str:
        cfg = get_policies()
        return render_template("policies.html", rules=cfg.rules)

    @app.post("/policies")
    def save_policies() -> Any:
        names = request.form.getlist("name")
        categories = request.form.getlist("categories")
        envs = request.form.getlist("environments")
        prefixes = request.form.getlist("resource_prefixes")
        min_amounts = request.form.getlist("min_amount")
        max_amounts = request.form.getlist("max_amount")

        rules: list[PolicyRule] = []
        for i, name in enumerate(names):
            name = (name or "").strip()
            if not name:
                continue
            cats = [
                ApprovalCategory(c.strip())
                for c in (categories[i] if i < len(categories) else "").split(
                    ","
                )
                if c.strip()
            ]
            env_list = [
                e.strip()
                for e in (envs[i] if i < len(envs) else "").split(",")
                if e.strip()
            ]
            pref_list = [
                p.strip()
                for p in (prefixes[i] if i < len(prefixes) else "").split(",")
                if p.strip()
            ]
            ra = request.form.get(f"require_approval_{i}") is not None
            dn = request.form.get(f"deny_{i}") is not None
            min_amt = (
                float(min_amounts[i])
                if i < len(min_amounts) and min_amounts[i]
                else None
            )
            max_amt = (
                float(max_amounts[i])
                if i < len(max_amounts) and max_amounts[i]
                else None
            )
            rules.append(
                PolicyRule(
                    name=name,
                    categories=cats,
                    environments=env_list,
                    resource_prefixes=pref_list,
                    min_amount=min_amt,
                    max_amount=max_amt,
                    require_approval=ra,
                    deny=dn,
                )
            )
        put_policies(rules)
        flash("Policies saved", "success")
        return redirect(url_for("policies"))

    # --- Approvals audit ---
    @app.get("/approvals")
    def approvals() -> str:
        limit = int(request.args.get("limit", "50"))
        try:
            table = get_approval_table()
            # Paginated scan and sort by creation timestamp (desc)
            items: list[dict[str, Any]] = []
            start_key: dict[str, Any] | None = None
            max_scan: int = max(limit * 5, 100)
            while True:
                scan_kwargs: dict[str, Any] = {"Limit": min(200, max_scan)}
                if start_key:
                    scan_kwargs["ExclusiveStartKey"] = start_key
                resp = table.scan(**scan_kwargs)
                items.extend(resp.get("Items", []))
                start_key = resp.get("LastEvaluatedKey")
                if not start_key or len(items) >= max_scan:
                    break
        except Exception:
            # If approvals table is missing (e.g., local tests), show empty list
            items = []

        def _ts_key(d: dict[str, Any]) -> float:
            ts = d.get("timestamp", "")
            try:
                from datetime import datetime

                norm = ts.replace("Z", "+00:00")
                return datetime.fromisoformat(norm).timestamp()
            except Exception:
                return 0.0

        items = sorted(items, key=_ts_key, reverse=True)[:limit]
        return render_template("approvals.html", items=items)

    return app


app = create_app()
