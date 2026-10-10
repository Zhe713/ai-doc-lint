"""Day30 验收：为全部已解析文档创建向量化任务（幂等，create_embed_task 内部已入队）。"""
import sys

from app.db.session import SessionLocal
from app.models.document import Document
from app.tasks.embed import create_embed_task

LIMIT = 5000


def main() -> int:
    db = SessionLocal()
    try:
        docs = (db.query(Document)
                .filter(Document.status == "parsed")
                .order_by(Document.created_at.asc())
                .limit(LIMIT)
                .all())
        queued = 0
        for doc in docs:
            task = create_embed_task(db, doc)
            if task is not None:
                queued += 1
        print(f"docs={len(docs)} queued={queued}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
