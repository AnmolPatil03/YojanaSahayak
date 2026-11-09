"""Inspect, correct and approve extracted eligibility rules.

yojana-review list [--pending]
yojana-review show SCHEME_ID
yojana-review set SCHEME_ID FIELD VALUE [--chunk CHUNK_ID]
yojana-review edit SCHEME_ID
yojana-review approve SCHEME_ID [--reviewer NAME]
yojana-review interactive
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from yojana.config import Settings, get_settings
from yojana.index.store import ChunkStore
from yojana.rules import RULE_FIELDS, EligibilityRules, RulesRecord, RulesStore

_LIST_FIELDS = {"genders", "states", "social_categories", "occupations", "education_levels"}
_INT_FIELDS = {"min_age", "max_age", "max_annual_family_income"}


class ReviewError(Exception):
    pass


def parse_value(field: str, raw: str) -> Any:
    """Turn command-line text into a typed rule value; 'null' clears the field."""
    if raw.strip().lower() in ("null", "none", ""):
        return None
    if field in _INT_FIELDS:
        try:
            return int(raw.replace(",", "").replace("_", ""))
        except ValueError as exc:
            raise ReviewError(f"{field} needs a whole number") from exc
    if field in _LIST_FIELDS:
        if raw.strip().startswith("["):
            return json.loads(raw)
        return [part.strip() for part in raw.split(",") if part.strip()]
    if field == "disability_required":
        lowered = raw.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
        raise ReviewError("disability_required must be true or false")
    if field == "residence":
        return raw.strip().lower()
    raise ReviewError(f"Unknown field {field!r}. Fields: {', '.join(RULE_FIELDS)}")


def set_field(record: RulesRecord, field: str, raw: str, chunk_id: str | None) -> RulesRecord:
    """Return a copy of `record` with one field changed and review status reset."""
    if field not in RULE_FIELDS:
        raise ReviewError(f"Unknown field {field!r}. Fields: {', '.join(RULE_FIELDS)}")
    data = record.rules.model_dump()
    data[field]["value"] = parse_value(field, raw)
    if chunk_id is not None:
        data[field]["chunk_id"] = chunk_id
    try:
        rules = EligibilityRules.model_validate(data)
    except ValidationError as exc:
        raise ReviewError(str(exc)) from exc
    return record.model_copy(update={"rules": rules, "needs_review": True})


def render(record: RulesRecord, chunks: ChunkStore, out: TextIO) -> None:
    status = "needs review" if record.needs_review else f"reviewed {record.reviewed_at}"
    out.write(f"\n{record.scheme_name} ({record.scheme_id}) - {status}\n")
    if record.extracted_by:
        out.write(f"extracted by {record.extracted_by} at {record.extracted_at}\n")
    out.write("-" * 72 + "\n")
    for name in RULE_FIELDS:
        rule = getattr(record.rules, name)
        if rule.value is None:
            out.write(f"  {name:26} -\n")
            continue
        out.write(f"  {name:26} {json.dumps(rule.value, ensure_ascii=False)}\n")
        _write_source(rule.chunk_id, chunks, out)
    for condition in record.rules.other_conditions:
        out.write(f"  {'other':26} {condition.text}\n")
        _write_source(condition.chunk_id, chunks, out)
    if record.previous is not None:
        out.write("\n  Previously reviewed rules differ; run `show` after editing to compare.\n")


def _write_source(chunk_id: str | None, chunks: ChunkStore, out: TextIO) -> None:
    if not chunk_id:
        out.write(f"  {'':26} source: (none cited)\n")
        return
    chunk = chunks.get(chunk_id)
    if chunk is None:
        out.write(f"  {'':26} source: {chunk_id} (chunk no longer exists)\n")
        return
    snippet = textwrap.shorten(" ".join(chunk.text.split()), width=160, placeholder=" …")
    out.write(f"  {'':26} source [{chunk_id}]: {snippet}\n")


def edit_in_editor(record: RulesRecord) -> RulesRecord:
    """Open the rules as JSON in $EDITOR (Notepad on Windows) and validate the result."""
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(record.rules.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
        path = Path(handle.name)
    try:
        subprocess.run([editor, str(path)], check=True)
        rules = EligibilityRules.model_validate_json(path.read_text(encoding="utf-8"))
    except (subprocess.CalledProcessError, ValidationError) as exc:
        raise ReviewError(f"Edit not applied: {exc}") from exc
    finally:
        path.unlink(missing_ok=True)
    return record.model_copy(update={"rules": rules, "needs_review": True})


def _require(store: RulesStore, scheme_id: str) -> RulesRecord:
    record = store.get(scheme_id)
    if record is None:
        raise ReviewError(f"No rules found for {scheme_id!r}")
    return record


def interactive(store: RulesStore, chunks: ChunkStore, reviewer: str | None) -> None:
    pending = [r for r in store.all() if r.needs_review]
    if not pending:
        print("Nothing to review.")
        return
    for record in pending:
        while True:
            render(record, chunks, sys.stdout)
            choice = input("\n[a]pprove  [e]dit  [s]kip  [q]uit > ").strip().lower()
            if choice == "a":
                record.mark_reviewed(reviewer)
                store.save(record)
                break
            if choice == "e":
                try:
                    record = edit_in_editor(record)
                    store.save(record)
                except ReviewError as exc:
                    print(exc)
                continue
            if choice == "s":
                break
            if choice == "q":
                return


def run(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    parser = argparse.ArgumentParser(prog="yojana-review", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    list_cmd = sub.add_parser("list", help="List schemes with rules")
    list_cmd.add_argument("--pending", action="store_true")
    show = sub.add_parser("show", help="Show rules with their source passages")
    show.add_argument("scheme_id")
    setter = sub.add_parser("set", help="Change one field")
    setter.add_argument("scheme_id")
    setter.add_argument("field", choices=RULE_FIELDS)
    setter.add_argument("value")
    setter.add_argument("--chunk", help="Chunk id that states this value")
    edit = sub.add_parser("edit", help="Edit all rules as JSON in your editor")
    edit.add_argument("scheme_id")
    approve = sub.add_parser("approve", help="Mark rules as reviewed")
    approve.add_argument("scheme_id")
    approve.add_argument("--reviewer")
    inter = sub.add_parser("interactive", help="Step through every pending scheme")
    inter.add_argument("--reviewer")
    args = parser.parse_args(argv)

    store = RulesStore(settings.processed_dir / "rules")
    chunks = ChunkStore.load(settings.processed_dir)
    try:
        if args.command == "list":
            for record in store.all():
                if args.pending and not record.needs_review:
                    continue
                flag = "pending " if record.needs_review else "reviewed"
                print(f"{flag}  {record.scheme_id:40} {record.scheme_name}")
        elif args.command == "show":
            render(_require(store, args.scheme_id), chunks, sys.stdout)
        elif args.command == "set":
            record = set_field(_require(store, args.scheme_id), args.field, args.value, args.chunk)
            store.save(record)
            render(record, chunks, sys.stdout)
        elif args.command == "edit":
            store.save(edit_in_editor(_require(store, args.scheme_id)))
        elif args.command == "approve":
            record = _require(store, args.scheme_id)
            record.mark_reviewed(args.reviewer)
            store.save(record)
            print(f"Approved {args.scheme_id}")
        elif args.command == "interactive":
            interactive(store, chunks, args.reviewer)
    except ReviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
