from __future__ import annotations

import os
from typing import Any

from flask import Flask, redirect, render_template, request, url_for, flash

from .config_store import (
    MCPServer,
    get_mcp_servers,
    put_mcp_servers,
    get_policies,
    put_policies,
)
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
        aliases = request.form.getlist("alias")
        paths = request.form.getlist("path")
        disableds = request.form.getlist("disabled_tools")
        for i, alias in enumerate(aliases):
            alias = (alias or "").strip()
            path = (paths[i] if i < len(paths) else "").strip()
            if not alias or not path:
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
            rows.append(
                MCPServer(
                    alias=alias,
                    path=path,
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
        from .policy import PolicyRule, ApprovalCategory

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
        table = get_approval_table()
        try:
            resp = table.query(
                IndexName="TimestampIndex",
                KeyConditionExpression="#ts >= :min",
                ExpressionAttributeNames={"#ts": "timestamp"},
                ExpressionAttributeValues={":min": ""},
                ScanIndexForward=False,
                Limit=limit,
            )
            items = resp.get("Items", [])
        except Exception:
            resp = table.scan(Limit=limit)
            items = resp.get("Items", [])
        # Ensure client receives items sorted by most recent first
        try:
            items = sorted(
                items,
                key=lambda d: d.get("timestamp", ""),
                reverse=True,
            )
        except Exception:
            pass
        return render_template("approvals.html", items=items)

    return app


app = create_app()
