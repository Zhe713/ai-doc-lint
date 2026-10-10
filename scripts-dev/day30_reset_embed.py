"""Day30 重置 embed 任务：全部置 pending 并重新入队（先清队列再执行）。"""
import sys

from app.db.session import SessionLocal
from app.models.document import DocumentTask
from app.tasks.embed import enqueue_embed


def main() -> int:
    db = SessionLocal()
    try:
        db.query(DocumentTask).filter(
            DocumentTask.task_type == "embed").update(
            {"status": "pending"})
        db.commit()
        tasks = (db.query(DocumentTask)
                 .filter(DocumentTask.task_type == "embed").all())
        for t in tasks:
            enqueue_embed(t.id)
        print(f"reset+queued={len(tasks)}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
