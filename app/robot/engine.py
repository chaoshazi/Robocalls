'''话术脚本引擎：规则优先、变量填充、意图识别与结束/转人工判定。

脚本结构（存在 scripts.content 里）：
{
  'opening': '您好，我是{company}的小王，请问是{name}吗？',
  'nodes': [
    {'id': 'n1', 'say': '您这边近期有采购计划吗？',
     'keywords': {'有': 'n2', '没有': None}, 'default': 'n2', 'intent': 'B'}
  ],
  'closing': '好的，打扰了，祝您生活愉快。'
}
keywords 的值是下一个节点 id；null 表示结束通话。
'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FALLBACK_OPENING = '您好，这里是外呼机器人，请问现在方便沟通吗？'
FALLBACK_CLOSING = '好的，打扰了，祝您生活愉快。'

# 意图关键词：命中即给意向等级，供规则模式与「LLM 失败降级」共用
INTENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('A', ('签约', '合同', '报价', '价格', '多少钱', '购买', '下单', 'demo', '演示')),
    ('B', ('考虑', '了解', '方案', '看看', '介绍', '资料', '方便', '可以')),
    ('C', ('再想想', '以后', '下次', '暂时不', '再说')),
    ('D', ('不需要', '不感兴趣', '打错了', '别打', '骚扰', '没兴趣')),
)
TRANSFER_KEYWORDS: tuple[str, ...] = ('转人工', '找个人', '真人', '客服', '经理')


@dataclass
class Reply:
    say: str
    next_node: str | None
    intent: str | None
    end: bool
    transfer: bool
    used_llm: bool = False


class ScriptEngine:
    def __init__(self, content: dict[str, Any] | None) -> None:
        self.content = dict(content or {})
        self.nodes = {
            str(node.get('id')): node
            for node in (self.content.get('nodes') or [])
            if isinstance(node, dict) and node.get('id')
        }

    # ---- 开场与结束 ----
    def opening(self, variables: dict[str, Any]) -> str:
        text = str(self.content.get('opening') or FALLBACK_OPENING)
        return self.fill(text, variables)

    def closing(self) -> str:
        return str(self.content.get('closing') or FALLBACK_CLOSING)

    def first_node(self) -> str | None:
        nodes = list(self.nodes)
        return nodes[0] if nodes else None

    # ---- 单轮 ----
    def respond(self, *, node_id: str | None, customer_text: str, variables: dict[str, Any]) -> Reply:
        text = str(customer_text or '')
        intent = detect_intent(text)
        transfer = any(word in text for word in TRANSFER_KEYWORDS)
        node = self.nodes.get(str(node_id)) if node_id else None
        if node is None:
            return Reply(
                say=self.closing(),
                next_node=None,
                intent=intent,
                end=True,
                transfer=transfer,
            )
        node_intent = str(node.get('intent') or '') or None
        next_node = self._match(node, text)
        node_text = self.fill(str(node.get('say') or ''), variables)
        if next_node is None:
            return Reply(
                say=(node_text + ' ' + self.closing()).strip(),
                next_node=None,
                intent=intent or node_intent,
                end=True,
                transfer=transfer,
            )
        return Reply(
            say=node_text,
            next_node=next_node,
            intent=intent or node_intent,
            end=False,
            transfer=transfer,
        )

    def _match(self, node: dict[str, Any], text: str) -> str | None:
        '''按关键词命中分支；长关键词优先，避免「没有」被「有」抢先匹配。'''
        keywords = node.get('keywords') or {}
        if isinstance(keywords, dict):
            for key in sorted(keywords, key=lambda item: len(str(item)), reverse=True):
                if key and str(key) in text:
                    target = keywords[key]
                    return str(target) if target else None
        default = node.get('default')
        return str(default) if default else None

    @staticmethod
    def fill(text: str, variables: dict[str, Any]) -> str:
        result = str(text or '')
        for key, value in (variables or {}).items():
            result = result.replace('{' + str(key) + '}', str(value or ''))
        return result

    def prompt(self, *, transcript: list[dict[str, Any]], variables: dict[str, Any]) -> str:
        '''给大模型的系统提示：把脚本约束交代清楚，避免它跑题。'''
        lines = [
            '你是一名电话外呼机器人，代表公司做首次电话沟通。',
            '要求：口语化、一次只说一两句、不承诺任何价格或合同条款、不编造公司信息。',
            '客户明确拒绝时立刻礼貌结束；客户要求转人工时回答「马上为您转接人工客服」。',
        ]
        if self.content.get('opening'):
            lines.append('开场白：' + self.fill(str(self.content['opening']), variables))
        for node in self.content.get('nodes') or []:
            if isinstance(node, dict) and node.get('say'):
                lines.append('话术要点：' + self.fill(str(node['say']), variables))
        lines.append('已知客户信息：' + str(variables or {}))
        lines.append('对话历史：' + str(transcript or []))
        lines.append('直接输出机器人接下来要说的一句话，不要加任何前缀或解释。')
        return '\n'.join(lines)


def detect_intent(text: str) -> str | None:
    body = str(text or '')
    for level, words in INTENT_KEYWORDS:
        if any(word in body for word in words):
            return level
    return None


def guess_intent(transcript: list[dict[str, Any]]) -> str:
    '''整通对话的意向：取客户说过的最强意向，没提到就是 none。'''
    order = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
    best: str | None = None
    for turn in transcript or []:
        if str(turn.get('role')) != 'customer':
            continue
        level = detect_intent(str(turn.get('text') or ''))
        if level is None:
            continue
        if best is None or order[level] < order[best]:
            best = level
    return best or 'none'