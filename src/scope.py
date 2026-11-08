"""Which parents may this admin see?  None = everyone (your real admin). A set = only those parents.
The public demo admin is limited to the demo parent, so your own test families stay private.
Override with env DEMO_ADMIN_EMAILS / DEMO_PARENT_EMAILS (comma-separated)."""
import os
from database import User


def _emails(env, default):
    return {e.strip().lower() for e in os.getenv(env, default).split(",") if e.strip()}


def visible_user_ids(user, db):
    if (user.email or "").lower() not in _emails("DEMO_ADMIN_EMAILS", "demo.admin@melodycare.my"):
        return None
    wanted = _emails("DEMO_PARENT_EMAILS", "demo.parent@melodycare.my")
    return {u.id for u in db.query(User).all() if (u.email or "").lower() in wanted}
