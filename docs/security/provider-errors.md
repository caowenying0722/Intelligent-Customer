# 模型供应商错误边界

`AnthropicCompatibleChatModel` 对供应商失败只抛出安全的 `AnthropicCompatibleProviderError`。错误消息最多包含状态码和经过字符白名单校验的请求 ID，不包含 `response.text`、请求/响应正文、密钥或完整 URL。

响应 JSON 解析失败和非对象响应同样只返回固定错误。成功响应的 LangChain `llm_output` 仅保留模型名，不保存供应商返回的 `raw` 对象，避免后续日志、追踪或异常处理意外携带原始内容。

`ModelGateway` 仍负责把适配器异常映射为 provider-neutral 的稳定错误契约；本边界是更底层的防线，直接使用适配器时也不会泄露供应商正文。回归覆盖位于 `tests/test_anthropic_compatible.py`。
