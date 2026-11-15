from src.models import Audit
def record(db,user,action,target):
    actor=user.email if hasattr(user,'email') else str(user)
    db.add(Audit(actor=actor,action=action,target=str(target)))
