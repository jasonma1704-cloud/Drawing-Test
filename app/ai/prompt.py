from __future__ import annotations

EXTRACTION_PROMPT = """
你是资深机械图纸信息提取助手。请从图纸图片中抽取询价所需信息，并严格输出 JSON。

要求：
1. 只根据图纸内容与邮件附带的文字信息判断，不要编造。
2. 如果信息缺失，请使用空字符串、空数组或 null。
3. 输出必须是合法 JSON，不要输出解释、markdown、代码块。
4. 优先提取以下字段：
   - customer_name: 客户/公司名
   - project_name: 项目名
   - part_name: 零件名
   - part_number: 图号/料号
   - material: 材料
   - surface_treatment: 表面处理
   - quantity: 数量
   - tolerance: 公差
   - dimensions: 关键尺寸
   - special_requirements: 特殊要求
   - due_date: 交期
   - quotation_needed: 是否需要报价
   - risk_notes: 风险点/疑点
   - summary: 适合转发给工程师的简要摘要

JSON 格式：
{
  "customer_name": "",
  "project_name": "",
  "part_name": "",
  "part_number": "",
  "material": "",
  "surface_treatment": "",
  "quantity": "",
  "tolerance": "",
  "dimensions": [],
  "special_requirements": [],
  "due_date": "",
  "quotation_needed": true,
  "risk_notes": [],
  "summary": ""
}
""".strip()


def build_email_context_prompt(subject: str, sender: str, body_text: str) -> str:
    return f"""
邮件主题：{subject}
发件人：{sender}

邮件正文：
{body_text[:6000]}
""".strip()
