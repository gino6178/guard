"""The fact-master field dictionary (欄位字典): one place that defines each checked field."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    kind: str  # org | text | amount | date | quantity | duration | item | ref
    severity: str
    per_item: bool = False
    labels: tuple[str, ...] = ()  # label words used by the rule extractor ("label：value")


FIELDS: dict[str, FieldDef] = {f.key: f for f in [
    FieldDef("client_name", "客戶名稱", "org", "high",
             labels=("客戶名稱", "客戶", "甲方", "委託單位", "委託人", "買方", "採購單位", "需求單位")),
    FieldDef("vendor_name", "承攬廠商", "org", "medium",
             labels=("乙方", "承攬廠商", "廠商名稱", "供應商", "賣方", "執行單位", "承攬單位")),
    FieldDef("project_name", "專案名稱", "text", "high",
             labels=("專案名稱", "案名", "計畫名稱", "標案名稱", "專案")),
    FieldDef("total_amount", "總金額", "amount", "high",
             labels=("合約總價", "合約總金額", "總金額", "總價", "報價總額", "總計", "合計", "契約總價", "專案總價", "預算金額", "計畫總經費", "總經費")),
    FieldDef("sign_date", "簽約日期", "date", "medium", labels=("簽約日期", "簽訂日期", "立約日期", "簽署日期")),
    FieldDef("start_date", "開始日期", "date", "medium", labels=("開始日期", "啟動日期", "專案開始", "開工日期", "履約開始")),
    FieldDef("delivery_date", "交付日期", "date", "high",
             labels=("交付日期", "交貨日期", "交期", "完成日期", "預計交付", "交付期限", "履約期限", "上線日期", "結案日期")),
    FieldDef("acceptance_date", "驗收日期", "date", "medium", labels=("驗收日期", "驗收期限", "預定驗收")),
    FieldDef("quote_valid_until", "報價有效期限", "date", "medium", labels=("報價有效期限", "有效期限", "報價有效期", "有效日期")),
    FieldDef("warranty", "保固期", "duration", "medium", labels=("保固期", "保固期間", "保固", "保固期限")),
    FieldDef("payment_terms", "付款條件", "text", "medium", labels=("付款條件", "付款方式", "付款辦法")),
    FieldDef("deliverable", "交付項目", "item", "medium", per_item=True),
    FieldDef("quantity", "數量", "quantity", "medium", per_item=True),
    FieldDef("unit_price", "單價", "amount", "medium", per_item=True),
    FieldDef("line_total", "小計", "amount", "medium", per_item=True),
    FieldDef("spec", "規格", "text", "medium", per_item=True),
    FieldDef("responsibility", "責任歸屬", "text", "medium", per_item=True),
    FieldDef("version_ref", "引用版本", "ref", "low", per_item=True),
]}

# Header words that identify columns of an item table (報價明細、交付清單、規格表 ...)
ITEM_HEADERS = ("品名", "項目", "交付項目", "交付物", "品項", "工作項目", "項目名稱", "交付內容", "名稱", "設備名稱", "模組")
QTY_HEADERS = ("數量",)
UNIT_PRICE_HEADERS = ("單價",)
LINE_TOTAL_HEADERS = ("小計", "複價", "金額", "總價")
SPEC_HEADERS = ("規格", "規格說明", "技術規格", "規格需求", "驗收標準", "說明")
RESP_HEADERS = ("負責單位", "負責方", "權責", "負責人", "責任歸屬", "執行單位")

# Which document types are authoritative for which fields (earlier = more authoritative)
AUTHORITY = ["contract", "quotation", "acceptance", "spec", "sow", "proposal", "slides", "minutes", "other"]
# Doc types expected to enumerate the full deliverable list (used for omission checks)
ENUMERATING_TYPES = {"contract", "quotation", "acceptance", "spec", "sow"}
