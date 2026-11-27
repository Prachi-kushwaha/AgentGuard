from __future__ import annotations
import argparse
from app.research import run_research


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentGuard AI Research Agent")
    parser.add_argument("topic", nargs="+", help="Research topic")
    args = parser.parse_args()
    run_research(" ".join(args.topic))

if __name__ == "__main__":
    main()
