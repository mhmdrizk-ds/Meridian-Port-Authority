import argparse
import json
import sys
from pathlib import Path

from agent.elicitation import interactive_elicitation_handler, scripted_elicitation_handler
from agent.progress import progress_handler
from agent.sampling import sampling_handler
from agent.scenarios import FULL_DEMO_ORDER, SCENARIO_ORDER, SCENARIOS
from agent.session import MeridianAgentSession

TEST_INPUTS_PATH = Path(__file__).resolve().parent / "test_inputs.json"
DEFAULT_ELICITATION_ANSWER = {"action": "accept", "content": {"confirm": True}}


def load_test_inputs():
    with open(TEST_INPUTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["scenarios"]


def build_session(scenario_data, interactive):
    if interactive:
        elicit = interactive_elicitation_handler
    else:
        fixed = scenario_data.get("elicitation_response", DEFAULT_ELICITATION_ANSWER)
        elicit = scripted_elicitation_handler(fixed)

    return MeridianAgentSession(
        elicitation_handler=elicit,
        sampling_handler=sampling_handler,
        progress_handler=progress_handler,
        memory_buffer_capacity=scenario_data.get("memory_buffer_capacity", 50),
    )


def run_scenario(name, all_data, interactive):
    if name not in SCENARIOS:
        print(f"Unknown scenario '{name}'. Use --list to see valid names.", file=sys.stderr)
        sys.exit(1)

    data = all_data[name]
    print(f"\n>>> Running scenario: {name}")
    print(f">>> {data.get('description', '')}")

    session = build_session(data, interactive)
    try:
        session.initialize()
        SCENARIOS[name](session, data)
    except Exception as exc:  # noqa: BLE001 - surface it, then still close cleanly
        print(f"\n!!! Scenario '{name}' raised: {exc}", file=sys.stderr)
        raise
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Meridian Port Authority MCP agent")
    parser.add_argument("--scenario", help="Name of a single scenario to run")
    parser.add_argument("--all", action="store_true", help="Run all 7 scenarios in order")
    parser.add_argument(
        "--full-demo",
        action="store_true",
        help="Run all 7 original scenarios plus the Memory & RAG Lab integration scenario",
    )
    parser.add_argument("--list", action="store_true", help="List available scenarios and exit")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Answer elicitation prompts live at the terminal instead of using the scripted demo answers",
    )
    args = parser.parse_args()

    all_data = load_test_inputs()

    if args.list:
        for name in FULL_DEMO_ORDER:
            print(f"  {name:42s} {all_data[name].get('description', '')}")
        return

    if args.all:
        for name in SCENARIO_ORDER:
            run_scenario(name, all_data, args.interactive)
        return

    if args.full_demo:
        for name in FULL_DEMO_ORDER:
            run_scenario(name, all_data, args.interactive)
        return

    if args.scenario:
        run_scenario(args.scenario, all_data, args.interactive)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
