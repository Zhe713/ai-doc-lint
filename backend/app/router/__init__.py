"""三层意图漏斗路由内核骨架（W2 预留，不写规则、不做 UI）。

L1 规则层（关键词/正则/FSM）、L2 上下文层（状态机+槽位）、L3 Agent 层（LLM function calling）
的具体实现在 W3/W4 接入。本文件只定义统一协议与路由落库 helper：
全部请求无论落在哪一层，都写一行 intent_routes 作为 W7 自动学习反哺的原料，
同时是"L3 个位数流量、越用越省 token"的度量依据。
"""

from dataclasses import dataclass, field


@dataclass
class RouteResult:
    intent_code: str | None
    layer: str  # rule / context / llm
    confidence: float
    slots: dict = field(default_factory=dict)
    path: str = ""          # 下沉路径，如 L1_MISS->L2_HIT
    clarified: bool = False  # 是否因缺槽反问
    tool_calls: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    model: str | None = None
    tokens: int | None = None


class RouterChain:
    """单层路由节点协议。W3 由 RuleLayer / ContextLayer / W4 由 AgentLayer 实现。"""

    layer: str = "base"

    def match(self, text: str, *, scene: str, slots: dict) -> RouteResult | None:
        raise NotImplementedError
