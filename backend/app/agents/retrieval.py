"""轻量检索：字符二元组 BM25（中文友好、零外部依赖、确定性）。

接口与 FAISS 风格对齐（add_texts / similarity_search_with_score），知识库大了可平替。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

_LATIN = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文字符二元组 + 英文/数字小写词。"""
    tokens: list[str] = []
    for word in _LATIN.findall(text):
        tokens.append(word.lower())
    # 抽取 CJK 连续段做 bigram
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            buf += ch
        else:
            if len(buf) >= 2:
                tokens.extend(buf[i : i + 2] for i in range(len(buf) - 1))
            elif buf:
                tokens.append(buf)
            buf = ""
    if len(buf) >= 2:
        tokens.extend(buf[i : i + 2] for i in range(len(buf) - 1))
    elif buf:
        tokens.append(buf)
    return tokens


@dataclass
class _Doc:
    title: str
    text: str
    tokens: list[str] = field(default_factory=list)


class BM25Store:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[_Doc] = []
        self.df: dict[str, int] = {}
        self.avg_len = 0.0

    def add_texts(self, items: list[dict]) -> None:
        for it in items:
            toks = tokenize(it.get("title", "") + "\n" + it.get("text", ""))
            self.docs.append(_Doc(it.get("title", ""), it.get("text", ""), toks))
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        total = sum(len(d.tokens) for d in self.docs)
        self.avg_len = total / max(1, len(self.docs))

    def search(self, query: str, k: int = 4) -> list[tuple[dict, float]]:
        q = tokenize(query)
        n = len(self.docs)
        scores: list[float] = []
        for d in self.docs:
            tf: dict[str, int] = {}
            for t in d.tokens:
                tf[t] = tf.get(t, 0) + 1
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                idf = math.log(1 + (n - self.df.get(t, 0) + 0.5) / (self.df.get(t, 0) + 0.5))
                s += idf * tf[t] * (self.k1 + 1) / (
                    tf[t] + self.k1 * (1 - self.b + self.b * len(d.tokens) / max(1e-6, self.avg_len))
                )
            scores.append(s)
        ranked = sorted(zip(self.docs, scores), key=lambda x: x[1], reverse=True)[:k]
        return [
            ({"title": d.title, "text": d.text}, round(s, 4)) for d, s in ranked if s > 0
        ]


def load_kb(kb_dir: str | Path) -> BM25Store:
    """从目录加载知识库：每个 .md/.txt 一个文档，首个 '# ' 标题作 title。"""
    store = BM25Store()
    p = Path(kb_dir)
    if not p.exists():
        return store
    items = []
    for f in sorted(p.glob("*")):
        if f.suffix.lower() not in (".md", ".txt"):
            continue
        text = f.read_text(encoding="utf-8")
        title = f.stem
        for line in text.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        items.append({"title": title, "text": text})
    store.add_texts(items)
    return store
