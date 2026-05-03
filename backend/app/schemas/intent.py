"""意图识别结果 Schema"""

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """意图识别结果"""

    intent: str = Field(
        description="意图标签",
        enum=["knowledge_qa", "chitchat", "summarize", "compare", "complex_task"],
    )
    confidence: float = Field(
        description="置信度 0.0-1.0",
        ge=0,
        le=1,
    )
    entities: list[str] = Field(
        description="提到的关键实体",
        default_factory=list,
    )
    action: str = Field(
        description="用户想执行的动作",
        default="",
    )
    conditions: list[str] = Field(
        description="限制条件",
        default_factory=list,
    )
    needs_clarification: bool = Field(
        description="是否需要澄清",
        default=False,
    )
    clarification_question: str = Field(
        description="澄清问题",
        default="",
    )
