from src.plugin_system import ConfigField


CONFIG_SECTION_DESCRIPTIONS = {
    "plugin": "插件基础配置",
    "selfie": "自拍功能配置",
    "llm": "文本模型配置",
    "image": "绘图模型配置",
    "safety": "安全策略配置",
}


CONFIG_SCHEMA = {
    "plugin": {
        "name": ConfigField(type=str, default="maimai_selfie_plugin", description="插件名称"),
        "version": ConfigField(type=str, default="1.0.0", description="插件版本"),
        "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
        "config_version": ConfigField(type=str, default="1.0.0", description="配置文件版本"),
    },
    "selfie": {
        "enabled": ConfigField(type=bool, default=True, description="是否启用自拍功能"),
        "trigger_keywords": ConfigField(
            type=list,
            default=["自拍", "照片", "来张", "发张", "看看你"],
            description="触发关键词列表",
            item_type="string",
            min_items=1,
        ),
        "context_message_limit": ConfigField(
            type=int,
            default=20,
            min=5,
            max=100,
            description="上下文消息条数",
        ),
        "base_image_scope": ConfigField(
            type=str,
            default="chat",
            choices=["chat", "user"],
            description="底图作用域：chat 或 user",
        ),
        "cooldown_seconds": ConfigField(
            type=int,
            default=30,
            min=0,
            max=3600,
            description="同作用域触发冷却秒数",
        ),
        "prompt_style": ConfigField(
            type=str,
            default="写实",
            description="提示词风格，如：写实/二次元/插画",
        ),
    },
    "llm": {
        "llm_provider": ConfigField(
            type=str,
            default="openai",
            choices=["openai", "custom"],
            description="文本模型提供方",
        ),
        "llm_api_base": ConfigField(
            type=str,
            default="https://api.openai.com/v1",
            description="文本模型 API Base URL",
        ),
        "llm_api_key": ConfigField(
            type=str,
            default="",
            description="文本模型 API Key",
            input_type="password",
        ),
        "llm_model": ConfigField(
            type=str,
            default="gpt-4o-mini",
            description="文本模型名称",
        ),
    },
    "image": {
        "image_provider": ConfigField(
            type=str,
            default="openai",
            choices=["openai", "custom"],
            description="绘图模型提供方",
        ),
        "image_api_base": ConfigField(
            type=str,
            default="https://api.openai.com/v1",
            description="绘图模型 API Base URL",
        ),
        "image_api_key": ConfigField(
            type=str,
            default="",
            description="绘图模型 API Key",
            input_type="password",
        ),
        "image_model": ConfigField(
            type=str,
            default="gpt-image-1",
            description="绘图模型名称",
        ),
        "image_size": ConfigField(
            type=str,
            default="1024x1024",
            choices=["512x512", "768x768", "1024x1024", "1024x1536", "1536x1024"],
            description="生成图尺寸",
        ),
    },
    "safety": {
        "disallow_nsfw": ConfigField(
            type=bool,
            default=True,
            description="是否严格禁止 NSFW/血腥/未成年人相关内容",
        ),
    },
}
