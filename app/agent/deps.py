"""Everything the nodes need from outside the state, passed in once when the graph is built.

Tests build ``AgentDeps`` with a fake LLM; the app uses ``default_deps()``.
"""

from dataclasses import dataclass

from langchain_core.messages import BaseMessage, SystemMessage

from app.agent.config import AgentConfig, get_agent_config
from app.agent.state import AgentState, Usage
from app.core.config import get_settings
from app.core.llm import BudgetTracker, LLMClient, LLMConfig, create_llm_client, get_llm_config
from app.core.prompts import load_prompt
from app.semantic.calendar import CalendarConfig, load_calendar
from app.semantic.catalog import load_semantic_layer_file
from app.semantic.models import SemanticLayer


@dataclass(frozen=True)
class AgentDeps:
    llm: LLMClient
    llm_config: LLMConfig
    agent_config: AgentConfig
    calendar: CalendarConfig
    semantic: SemanticLayer

    def budget_for(self, state: AgentState) -> BudgetTracker:
        """The question's budget, continuing from what earlier nodes already spent."""
        return BudgetTracker(
            self.llm_config.budget,
            self.llm_config.pricing,
            spent_input_tokens=state.usage.input_tokens,
            spent_output_tokens=state.usage.output_tokens,
            spent_cost_usd=state.usage.cost_usd,
        )

    def system_messages(self) -> list[BaseMessage]:
        prompt = load_prompt("system", self.llm_config.prompts["system"])
        return list(
            prompt.to_chat_prompt().format_messages(
                business_today=self.calendar.reference_date.isoformat()
            )
        )


def usage_of(budget: BudgetTracker) -> Usage:
    return Usage(
        input_tokens=budget.input_tokens,
        output_tokens=budget.output_tokens,
        cost_usd=budget.cost_usd,
    )


def default_deps() -> AgentDeps:
    """Production wiring: real LLM client, config files and the semantic layer file."""
    return AgentDeps(
        llm=create_llm_client(get_settings()),
        llm_config=get_llm_config(),
        agent_config=get_agent_config(),
        calendar=load_calendar(),
        semantic=load_semantic_layer_file(),
    )


__all__ = ["AgentDeps", "SystemMessage", "default_deps", "usage_of"]
