"""Propose candidate golden questions from random chunks, then verify them by hand.

    python -m yojana.eval.bootstrap propose --n 20
    python -m yojana.eval.bootstrap verify

Proposals go to `data/eval/candidates.jsonl` (not committed). Only questions you
accept in `verify` are appended to `golden.jsonl`, marked `verified: true`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import textwrap
from pathlib import Path

from pydantic import BaseModel

from yojana.config import Settings, get_settings
from yojana.eval.metrics import GoldenItem, Target
from yojana.index.store import ChunkStore
from yojana.ingest.models import Chunk
from yojana.llm.gateway import AllProvidersExhausted, LLMGateway

PROPOSE_PROMPT = """Write one question a citizen might ask that is fully answered by the \
passage below, in the same language as the passage. The question must not quote the \
passage verbatim. Also give the short answer as stated in the passage. Return JSON: \
{"question": "...", "answer": "..."}"""


class Proposal(BaseModel):
    question: str
    answer: str


def pick_chunks(chunks: list[Chunk], n: int, seed: int) -> list[Chunk]:
    """Random chunks spread across schemes and sections, skipping tiny ones."""
    rng = random.Random(seed)
    usable = [c for c in chunks if len(c.text.split()) >= 8]
    rng.shuffle(usable)
    picked: list[Chunk] = []
    seen: set[tuple[str, str]] = set()
    for chunk in usable:
        key = (chunk.scheme_id, chunk.section)
        if key in seen:
            continue
        seen.add(key)
        picked.append(chunk)
        if len(picked) == n:
            break
    return picked


async def propose(settings: Settings, n: int, seed: int, gateway: LLMGateway | None = None) -> Path:
    chunks = ChunkStore.load(settings.processed_dir).all()
    out = settings.eval_dir / "candidates.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    owns = gateway is None
    gateway = gateway or LLMGateway.from_settings(settings)
    existing = 0
    if out.is_file():
        existing = sum(1 for line in out.read_text(encoding="utf-8").splitlines() if line.strip())
    try:
        with out.open("a", encoding="utf-8") as handle:
            for index, chunk in enumerate(pick_chunks(chunks, n, seed), start=existing + 1):
                try:
                    proposal, _ = await gateway.complete_json(
                        [
                            {"role": "system", "content": PROPOSE_PROMPT},
                            {"role": "user", "content": f"{chunk.header}\n\n{chunk.text}"},
                        ],
                        Proposal,
                        task="bootstrap_question",
                        max_tokens=300,
                    )
                except AllProvidersExhausted as exc:
                    print(f"Stopped early: {exc}")
                    break
                item = GoldenItem(
                    id=f"cand-{index:04d}",
                    question=proposal.question,
                    language=chunk.language,
                    answerable=True,
                    relevant=[Target(scheme_id=chunk.scheme_id, section=chunk.section)],
                    reference_answer=proposal.answer,
                    verified=False,
                    notes=f"proposed from {chunk.chunk_id}",
                )
                handle.write(item.model_dump_json() + "\n")
    finally:
        if owns:
            await gateway.aclose()
    return out


def verify(settings: Settings) -> int:
    """Walk through candidates; accepted ones are appended to golden.jsonl."""
    candidates_path = settings.eval_dir / "candidates.jsonl"
    golden_path = settings.eval_dir / "golden.jsonl"
    if not candidates_path.is_file():
        print("No candidates. Run `propose` first.")
        return 0
    chunks = ChunkStore.load(settings.processed_dir)
    pending = [
        GoldenItem.model_validate_json(line)
        for line in candidates_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    existing_ids = set()
    if golden_path.is_file():
        existing_ids = {
            json.loads(line)["id"]
            for line in golden_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    accepted = 0
    remaining: list[GoldenItem] = []
    for position, item in enumerate(pending):
        source = (item.notes or "").removeprefix("proposed from ")
        chunk = chunks.get(source)
        print("\n" + "-" * 72)
        print(f"Q: {item.question}\nA: {item.reference_answer}")
        if chunk:
            print("Source passage:\n" + textwrap.indent(textwrap.fill(chunk.text, 90), "  "))
        choice = input("[a]ccept  [e]dit question  [u]nanswerable  [s]kip  [q]uit > ").strip()
        if choice == "q":
            remaining.extend(pending[position:])
            break
        if choice == "s":
            remaining.append(item)
            continue
        if choice == "e":
            item.question = input("New question: ").strip() or item.question
        if choice == "u":
            item.answerable = False
            item.relevant = []
        if choice in ("a", "e", "u"):
            item.verified = True
            item.id = f"q{len(existing_ids) + accepted + 1:04d}"
            with golden_path.open("a", encoding="utf-8") as handle:
                handle.write(item.model_dump_json(exclude_none=True) + "\n")
            accepted += 1
        else:
            remaining.append(item)
    candidates_path.write_text(
        "".join(c.model_dump_json() + "\n" for c in remaining), encoding="utf-8"
    )
    print(f"Accepted {accepted} questions into {golden_path}")
    return accepted


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    prop = sub.add_parser("propose")
    prop.add_argument("--n", type=int, default=20)
    prop.add_argument("--seed", type=int, default=13)
    sub.add_parser("verify")
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.command == "propose":
        path = asyncio.run(propose(settings, args.n, args.seed))
        print(f"Candidates written to {path}. Review them with `verify`.")
    else:
        verify(settings)


if __name__ == "__main__":
    main()
