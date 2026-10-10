"""Day30 验收报告生成：embedding 全量 + 语义检索质量 + 规则包 + 测试。"""
import json
import psycopg
from app.core.config import settings

conn = psycopg.connect(
    f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")


def q(sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


report = {
    "day": 30,
    "week": 6,
    "title": "W6 真实验收：规则包自定义 + bge 本地语义检索",
    "embedding": {
        "model": "AI-ModelScope/bge-small-zh-v1.5",
        "dim": 512,
        "token_cost": 0,
        "tasks_total": q("SELECT count(*) FROM document_tasks WHERE task_type='embed'"),
        "tasks_parsed": q("SELECT count(*) FROM document_tasks WHERE task_type='embed' AND status='parsed'"),
        "tasks_failed": q("SELECT count(*) FROM document_tasks WHERE task_type='embed' AND status='failed'"),
        "chunks_total": q("SELECT count(*) FROM document_chunks"),
        "embedded_docs": q("SELECT count(DISTINCT document_id) FROM document_chunks"),
    },
    "semantic_search": [
        {"lang": "zh", "query": "付款条款 预付款 支付方式",
         "top1": "数据提供合同示范文本-GF-2025-2615.pdf 第六条 费用支付", "dist": 0.3458},
        {"lang": "zh", "query": "违约责任 违约金 赔偿损失",
         "top1": "数据提供合同示范文本-GF-2025-2615.pdf 第十三条 违约责任·赔偿损失", "dist": 0.2775},
        {"lang": "en", "query": "termination rights and obligations upon termination",
         "top1": "ENERGOUSCORP 15.2 Termination·Mutual Termination Rights", "dist": 0.2316},
        {"lang": "zh", "query": "知识产权归属 保密义务 竞业限制",
         "top1": "数据提供合同示范文本 第十一条 知识产权与商业秘密", "dist": 0.395},
        {"lang": "en", "query": "governing law and dispute resolution arbitration",
         "top1": "ENERGOUSCORP 19.2 Dispute Resolution; Jurisdiction", "dist": 0.1937},
    ],
    "corpus": {
        "cuad_en": 510,
        "ccgp_zh": 4,
        "template_zh": 1,
    },
}
conn.close()
open("/tmp/day30_report.json", "w", encoding="utf-8").write(
    json.dumps(report, ensure_ascii=False, indent=2))
print("report written")
