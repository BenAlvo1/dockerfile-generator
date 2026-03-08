from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langchain_core.language_models import BaseChatModel

from dockerfile_gen.agent.state import AgentState
from dockerfile_gen.agent.nodes.parse_script import parse_script
from dockerfile_gen.agent.nodes.identify_technologies import make_identify_technologies_node
from dockerfile_gen.agent.nodes.check_safety import make_safety_node
from dockerfile_gen.agent.nodes.generate_dockerfile import make_generate_node
from dockerfile_gen.agent.nodes.execute_dockerfile import make_execute_node
from dockerfile_gen.agent.nodes.validate_output import validate_output
from dockerfile_gen.agent.nodes.reflect_and_fix import make_reflect_node
from dockerfile_gen.config import Config, get_config


def _safety_gate(state: AgentState) -> str:
    return "safe" if state["is_safe"] else "end"


def build_graph(llm: BaseChatModel, config: Config | None = None) -> CompiledStateGraph:
    cfg = config or get_config()

    def _should_retry(state: AgentState) -> str:
        if state["success"]:
            return "end"
        if state["attempts"] < cfg.max_attempts:
            return "reflect"
        return "end"

    graph = StateGraph(AgentState)

    graph.add_node("parse_script", parse_script)
    graph.add_node("check_safety", make_safety_node(llm))
    graph.add_node("identify_technologies", make_identify_technologies_node(llm))
    graph.add_node("generate_dockerfile", make_generate_node(llm))
    graph.add_node("execute_dockerfile", make_execute_node(cfg))
    graph.add_node("validate_output", validate_output)
    graph.add_node("reflect_and_fix", make_reflect_node(llm))

    graph.set_entry_point("parse_script")
    graph.add_edge("parse_script", "check_safety")
    graph.add_conditional_edges(
        "check_safety",
        _safety_gate,
        {"safe": "identify_technologies", "end": END},
    )
    graph.add_edge("identify_technologies", "generate_dockerfile")
    graph.add_edge("generate_dockerfile", "execute_dockerfile")
    graph.add_edge("execute_dockerfile", "validate_output")
    graph.add_conditional_edges(
        "validate_output",
        _should_retry,
        {"end": END, "reflect": "reflect_and_fix"},
    )
    graph.add_edge("reflect_and_fix", "execute_dockerfile")

    return graph.compile()
