from __future__ import annotations

from agents.todo_creation.multi_turn.graph import build_multi_turn_graph


def test_graph_compiles_with_expected_nodes():
    graph = build_multi_turn_graph()
    node_ids = set(graph.get_graph().nodes.keys())
    expected = {
        "validate", "phase_router", "planner_judge", "follow_up",
        "plan_generator", "tagger", "edit_agent", "commit_invoke", "present",
    }
    assert expected.issubset(node_ids)


def test_graph_mermaid_includes_phase_router_and_edit_agent():
    graph = build_multi_turn_graph()
    mmd = graph.get_graph().draw_mermaid()
    assert "phase_router" in mmd
    assert "edit_agent" in mmd
