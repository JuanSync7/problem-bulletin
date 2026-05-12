"""Admin CLI: create an agent account and print the plaintext api_key once.

Usage::

    python scripts/create_agent_account.py --name claude-bot-1 \\
        --scope tickets:read --scope tickets:write \\
        [--description "primary build bot"]

The plaintext key is emitted to stdout exactly once. Store it immediately —
it is NOT recoverable. Future invocations cannot rehydrate it.

Reads ``DATABASE_URL`` from env / ``.env`` via :mod:`app.config`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.database import async_session_factory
from app.services.agent_accounts import AgentAccountService


async def _main(args: argparse.Namespace) -> int:
    svc = AgentAccountService()
    async with async_session_factory() as session:
        try:
            account, plaintext = await svc.create_account(
                session,
                name=args.name,
                scopes=args.scope or [],
                description=args.description,
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            print(f"error: {exc}", file=sys.stderr)
            return 1

    payload = {
        "id": str(account.id),
        "name": account.name,
        "api_key": plaintext,
        "api_key_prefix": account.api_key_prefix,
        "scopes": list(account.scopes or []),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _parse_argv(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an agent account.")
    parser.add_argument("--name", required=True, help="Unique agent account name.")
    parser.add_argument(
        "--scope", action="append", default=[],
        help="Repeatable. Scopes to grant (e.g. tickets:read).",
    )
    parser.add_argument(
        "--description", default=None,
        help="Optional human description.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
