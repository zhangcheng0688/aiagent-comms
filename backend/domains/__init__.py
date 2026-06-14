"""V3.0 行业词库加载器。

设计目标：
- 启动时一次性加载所有行业到内存（JSON 小，~22KB）
- 提供 O(1) 查找 (industry, scenario) 配置
- 提供关键词匹配用于意图解析增强
- 提供模板话术直接喂给 LLM
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional


# 默认从项目根目录的 domains/ 加载
_DEFAULT_DOMAINS_DIR = Path(__file__).resolve().parent.parent.parent / "domains"


class DomainLoader:
    """行业词库单例加载器。"""

    def __init__(self, domains_dir: str | Path):
        self.domains_dir = Path(domains_dir)
        self._data: dict | None = None
        self.load()

    def load(self) -> None:
        """从 all.json 加载。"""
        all_path = self.domains_dir / "all.json"
        with open(all_path, "r", encoding="utf-8") as f:
            self._data = json.load(f)
        self._industries = self._data.get("industries", {})

    def list_industries(self) -> list[str]:
        return list(self._industries.keys())

    def get_industry(self, industry: str) -> dict | None:
        return self._industries.get(industry)

    def get_scenario(self, industry: str, scenario: str) -> dict | None:
        ind = self.get_industry(industry)
        if not ind:
            return None
        return ind.get("scenarios", {}).get(scenario)

    def get_keywords(self, industry: str, scenario: str | None = None) -> list[str]:
        """获取某 (industry, scenario?) 的关键词列表。"""
        ind = self.get_industry(industry) or {}
        terms = list(ind.get("common_terms", []))
        if scenario:
            sc = ind.get("scenarios", {}).get(scenario) or {}
            terms.extend(sc.get("keywords", []))
        return terms

    def get_phrasebook(self, industry: str, scenario: str, lang: str = "en") -> list[str]:
        """获取某 (industry, scenario, lang) 的商务套话。"""
        sc = self.get_scenario(industry, scenario) or {}
        return [p["text"] for p in sc.get("phrasebook", []) if p.get("lang") == lang]

    def get_hard_rule_keywords(self, industry: str, scenario: str) -> list[str]:
        sc = self.get_scenario(industry, scenario) or {}
        return sc.get("hard_rule_keywords", [])

    def get_escalation_threshold(self, industry: str, scenario: str) -> dict:
        sc = self.get_scenario(industry, scenario) or {}
        return sc.get("escalation_threshold", {"pct": 20, "abs": 1000, "rounds": 4})

    def detect_industry(self, text: str) -> str | None:
        """根据文本内容检测行业。简单关键词匹配，返回最匹配行业。"""
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for ind_key, ind_data in self._industries.items():
            score = 0
            # 通用术语命中
            for term in ind_data.get("common_terms", []):
                if term.lower().split()[0] in text_lower:  # 第一个词是中文/英文
                    score += 1
            # 场景关键词
            for sc_data in ind_data.get("scenarios", {}).values():
                for kw in sc_data.get("keywords", []):
                    if any(part.lower() in text_lower for part in kw.split() if len(part) > 2):
                        score += 1
            if score > 0:
                scores[ind_key] = score
        if not scores:
            return None
        # mypy 友好：key 显式 lambda
        return max(scores.keys(), key=lambda k: scores[k])

    def detect_scenario(self, text: str, industry: str) -> str | None:
        """根据文本+行业检测场景。"""
        ind = self.get_industry(industry) or {}
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for sc_key, sc_data in ind.get("scenarios", {}).items():
            score = 0
            for kw in sc_data.get("keywords", []):
                if any(part.lower() in text_lower for part in kw.split() if len(part) > 2):
                    score += 1
            # 场景描述命中
            if any(w in text_lower for w in sc_data.get("scenario_desc", "").lower().split()):
                score += 1
            if score > 0:
                scores[sc_key] = score
        if not scores:
            return None
        return max(scores.keys(), key=lambda k: scores[k])

    def build_prompt_injection(self, industry: str, scenario: str, lang: str = "ja") -> str:
        """生成注入到 LLM prompt 的行业上下文片段。"""
        ind = self.get_industry(industry)
        sc = self.get_scenario(industry, scenario)
        if not ind or not sc:
            return ""

        terms = self.get_keywords(industry, scenario)[:15]  # 限制 15 个术语
        phrase = self.get_phrasebook(industry, scenario, lang)
        hr_kw = self.get_hard_rule_keywords(industry, scenario)
        threshold = self.get_escalation_threshold(industry, scenario)
        compliance = ind.get("compliance_requirements", [])

        parts = [
            f"## 行业上下文：{ind.get('label', industry)}",
            f"## 场景：{sc.get('scenario_label', scenario)} - {sc.get('scenario_desc', '')}",
            f"## 典型客户：{', '.join(ind.get('typical_clients', []))}",
            f"## 行业术语（请用对）：\n" + "\n".join(f"  - {t}" for t in terms),
        ]
        if phrase:
            parts.append(f"## 商务套话参考（{lang}）：\n" + "\n".join(f'  - "{p}"' for p in phrase))
        if compliance:
            parts.append(f"## 合规要求：{', '.join(compliance)}")
        if hr_kw:
            parts.append(f"## 硬规则触发关键词（命中即升级人工）：{', '.join(hr_kw)}")
        parts.append(f"## 升级阈值：加价>{threshold['pct']}% 或 >¥{threshold['abs']} 或 {threshold['rounds']} 轮无果 → 升级")

        return "\n\n".join(parts)


# 全局单例
_LOADER: DomainLoader | None = None


def get_domain_loader() -> DomainLoader:
    """获取全局单例（懒加载）。"""
    global _LOADER
    if _LOADER is None:
        # 优先用 env，其次默认路径
        env_dir = os.getenv("DOMAINS_DIR")
        if env_dir:
            _LOADER = DomainLoader(env_dir)
        else:
            _LOADER = DomainLoader(_DEFAULT_DOMAINS_DIR)
    return _LOADER
