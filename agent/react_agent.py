from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.tools.agent_tools import (
    fetch_external_data,
    fill_context_for_report,
    get_current_month,
    get_user_id,
    get_user_location,
    get_weather,
    rag_summarize,
)
from model.factory import get_chat_model
from utils.logger_handler import logger
from utils.prompt_loader import load_report_prompts, load_system_prompts
from utils.settings import Settings, get_settings

AGENT_STEP_LIMIT_MESSAGE = "本次请求已达到处理步骤上限，请缩小问题范围后重试。"
AGENT_TOOL_LIMIT_MESSAGE = "本次请求已达到工具调用上限，请缩小问题范围后重试。"


class ReactAgent:
    def __init__(
        self,
        model: BaseChatModel | None = None,
        tools: Sequence[BaseTool] | None = None,
        settings: Settings | None = None,
    ):
        runtime_settings = settings if settings is not None else get_settings()
        self.max_steps = runtime_settings.agent_max_steps
        self.max_tool_calls = runtime_settings.agent_max_tool_calls
        self.tools = (
            list(tools)
            if tools is not None
            else [
                rag_summarize,
                get_weather,
                get_user_location,
                get_user_id,
                get_current_month,
                fetch_external_data,
                fill_context_for_report,
            ]
        )
        chat_model = model if model is not None else get_chat_model()
        self.model_with_tools = chat_model.bind_tools(self.tools)
        self.system_prompt = load_system_prompts()
        self.graph = self._build_graph()

    @staticmethod
    def _count_tool_calls(messages: Sequence[BaseMessage]) -> int:
        return sum(
            len(message.tool_calls)
            for message in messages
            if isinstance(message, AIMessage)
        )

    def _call_model(self, state: MessagesState):
        messages = state["messages"]
        tool_call_count = self._count_tool_calls(messages)
        if tool_call_count >= self.max_tool_calls:
            logger.warning(
                "[agent]达到工具调用上限 max_tool_calls=%s", self.max_tool_calls
            )
            return {"messages": [AIMessage(content=AGENT_TOOL_LIMIT_MESSAGE)]}

        # 检测是否已调用 fill_context_for_report，切换到报告提示词
        report_triggered = any(
            isinstance(m, ToolMessage)
            and hasattr(m, "name")
            and m.name == "fill_context_for_report"
            for m in messages
        )
        prompt = load_report_prompts() if report_triggered else self.system_prompt

        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=prompt)] + messages

        response = self.model_with_tools.invoke(messages)
        requested_tool_calls = (
            len(response.tool_calls) if isinstance(response, AIMessage) else 0
        )
        if tool_call_count + requested_tool_calls > self.max_tool_calls:
            logger.warning(
                "[agent]拒绝超限工具批次 current=%s requested=%s max=%s",
                tool_call_count,
                requested_tool_calls,
                self.max_tool_calls,
            )
            return {"messages": [AIMessage(content=AGENT_TOOL_LIMIT_MESSAGE)]}
        logger.info(f"[model]调用模型，返回 {len(response.content)} 字符")
        return {"messages": [response]}

    def _build_graph(self):
        tool_node = ToolNode(self.tools)

        graph = StateGraph(MessagesState)
        graph.add_node("agent", self._call_model)
        graph.add_node("tools", tool_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent", tools_condition, {"tools": "tools", END: END}
        )
        graph.add_edge("tools", "agent")

        return graph.compile()

    def execute_stream(self, query: str):
        input_dict = {
            "messages": [
                {"role": "user", "content": query},
            ]
        }

        try:
            for chunk in self.graph.stream(
                input_dict,
                config={"recursion_limit": self.max_steps},
                stream_mode="values",
            ):
                latest_message = chunk["messages"][-1]
                if latest_message.content:
                    yield latest_message.content.strip() + "\n"
        except GraphRecursionError:
            logger.warning("[agent]达到图步骤上限 max_steps=%s", self.max_steps)
            yield AGENT_STEP_LIMIT_MESSAGE + "\n"


if __name__ == "__main__":
    agent = ReactAgent()

    for chunk in agent.execute_stream("给我生成我的使用报告"):
        print(chunk, end="", flush=True)
