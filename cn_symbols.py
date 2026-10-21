"""A-share universe shared by the analysis pipeline and backend startup logs."""

# Display name, East Money market.security identifier. Existing indices retained.
CN_SYMS = [
    ("上证指数", "1.000001"),
    ("科创50", "1.000688"),
    ("银行指数", "0.399986"),
    ("平均股价", "47.800005"),
    ("万向钱潮", "0.000559"),
    ("三花智控", "0.002050"),
    ("三孚股份", "1.603938"),
    ("诺德股份", "1.600110"),
]

CN_CODES = {
    "万向钱潮": "000559",
    "三花智控": "002050",
    "三孚股份": "603938",
    "诺德股份": "600110",
}

# Sina uses sh/sz identifiers. 平均股价 remains East Money-only.
SINA_SYMS = {
    "上证指数": "sh000001", "科创50": "sh000688", "银行指数": "sz399986",
    "万向钱潮": "sz000559", "三花智控": "sz002050",
    "三孚股份": "sh603938", "诺德股份": "sh600110",
}
