"""统一标签体系（四类受控字典），录入/导入时强校验。"""

BUILTIN_TAG_DICT: list[dict] = [
    # 领域
    {"category": "domain", "value": "通用", "label": "通用问答"},
    {"category": "domain", "value": "客服", "label": "客服场景"},
    {"category": "domain", "value": "数据分析", "label": "数据分析/NL2SQL"},
    {"category": "domain", "value": "知识问答", "label": "知识库问答"},
    {"category": "domain", "value": "编码", "label": "编程开发"},
    # 难度
    {"category": "difficulty", "value": "easy", "label": "简单"},
    {"category": "difficulty", "value": "medium", "label": "中等"},
    {"category": "difficulty", "value": "hard", "label": "困难"},
    # 场景
    {"category": "scenario", "value": "单轮问答", "label": "单轮问答"},
    {"category": "scenario", "value": "nl2sql", "label": "自然语言转 SQL"},
    {"category": "scenario", "value": "rag_qa", "label": "检索增强问答"},
    {"category": "scenario", "value": "写作", "label": "写作生成"},
    {"category": "scenario", "value": "推理", "label": "逻辑推理"},
    {"category": "scenario", "value": "注入攻击", "label": "提示注入攻防"},
    # 风险等级
    {"category": "risk", "value": "low", "label": "低风险"},
    {"category": "risk", "value": "medium", "label": "中风险"},
    {"category": "risk", "value": "high", "label": "高风险"},
]

TAG_CATEGORIES = ("domain", "difficulty", "scenario", "risk")
DIFFICULTIES = ("easy", "medium", "hard")
