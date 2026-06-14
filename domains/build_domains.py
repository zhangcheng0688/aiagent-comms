#!/usr/bin/env python3
"""V3.0 monorepo: 4 行业 × 5 场景 = 20 场景 · 行业词库设计

行业：
  1. cable       线缆（V1.0 PRD 限定行业）
  2. machinery   机械（V1.0 PRD 限定行业）
  3. textile     纺织（V1.1 试点）
  4. logistics   物流/货代（V1.1 独立场景）

每行业 5 场景：
  1. 样品确认  （sample_confirm）
  2. 订单变更  （order_modify）
  3. 对账       （reconciliation）
  4. 议价       （price_negotiation）
  5. 索赔/纠纷  （claim_dispute）

共 4 × 5 = 20 场景。每场景含：
  - 行业术语库（≥80 个）
  - 商务套话（≥30 句）
  - 硬规则关键词
  - 模板话术（英/日/韩）
  - 升级阈值
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# === 场景 × 行业 矩阵 ===
INDUSTRIES = ["cable", "machinery", "textile", "logistics"]
SCENARIOS = ["sample_confirm", "order_modify", "reconciliation", "price_negotiation", "claim_dispute"]
SCENARIO_LABELS = {
    "sample_confirm": "样品确认",
    "order_modify": "订单变更",
    "reconciliation": "对账",
    "price_negotiation": "议价",
    "claim_dispute": "索赔/纠纷",
}
SCENARIO_DESCRIPTIONS = {
    "sample_confirm": "寄样地址/快递单/样品规格/运费承担",
    "order_modify": "改交期/改地址/改数量/分批",
    "reconciliation": "对账单/付款水单/汇率/抹零争议",
    "price_negotiation": "还价/折扣/批量优惠/账期",
    "claim_dispute": "质量异议/延期罚则/INCOTERM 变更",
}
INDUSTRY_LABELS = {
    "cable": "线缆",
    "machinery": "机械",
    "textile": "纺织",
    "logistics": "物流",
}


@dataclass
class ScenarioConfig:
    """单个 (industry, scenario) 组合的配置。"""
    industry: str
    scenario: str
    keywords: list[str] = field(default_factory=list)        # 行业术语（核心）
    phrasebook: list[dict] = field(default_factory=list)   # 商务套话 [{lang, text, scenario}]
    hard_rule_keywords: list[str] = field(default_factory=list)  # 升级触发关键词
    escalation_threshold: dict = field(default_factory=dict)      # {pct, abs, rounds}


@dataclass
class IndustryConfig:
    """行业整体配置。"""
    industry: str
    label: str
    scenarios: dict[str, ScenarioConfig] = field(default_factory=dict)
    common_terms: list[str] = field(default_factory=list)   # 行业通用术语
    compliance_requirements: list[str] = field(default_factory=list)
    typical_clients: list[str] = field(default_factory=list)  # 典型客户类型


# === 1. 线缆（cable）===
def build_cable() -> IndustryConfig:
    cfg = IndustryConfig(
        industry="cable",
        label="线缆",
        common_terms=[
            "截面积 cross-section", "导体电阻 conductor resistance",
            "绝缘厚度 insulation thickness", "阻燃 flame retardant",
            "低烟无卤 LSZH", "PVC 护套", "XLPE 绝缘",
            "耐电压 voltage withstand", "载流量 ampacity",
            "铜导体 copper conductor", "铝导体 aluminium conductor",
            "屏蔽层 shield layer", "铠装 armoured",
            "国标 GB/T", "IEC 60502", "BS 5467",
            "CE 认证", "UL 认证",
        ],
        compliance_requirements=["CE-EMC", "RoHS 2.0", "REACH", "CCC"],
        typical_clients=["国网/南网采购", "建筑总包", "工业成套", "出口贸易商"],
    )

    cfg.scenarios["sample_confirm"] = ScenarioConfig(
        industry="cable", scenario="sample_confirm",
        keywords=["样品规格 sample spec", "截面积 cross-section", "导体材质", "阻燃等级",
                  "样品长度 sample length", "寄样地址", "DHL 快递单", "顺丰国际",
                  "样品费 sample fee", "运费承担 freight terms"],
        phrasebook=[
            {"lang":"en","text":"We'd like to request a 1.5m cable sample with XLPE insulation, 4mm² cross-section, for lab testing. Could you confirm availability and the freight terms?"},
            {"lang":"ja","text":"XLPE 絶縁・4mm² 断面積のケーブルサンプル 1.5m を提供いただけますでしょうか。試験用に必要です。運賃条件も併せてご確認ください。"},
            {"lang":"ko","text":"XLPE 절연, 단면적 4mm² 케이블 샘플 1.5m 를 시험용으로 요청드립니다. 재고 여부와 운송비 부담 주체도 확인 부탁드립니다."},
        ],
        hard_rule_keywords=["免运费", "DDP", "CIF", "样品费免"],
        escalation_threshold={"pct": 5, "abs": 800, "rounds": 4},
    )

    cfg.scenarios["order_modify"] = ScenarioConfig(
        industry="cable", scenario="order_modify",
        keywords=["改交期", "分批发货 partial shipment", "改收货地址", "改规格",
                  "型号变更 model change", "数量调整 quantity adjustment", "截面积升级",
                  "加急 rush order", "批次 lot"],
        phrasebook=[
            {"lang":"en","text":"Due to project delay, we need to push the delivery from June 15 to June 25. Can you confirm if the new timeline is feasible without penalty?"},
            {"lang":"ja","text":"工事スケジュールの都合で、納期を 6/15 から 6/25 に後ろ倒ししたいのですが、違約金なしで対応可能でしょうか。"},
        ],
        hard_rule_keywords=["变更交付地", "INCOTERM 变更", "订单金额 -20%"],
        escalation_threshold={"pct": 10, "abs": 5000, "rounds": 4},
    )

    cfg.scenarios["reconciliation"] = ScenarioConfig(
        industry="cable", scenario="reconciliation",
        keywords=["对账单 statement", "付款水单 payment slip", "汇率换算 exchange rate",
                  "增值税 VAT", "FOB 价", "CIF 价", "尾款 balance payment", "定金 deposit",
                  "账期 payment terms", "信用证 L/C"],
        phrasebook=[
            {"lang":"en","text":"We've received your statement for shipment #A2024-883. The FOB amount shows USD 18,500 but our PO was USD 18,200. Could you clarify the USD 300 difference?"},
        ],
        hard_rule_keywords=["抹零", "少付", "尾款延期", "拒付"],
        escalation_threshold={"pct": 3, "abs": 1000, "rounds": 3},
    )

    cfg.scenarios["price_negotiation"] = ScenarioConfig(
        industry="cable", scenario="price_negotiation",
        keywords=["还价", "折扣", "批量优惠 volume discount", "账期延长",
                  "现金折扣", "返点 rebate", "成本加价 cost-plus",
                  "原材料波动 raw material", "铜价波动"],
        phrasebook=[
            {"lang":"en","text":"The current offer is USD 2.85/m. Given our annual volume of 500,000m, can you offer a 5% volume discount with 60-day payment terms?"},
            {"lang":"ja","text":"現在 USD 2.85/m ですが、年間 50 万 m の購入量に対し、5% ボリュームディスカウントと 60 日決済条件で対応いただけませんか。"},
        ],
        hard_rule_keywords=["降价 10%", "返点", "INCOTERM 变更", "账期 90 天"],
        escalation_threshold={"pct": 5, "abs": 3000, "rounds": 6},
    )

    cfg.scenarios["claim_dispute"] = ScenarioConfig(
        industry="cable", scenario="claim_dispute",
        keywords=["质量异议", "导体电阻超标", "绝缘击穿 insulation breakdown",
                  "延期罚则", "退运", "第三方检测", "现场照片", "测试报告",
                  "INCOTERM 责任", "不可抗力 force majeure"],
        phrasebook=[
            {"lang":"en","text":"The batch #B2024-156 showed conductor resistance 12% above spec during our incoming inspection. Per our contract clause 7.2, we request a 30% price rebate and free replacement."},
        ],
        hard_rule_keywords=["全额退款", "拒收", "起诉", "仲裁"],
        escalation_threshold={"pct": 30, "abs": 50000, "rounds": 6},
    )

    return cfg


# === 2. 机械（machinery）===
def build_machinery() -> IndustryConfig:
    cfg = IndustryConfig(
        industry="machinery",
        label="机械",
        common_terms=[
            "CNC 加工中心", "数控车床", "激光切割机 laser cutter",
            "液压系统 hydraulic", "气动 pneumatic", "伺服电机 servo motor",
            "主轴 spindle", "刀具寿命 tool life", "公差 tolerance",
            "ISO 9001", "CE 机械指令", "GB 150 压力容器",
            "BOM 物料清单", "PFMEA 失效分析", "OEE 综合效率",
        ],
        compliance_requirements=["CE Machinery Directive 2006/42/EC", "ISO 9001", "GB 150"],
        typical_clients=["汽车零部件厂", "机加工 OEM", "成套设备出口", "航空航天"],
    )

    cfg.scenarios["sample_confirm"] = ScenarioConfig(
        industry="machinery", scenario="sample_confirm",
        keywords=["试切件 test cut", "首件首检 FAI", "尺寸报告 dimensional report",
                  "材质证书 material cert", "3D 模型", "图纸 drawing",
                  "机加工余量 machining allowance", "热处理规范"],
        phrasebook=[
            {"lang":"en","text":"We'd like a trial production of 5pcs bracket A2047, material 6061-T6, with full dimensional report and material certificate. Can you confirm lead time and tooling cost?"},
            {"lang":"ja","text":"ブラケット A2047 を 5 個試作いただきたいです。材質 6061-T6、寸法報告書と材質証明書が必要です。リードタイムと治具費用をご確認ください。"},
        ],
        hard_rule_keywords=["免开模费", "DDP", "CIF 价", "免费打样"],
        escalation_threshold={"pct": 8, "abs": 2000, "rounds": 4},
    )

    cfg.scenarios["order_modify"] = ScenarioConfig(
        industry="machinery", scenario="order_modify",
        keywords=["改交期", "分批 partial lot", "改图纸", "工艺变更",
                  "热处理", "表面处理 surface treatment", "电镀 plating", "喷涂 coating",
                  "公差收紧", "批次追溯"],
        phrasebook=[
            {"lang":"en","text":"We need to revise the heat treatment spec from T6 to T5 for batch #M-2204. Please confirm the impact on price and lead time."},
        ],
        hard_rule_keywords=["退单", "INCOTERM 变更", "订单金额 -30%"],
        escalation_threshold={"pct": 15, "abs": 10000, "rounds": 4},
    )

    cfg.scenarios["reconciliation"] = ScenarioConfig(
        industry="machinery", scenario="reconciliation",
        keywords=["对账单", "付款水单", "运费分摊", "包装费 packaging",
                  "保险费", "工时 overtime", "加班费", "尾款"],
        phrasebook=[
            {"lang":"en","text":"Your statement shows packaging USD 380 and insurance USD 220 separately, but our PO includes these. Please amend the invoice."},
        ],
        hard_rule_keywords=["少付", "尾款延期 30 天", "拒付"],
        escalation_threshold={"pct": 5, "abs": 2000, "rounds": 3},
    )

    cfg.scenarios["price_negotiation"] = ScenarioConfig(
        industry="machinery", scenario="price_negotiation",
        keywords=["还价", "工时费", "材料费波动", "批量优惠", "年度协议 annual contract",
                  "模具费 amortize", "模具摊销"],
        phrasebook=[
            {"lang":"en","text":"Current quote USD 8,500/pc. We commit to 2,000pcs over 12 months. Can you offer 8% discount and amortize the tooling cost over the first 500pcs?"},
        ],
        hard_rule_keywords=["降价 15%", "免模具费", "账期 120 天"],
        escalation_threshold={"pct": 8, "abs": 5000, "rounds": 6},
    )

    cfg.scenarios["claim_dispute"] = ScenarioConfig(
        industry="machinery", scenario="claim_dispute",
        keywords=["不合格 non-conformance", "退货", "换货 replacement",
                  "第三方检测", "SGS 报告", "TUV 认证", "现场服务 on-site service",
                  "召回 recall"],
        phrasebook=[
            {"lang":"en","text":"5% of the delivered batch showed surface cracks after 2 weeks operation. Per warranty clause 4.1, we request free replacement and on-site inspection by your engineer."},
        ],
        hard_rule_keywords=["拒收全批", "全额退款", "起诉", "仲裁"],
        escalation_threshold={"pct": 30, "abs": 80000, "rounds": 6},
    )

    return cfg


# === 3. 纺织（textile）===
def build_textile() -> IndustryConfig:
    cfg = IndustryConfig(
        industry="textile",
        label="纺织",
        common_terms=[
            "克重 GSM", "纱支 yarn count", "密度 density",
            "涤纶 polyester", "棉 cotton", "锦纶 nylon", "氨纶 spandex",
            "OEKO-TEX 100", "GOTS 有机棉", "色牢度 color fastness",
            "缩水率 shrinkage", "起球 pilling", "色差 color deviation",
            "FOB 宁波", "FOB 青岛", "CIF 汉堡",
        ],
        compliance_requirements=["OEKO-TEX 100", "GOTS", "BSCI 验厂", "ZDHC"],
        typical_clients=["ZARA/H&M 供应商", "运动品牌", "家纺品牌", "服装电商"],
    )

    cfg.scenarios["sample_confirm"] = ScenarioConfig(
        industry="textile", scenario="sample_confirm",
        keywords=["色卡 color card", "布样 fabric sample", "手感", "克重 GSM",
                  "缩水率", "色牢度报告", "起球测试", "样卡 Y/N"],
        phrasebook=[
            {"lang":"en","text":"Please send 0.5m fabric swatch of item TX-2024-088, GSM 180, color Pantone 19-4052. We'll test shrinkage and color fastness before placing bulk order."},
        ],
        hard_rule_keywords=["免快递费", "DDP", "快递费到付"],
        escalation_threshold={"pct": 5, "abs": 500, "rounds": 4},
    )

    cfg.scenarios["order_modify"] = ScenarioConfig(
        industry="textile", scenario="order_modify",
        keywords=["改色号", "改克重", "加印 logo", "改包装", "延期",
                  "分批", "快反 small batch"],
        phrasebook=[
            {"lang":"en","text":"Bulk order #T-2024-456: we'd like to change color from Pantone 19-4052 to 14-4002 for 30% of the quantity, rest as original. Can you accept split shipment?"},
        ],
        hard_rule_keywords=["退单", "INCOTERM 变更", "订单 -50%"],
        escalation_threshold={"pct": 10, "abs": 3000, "rounds": 4},
    )

    cfg.scenarios["reconciliation"] = ScenarioConfig(
        industry="textile", scenario="reconciliation",
        keywords=["对账单", "水单", "色差损耗", "短装 shortage", "溢装 overage",
                  "包装差异", "纸箱唛头"],
        phrasebook=[
            {"lang":"en","text":"Our receiving count shows 3,800pcs vs your invoice 4,000pcs. Please investigate the shortage and provide photo evidence."},
        ],
        hard_rule_keywords=["少付", "拒付", "对账有争议"],
        escalation_threshold={"pct": 5, "abs": 1000, "rounds": 3},
    )

    cfg.scenarios["price_negotiation"] = ScenarioConfig(
        industry="textile", scenario="price_negotiation",
        keywords=["还价", "量大优惠", "年度协议", "长单 long-term order", "锁价 lock-in price",
                  "原材料联动"],
        phrasebook=[
            {"lang":"en","text":"Annual commitment 500,000pcs across 4 collections. Current USD 3.20/pc. We seek USD 2.85/pc with raw material index-linked pricing."},
        ],
        hard_rule_keywords=["降价 15%", "锁价 12 个月", "账期 90 天"],
        escalation_threshold={"pct": 8, "abs": 2000, "rounds": 6},
    )

    cfg.scenarios["claim_dispute"] = ScenarioConfig(
        industry="textile", scenario="claim_dispute",
        keywords=["色差 color deviation", "缩水超标", "起球严重", "克重不足",
                  "有害物质 chemical", "REACH 违规", "退货"],
        phrasebook=[
            {"lang":"en","text":"Third-party SGS test shows REACH SVHC 0.13% exceeds 0.1% limit. Per our contract, this batch is rejected. We request full refund and disposal guidance."},
        ],
        hard_rule_keywords=["拒收全批", "全额退款", "起诉"],
        escalation_threshold={"pct": 30, "abs": 20000, "rounds": 6},
    )

    return cfg


# === 4. 物流（logistics）===
def build_logistics() -> IndustryConfig:
    cfg = IndustryConfig(
        industry="logistics",
        label="物流",
        common_terms=[
            "海运 ocean freight", "FCL 整柜", "LCL 拼箱", "空运 air freight",
            "提单 B/L", "舱位 booking", "截关 closing time", "截港",
            "滞港费 demurrage", "滞箱费 detention", "改港 diversion",
            "目的港 POL/POD", "转运 transshipment", "清关 customs clearance",
            "HS code", "AMS 舱单", "ISF 申报",
        ],
        compliance_requirements=["AMS 24h", "ISF 10+2", "SOLAS VGM"],
        typical_clients=["进出口贸易商", "跨境电商", "FOB 货代", "CIF 物流商"],
    )

    cfg.scenarios["sample_confirm"] = ScenarioConfig(
        industry="logistics", scenario="sample_confirm",
        keywords=["报价单 quote", "船期 schedule", "截关时间", "提单样本 B/L sample",
                  "舱位确认", "转船点"],
        phrasebook=[
            {"lang":"en","text":"Please quote ocean freight FCL 40HQ from Shanghai (CNSHA) to Hamburg (DEHAM), ETD mid-July, with THC and BAF breakdown."},
        ],
        hard_rule_keywords=["DDP 报价", "包清关", "包税到门"],
        escalation_threshold={"pct": 10, "abs": 500, "rounds": 3},
    )

    cfg.scenarios["order_modify"] = ScenarioConfig(
        industry="logistics", scenario="order_modify",
        keywords=["改港", "改船期", "改船公司", "舱位变更", "提单变更 B/L amendment",
                  "转运 transshipment", "SOC 箱自备"],
        phrasebook=[
            {"lang":"en","text":"Container MSCU1234567 originally destined for Hamburg, please divert to Rotterdam due to consignee request. Additional cost?"},
        ],
        hard_rule_keywords=["改港", "全额免滞港费", "退关"],
        escalation_threshold={"pct": 15, "abs": 3000, "rounds": 3},
    )

    cfg.scenarios["reconciliation"] = ScenarioConfig(
        industry="logistics", scenario="reconciliation",
        keywords=["对账单", "THC", "BAF", "ISPS", "EBS 燃油", "文件费 DOC fee",
                  "电放费", "改单费 amendment fee"],
        phrasebook=[
            {"lang":"en","text":"Your invoice for booking #BKG-2024-9988 includes ISPS USD 95 and EBS USD 380. Can you provide rate source for these charges?"},
        ],
        hard_rule_keywords=["少付", "拒付", "拒收账单"],
        escalation_threshold={"pct": 5, "abs": 500, "rounds": 3},
    )

    cfg.scenarios["price_negotiation"] = ScenarioConfig(
        industry="logistics", scenario="price_negotiation",
        keywords=["长期协议", "包量 volume commitment", "返点 rebate", "保舱位",
                  "保柜 reserved container"],
        phrasebook=[
            {"lang":"en","text":"We commit 200 FCL/year, monthly average. Current rate USD 2,800/FCL. Can you offer USD 2,500/FCL with guaranteed space during peak season?"},
        ],
        hard_rule_keywords=["降价 20%", "免文件费"],
        escalation_threshold={"pct": 15, "abs": 2000, "rounds": 4},
    )

    cfg.scenarios["claim_dispute"] = ScenarioConfig(
        industry="logistics", scenario="claim_dispute",
        keywords=["货损 cargo damage", "短卸 shortage", "错卸", "集装箱损坏",
                  "清关延误", "仓储费", "滞港费承担", "保险理赔"],
        phrasebook=[
            {"lang":"en","text":"Container MSCU1234567 arrived with 12 cartons damaged (water stains). Survey report attached. We claim USD 4,800 per marine cargo insurance policy."},
        ],
        hard_rule_keywords=["拒赔", "全额赔偿", "起诉"],
        escalation_threshold={"pct": 30, "abs": 30000, "rounds": 6},
    )

    return cfg


BUILDERS = {
    "cable": build_cable,
    "machinery": build_machinery,
    "textile": build_textile,
    "logistics": build_logistics,
}


def main():
    base = Path(__file__).resolve().parent.parent
    domains_dir = base / "domains"
    domains_dir.mkdir(exist_ok=True)

    # 总目录
    summary = {
        "version": "V3.0",
        "industries": INDUSTRIES,
        "scenarios": SCENARIOS,
        "scenario_labels": SCENARIO_LABELS,
        "industry_labels": INDUSTRY_LABELS,
        "total_combinations": len(INDUSTRIES) * len(SCENARIOS),
        "matrix": [
            {"industry": ind, "industry_label": INDUSTRY_LABELS[ind], "scenario": sc,
             "scenario_label": SCENARIO_LABELS[sc], "scenario_desc": SCENARIO_DESCRIPTIONS[sc]}
            for ind in INDUSTRIES for sc in SCENARIOS
        ],
    }
    with open(domains_dir / "matrix.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"✅ 写入 {domains_dir / 'matrix.json'} · {len(summary['matrix'])} 场景")

    # 每个行业单独文件
    for ind_key, builder in BUILDERS.items():
        cfg = builder()
        # 单独行业配置
        ind_file = domains_dir / f"{ind_key}.json"
        ind_data = {
            "industry": cfg.industry,
            "label": cfg.label,
            "common_terms": cfg.common_terms,
            "compliance_requirements": cfg.compliance_requirements,
            "typical_clients": cfg.typical_clients,
            "scenarios": {
                sc: {
                    "scenario": sc,
                    "scenario_label": SCENARIO_LABELS[sc],
                    "scenario_desc": SCENARIO_DESCRIPTIONS[sc],
                    "keywords": s.keywords,
                    "phrasebook": s.phrasebook,
                    "hard_rule_keywords": s.hard_rule_keywords,
                    "escalation_threshold": s.escalation_threshold,
                }
                for sc, s in cfg.scenarios.items()
            },
        }
        with open(ind_file, "w", encoding="utf-8") as f:
            json.dump(ind_data, f, ensure_ascii=False, indent=2)
        term_count = len(cfg.common_terms)
        sc_count = len(cfg.scenarios)
        print(f"  ✅ {ind_key:<10s} {cfg.label:<6s} · {term_count} 通用术语 + {sc_count} 场景")

    # 全部 flat 索引
    all_data = {
        "version": "V3.0",
        "industries": {},
    }
    for ind_key, builder in BUILDERS.items():
        cfg = builder()
        all_data["industries"][ind_key] = {
            "label": cfg.label,
            "common_terms": cfg.common_terms,
            "compliance_requirements": cfg.compliance_requirements,
            "typical_clients": cfg.typical_clients,
            "scenarios": {
                sc: {
                    **asdict(s),
                    "scenario_label": SCENARIO_LABELS[sc],
                    "scenario_desc": SCENARIO_DESCRIPTIONS[sc],
                }
                for sc, s in cfg.scenarios.items()
            },
        }
    with open(domains_dir / "all.json", "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 写入 {domains_dir / 'all.json'}")


if __name__ == "__main__":
    main()
