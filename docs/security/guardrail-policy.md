# 域外判断策略边界

`GuardrailPolicy` 将当前少量关键词规则封装为版本化、不可变且可注入的 deterministic baseline。默认版本为 `out-of-scope-v1`；测试和后续离线实验可以传入独立策略，不会修改全局默认规则。

该策略只用于明显域外问题的早期拒答和转人工提示，不是通用安全 guardrail，也不能替代 PromptSafetyPolicy、权限检查或人工审核。新增版本必须配套数据集回归，观察误拒答/漏放后再切换默认版本。
