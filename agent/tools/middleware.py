from collections.abc import Awaitable, Callable

from langchain.agents import AgentState
from langchain.agents.middleware import (
    ModelRequest,
    before_model,
    dynamic_prompt,
    wrap_tool_call,
)
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from agent.tools.policy import safe_argument_summary
from src.app.security.redaction import text_metadata
from utils.logger_handler import logger
from utils.prompt_loader import load_report_prompts, load_system_prompts


@wrap_tool_call
def monitor_tool(
    # 请求的数据封装
    request: ToolCallRequest,
    # 执行的函数本身
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:  # 工具执行的监控
    logger.info(f"[tool monitor]执行工具：{request.tool_call['name']}")
    logger.info(
        "[tool monitor]参数摘要：%s",
        safe_argument_summary(request.tool_call.get("args")),
    )

    try:
        result = handler(request)
        logger.info(f"[tool monitor]工具{request.tool_call['name']}调用成功")

        if request.tool_call["name"] == "fill_context_for_report":
            context = request.runtime.context
            if context is not None:
                context["report"] = True

        return result
    except Exception as e:
        logger.error(
            "工具%s调用失败，异常类型=%s",
            request.tool_call["name"],
            type(e).__name__,
        )
        raise


@wrap_tool_call
async def monitor_tool_async(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:
    """Async counterpart used by ToolNode with the same safe logging policy."""

    logger.info(f"[tool monitor]执行工具：{request.tool_call['name']}")
    logger.info(
        "[tool monitor]参数摘要：%s",
        safe_argument_summary(request.tool_call.get("args")),
    )
    try:
        result = await handler(request)
        logger.info(f"[tool monitor]工具{request.tool_call['name']}调用成功")
        if request.tool_call["name"] == "fill_context_for_report":
            context = request.runtime.context
            if context is not None:
                context["report"] = True
        return result
    except Exception as error:
        logger.error(
            "工具%s调用失败，异常类型=%s",
            request.tool_call["name"],
            type(error).__name__,
        )
        raise


@before_model
def log_before_model(
    state: AgentState,  # 整个Agent智能体中的状态记录
    runtime: Runtime,  # 记录了整个执行过程中的上下文信息
):  # 在模型执行前输出日志
    logger.info(f"[log_before_model]即将调用模型，带有{len(state['messages'])}条消息。")

    latest_message = state["messages"][-1]
    content = latest_message.content
    logger.debug(
        "[log_before_model]消息类型=%s | 内容元数据=%s",
        type(latest_message).__name__,
        (
            text_metadata(content)
            if isinstance(content, str)
            else {"type": type(content).__name__}
        ),
    )


@dynamic_prompt  # 每一次在生成提示词之前，调用此函数
def report_prompt_switch(request: ModelRequest):  # 动态切换提示词
    context = request.runtime.context
    is_report = context.get("report", False) if context is not None else False
    if is_report:  # 是报告生成场景，返回报告生成提示词内容
        return load_report_prompts()

    return load_system_prompts()
