from app.db.session import SessionLocal
from app.core.security import create_access_token
from app.models.user import User
db = SessionLocal(); u = db.query(User).first()
print(create_access_token(str(u.id))[0])
