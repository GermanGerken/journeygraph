"""Dump TrustGraph's ``urn:graph:retrieval`` named graph as JSON Lines of wire triples.

Requires the TrustGraph Python client (``pip install trustgraph-base``) and a running
TrustGraph deployment. It uses the same streaming triples query as ``tg-show-graph`` but keeps
each term's IRI/literal type, so multi-line literals and spaces survive intact.

    python export_retrieval_graph.py out/retrieval.jsonl --url http://localhost:8888/

It follows the TrustGraph client API as used in ``trustgraph-cli/trustgraph/cli/show_graph.py``
and was run against a local TrustGraph 3.0.0rc7 deployment on 24 November 2026.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trustgraph.api import Api  # type: ignore[import-not-found]

RETRIEVAL_GRAPH = "urn:graph:retrieval"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--url", default=os.getenv("TRUSTGRAPH_URL", "http://localhost:8888/"))
    parser.add_argument("--token", default=os.getenv("TRUSTGRAPH_TOKEN"))
    parser.add_argument("--workspace", default=os.getenv("TRUSTGRAPH_WORKSPACE", "default"))
    parser.add_argument("--flow-id", default="default")
    parser.add_argument("--collection", default="default")
    parser.add_argument("--limit", type=int, default=1_000_000)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()

    socket = Api(args.url, token=args.token, workspace=args.workspace).socket()
    count = 0
    try:
        flow = socket.flow(args.flow_id)
        with args.output.open("w", encoding="utf-8") as handle:
            for batch in flow.triples_query_stream(
                collection=args.collection,
                s=None,
                p=None,
                o=None,
                g=RETRIEVAL_GRAPH,
                limit=args.limit,
                batch_size=args.batch_size,
            ):
                for triple in batch:
                    record = {key: triple.get(key) for key in ("s", "p", "o")}
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    count += 1
    finally:
        socket.close()
    print(f"wrote {count} triples to {args.output}")
    if count >= args.limit:
        print("warning: the limit was reached; raise --limit to export everything")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
