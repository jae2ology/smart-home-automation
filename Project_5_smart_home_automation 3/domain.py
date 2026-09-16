from datetime import datetime

def can_access_home(db,user_id,home_id):
    return db.execute('SELECT * FROM memberships WHERE home_id=? AND user_id=? AND status="ACTIVE"',(home_id,user_id)).fetchone()
def compare(op,left,right):
    try: l=float(left); r=float(right)
    except (TypeError,ValueError): l=str(left); r=str(right)
    return {'==':l==r,'!=':l!=r,'<':l<r,'>':l>r,'<=':l<=r,'>=':l>=r}.get(op,False)
def is_cooldown(rule):
    if not rule['last_run_at']: return False
    return (datetime.utcnow()-datetime.fromisoformat(rule['last_run_at'])).total_seconds()<rule['cooldown_sec']
def command_supported(device,command): return command in (device['capabilities'] or '').split(',')
