"""
CLI 交互模块 — 消息渲染与用户交互主循环。
"""

import sys

from langchain_core.language_models import BaseChatModel

from src.core.agent import build_agent
from src.skills.center import SkillCenter


_BANNER = """
╔══════════════════════════════════════════════════╗
║          Generalist Agent — 供应链ChatBI          ║
║                                                  ║
║  输入 exit / quit / q 退出                         ║
║  技能修改无需重启，自动感知最新变更                     ║
╚══════════════════════════════════════════════════╝
"""

_SYSTEM_PROMPT = """你是一个智能助手。

规则：
1. 请始终用中文回答。
2. 对于多步骤任务，先使用 write_todos 工具拆解步骤。
3. 执行过程中及时反馈进度。
4. 如果需要使用某项技能，请先 read_file 读取对应的 SKILL.md 文件了解使用方法。"""


def print_stream(messages: list) -> None:
    """打印 Agent 响应消息流，区分角色和工具调用。"""
    for msg in messages:
        role = msg.type.upper() if hasattr(msg, "type") else type(msg).__name__

        if role == "HUMAN":
            continue

        if role == "AI":
            content = msg.content or ""
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get("name", "?")
                    args = str(tc.get("args", {}))
                    print(f"\n  🛠 调用工具: {name}")
                    print(f"     参数: {args[:200]}")
            if content:
                print(f"\n  🤖 {content}")
        elif role == "TOOL":
            content = str(msg.content or "")[:300]
            print(f"  📥 工具返回: {content}")
        else:
            content = str(msg.content or "")[:200]
            if content:
                print(f"  [{role}] {content}")


def repl(model: BaseChatModel, skill_center: SkillCenter) -> None:
    # Windows 编码兼容
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    """交互式主循环。

    每次用户输入：
    1. SkillCenter 检测技能是否变更
    2. 重新实例化 Agent（确保技能和 prompt 最新）
    3. 调用 Agent.invoke() 处理请求
    """
    print(_BANNER)

    state: dict = {"messages": []}
    invoke_config = {"configurable": {"thread_id": "generalist-agent-session"}}

    while True:
        try:
            user_input = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("\n再见！")
            break

        # 1. 检测技能变更，清除缓存
        state = skill_center.decorate_state(state)

        # 2. 重新实例化 Agent
        agent = build_agent(
            model=model,
            skills_dir=skill_center.get_skills_dir(),
            system_prompt=_SYSTEM_PROMPT,
        )

        # 3. 发送请求
        state["messages"].append({"role": "user", "content": user_input})
        result = agent.invoke(state, config=invoke_config)
        state = result

        # 4. 打印响应
        print_stream(result["messages"])