#  Copyright (C) 2024. Hao Zheng
#  All rights reserved.

import streamlit as st

st.set_page_config(page_title="费用说明", page_icon="Money", layout="wide")

chatbot_help_msg = """
## 费用说明

*定价信息参考自 [OpenAI](https://openai.com/pricing) 与 [Anthropic](https://docs.anthropic.com/claude/docs/models-overview#model-comparison)*

| 模型名称 | 每 100 万 Tokens 价格（输入/输出，USD） | 1 小时音频预估费用（USD） |
|----------|------------------------------------------|----------------------------|
| `gpt-3.5-turbo-0125`       | 0.5, 1.5  | 0.01  |
| `gpt-3.5-turbo`            | 0.5, 1.5  | 0.01  |
| `gpt-4-0125-preview`       | 10, 30    | 0.5   |
| `gpt-4-turbo-preview`      | 10, 30    | 0.5   |
| `claude-3-haiku-20240307`  | 0.25, 1.25| 0.015 |
| `claude-3-sonnet-20240229` | 3, 15     | 0.2   |
| `claude-3-opus-20240229`   | 15, 75    | 1     |

**说明：以上费用是根据输入输出文本的 token 数量估算的，实际成本会因语言类型和语速而变化。**

### 翻译模型建议

- 英文音频可优先考虑 `gpt-3.5-turbo`。
- 非英文音频可优先考虑 `claude-3-sonnet-20240229`。
"""

st.markdown(chatbot_help_msg, unsafe_allow_html=True)
