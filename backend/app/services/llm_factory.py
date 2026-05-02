import logging

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def create_chat_model() -> BaseChatModel:
    """根据配置创建对话模型实例"""
    provider = settings.LLM_PROVIDER
    model = settings.LLM_MODEL
    api_key = settings.OPENAI_API_KEY

    if not api_key or "sk-your" in api_key:
        raise ValueError("未配置有效的 API Key，请在 .env 中设置 OPENAI_API_KEY")

    logger.info("创建 LLM: provider=%s, model=%s", provider, model)

    if provider == "dashscope":
        # 阿里云百炼（DashScope OpenAI 兼容接口）
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            base_url=DASHSCOPE_BASE_URL,
            api_key=api_key,
            temperature=0.7,
            streaming=True,
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        kwargs = {"model": model, "api_key": api_key, "temperature": 0.7, "streaming": True}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        return ChatOpenAI(**kwargs)
    elif provider == "deepseek":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or "deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            api_key=settings.DEEPSEEK_API_KEY or api_key,
            temperature=0.7,
            streaming=True,
        )
    else:
        raise ValueError("不支持的 LLM 提供商: %s。支持: dashscope, openai, deepseek" % provider)
