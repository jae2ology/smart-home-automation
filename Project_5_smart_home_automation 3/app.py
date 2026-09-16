import os,json,uuid
from datetime import datetime,timedelta
from flask import Flask,render_template,request,redirect,url_for,session,flash,abort,jsonify
from db import get_db,close_db,init_db
from auth import login_required,roles_required
from domain import can_access_home,compare,is_cooldown,command_supported
from integrations import DeviceGateway,WebhookGateway
app=Flask(__name__); app.secret_key='qa-course-secret'; app.config['APP_NAME']='HomePulse 2.0 - Smart Home Automation'; app.teardown_appcontext(close_db); device_gateway=DeviceGateway(); webhook_gateway=WebhookGateway()
def now(): return datetime.utcnow().isoformat(timespec='seconds')
def audit(db,a,t,o,d=''): db.execute('INSERT INTO audit_log(actor_user_id,action,object_type,object_id,details,created_at) VALUES(?,?,?,?,?,?)',(session.get('user_id'),a,t,str(o),d,now()))
@app.before_request
def bootstrap():
    if not os.path.exists(os.path.join(os.path.dirname(__file__),'app.db')): init_db()
@app.context_processor
def inject(): return {'app_name':app.config['APP_NAME'],'session':session}
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=get_db().execute('SELECT * FROM users WHERE lower(email)=lower(?) AND password=? AND active=1',(request.form.get('email',''),request.form.get('password',''))).fetchone()
        if u: session.update(user_id=u['id'],name=u['name'],role=u['role']); return redirect(url_for('homes'))
        flash('Invalid credentials')
    return render_template('login.html',title='Login')
@app.get('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.get('/')
@login_required
def homes():
    db=get_db(); rows=db.execute('SELECT h.*,m.home_role FROM homes h JOIN memberships m ON m.home_id=h.id WHERE m.user_id=? AND m.status="ACTIVE" ORDER BY h.name',(session['user_id'],)).fetchall(); return render_template('homes.html',rows=rows,title='Homes')
@app.get('/homes/<int:hid>')
@login_required
def home(hid):
    db=get_db(); h=db.execute('SELECT * FROM homes WHERE id=?',(hid,)).fetchone(); devices=db.execute('SELECT * FROM devices WHERE home_id=? ORDER BY name',(hid,)).fetchall(); alerts=db.execute("SELECT * FROM alerts WHERE home_id=? AND status!='RESOLVED' ORDER BY id DESC",(hid,)).fetchall(); scenes=db.execute('SELECT * FROM scenes WHERE home_id=? AND active=1',(hid,)).fetchall(); rules=db.execute('SELECT * FROM rules WHERE home_id=? ORDER BY priority',(hid,)).fetchall(); return render_template('home.html',h=h,devices=devices,alerts=alerts,scenes=scenes,rules=rules,title=h['name'])
@app.get('/devices/<int:did>')
@login_required
def device(did):
    db=get_db(); d=db.execute('SELECT d.*,h.name home_name FROM devices d JOIN homes h ON h.id=d.home_id WHERE d.id=?',(did,)).fetchone(); telemetry=db.execute('SELECT * FROM telemetry WHERE device_id=? ORDER BY reported_at DESC LIMIT 100',(did,)).fetchall(); return render_template('device.html',d=d,telemetry=telemetry,title=d['name'])
@app.post('/devices/<int:did>/command')
@login_required
def command(did):
    db=get_db(); d=db.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone(); cmd=request.form['command']; payload=request.form.get('payload','{}'); result=device_gateway.send(d['external_id'],cmd,payload); db.execute('INSERT INTO device_commands(device_id,actor_user_id,command,payload,status,created_at,completed_at) VALUES(?,?,?,?,?,?,?)',(did,session['user_id'],cmd,payload,result['status'],now(),now())); audit(db,'COMMAND','device',did,cmd); db.commit(); return redirect(url_for('device',did=did))
@app.post('/api/device/telemetry')
def ingest_telemetry():
    data=request.get_json(force=True); db=get_db(); token=request.headers.get('X-Device-Token'); tok=db.execute('SELECT * FROM device_tokens WHERE token=? AND revoked_at IS NULL',(token,)).fetchone()
    if not tok: return jsonify(error='invalid token'),401
    device_id=int(data['device_id']); source=data['source_event_id']; existing=db.execute('SELECT id FROM telemetry WHERE source_event_id=?',(source,)).fetchone()
    if existing: return jsonify(status='duplicate',id=existing['id'])
    cur=db.execute('INSERT INTO telemetry(device_id,source_event_id,metric,value,text_value,reported_at,received_at) VALUES(?,?,?,?,?,?,?)',(device_id,source,data['metric'],data.get('value'),data.get('text_value'),data['reported_at'],now())); db.execute('UPDATE devices SET last_seen_at=?,status="ONLINE" WHERE id=?',(data['reported_at'],device_id)); db.commit(); evaluate_rules(db,device_id,data['metric'],data.get('value',data.get('text_value')),source); return jsonify(status='accepted',id=cur.lastrowid),201
def evaluate_rules(db,device_id,metric,value,event_id):
    rules=db.execute('SELECT * FROM rules WHERE trigger_device_id=? AND trigger_metric=? AND enabled=1 ORDER BY priority',(device_id,metric)).fetchall()
    for r in rules:
        if compare(r['trigger_operator'],value,r['trigger_value']) and not is_cooldown(r):
            run=db.execute('INSERT INTO rule_runs(rule_id,trigger_event_id,status,started_at) VALUES(?,?,?,?)',(r['id'],event_id,'RUNNING',now())); actions=db.execute('SELECT a.*,d.external_id FROM rule_actions a JOIN devices d ON d.id=a.device_id WHERE a.rule_id=? ORDER BY a.sequence_no',(r['id'],)).fetchall()
            for a in actions: device_gateway.send(a['external_id'],a['command'],a['payload']); db.execute('INSERT INTO device_commands(device_id,actor_user_id,command,payload,status,created_at) VALUES(?,?,?,?,?,?)',(a['device_id'],None,a['command'],a['payload'],'ACK',now()))
            db.execute('UPDATE rule_runs SET status="SUCCESS",completed_at=? WHERE id=?',(now(),run.lastrowid)); db.execute('UPDATE rules SET last_run_at=? WHERE home_id=?',(now(),r['home_id']))
            if r['name'].lower().find('battery')>=0: create_alert(db,r['home_id'],device_id,'LOW_BATTERY','WARNING',f'Low battery: {value}',event_id)
    db.commit()
def create_alert(db,home_id,device_id,kind,severity,message,event_id):
    key=f'{device_id}:{kind}'; existing=db.execute("SELECT id FROM alerts WHERE dedup_key=? AND status!='RESOLVED'",(key,)).fetchone()
    if existing: return existing['id']
    cur=db.execute('INSERT INTO alerts(home_id,device_id,kind,severity,message,status,dedup_key,created_at) VALUES(?,?,?,?,?,?,?,?)',(home_id,device_id,kind,severity,message,'OPEN',key,now())); return cur.lastrowid
@app.post('/scenes/<int:sid>/run')
@login_required
def run_scene(sid):
    db=get_db(); s=db.execute('SELECT * FROM scenes WHERE id=?',(sid,)).fetchone(); actions=db.execute('SELECT a.*,d.external_id FROM scene_actions a JOIN devices d ON d.id=a.device_id WHERE a.scene_id=? ORDER BY a.sequence_no',(sid,)).fetchall()
    for a in actions: result=device_gateway.send(a['external_id'],a['command'],a['payload']); db.execute('INSERT INTO device_commands(device_id,actor_user_id,command,payload,status,created_at,completed_at) VALUES(?,?,?,?,?,?,?)',(a['device_id'],session['user_id'],a['command'],a['payload'],result['status'],now(),now()))
    db.commit(); return redirect(url_for('home',hid=s['home_id']))
@app.get('/rules/<int:rid>')
@login_required
def rule_detail(rid):
    db=get_db(); r=db.execute('SELECT * FROM rules WHERE id=?',(rid,)).fetchone(); actions=db.execute('SELECT a.*,d.name device FROM rule_actions a JOIN devices d ON d.id=a.device_id WHERE a.rule_id=?',(rid,)).fetchall(); runs=db.execute('SELECT * FROM rule_runs WHERE rule_id=? ORDER BY id DESC LIMIT 30',(rid,)).fetchall(); return render_template('rule.html',r=r,actions=actions,runs=runs,title=r['name'])
@app.post('/rules/<int:rid>/dry-run')
@login_required
def dry_run(rid):
    db=get_db(); r=db.execute('SELECT * FROM rules WHERE id=?',(rid,)).fetchone(); value=request.form.get('value'); matched=compare(r['trigger_operator'],value,r['trigger_value']);
    if matched: evaluate_rules(db,r['trigger_device_id'],r['trigger_metric'],value,'dry-'+str(uuid.uuid4()))
    return jsonify(matched=matched)
@app.post('/jobs/schedules')
@roles_required('admin')
def schedules_job():
    db=get_db(); current=datetime.utcnow(); rows=db.execute('SELECT * FROM schedules WHERE enabled=1 AND cron_hour=? AND cron_minute=?',(current.hour,current.minute)).fetchall(); count=0
    for s in rows:
        if s['scene_id']:
            actions=db.execute('SELECT a.*,d.external_id FROM scene_actions a JOIN devices d ON d.id=a.device_id WHERE a.scene_id=?',(s['scene_id'],)).fetchall()
            for a in actions: device_gateway.send(a['external_id'],a['command'],a['payload'])
        db.execute('INSERT INTO schedule_runs(schedule_id,scheduled_for,status,details,created_at) VALUES(?,?,?,?,?)',(s['id'],now(),'SUCCESS','',now())); db.execute('UPDATE schedules SET last_run_date=? WHERE id=?',(current.date().isoformat(),s['id'])); count+=1
    db.commit(); return jsonify(ran=count)
@app.post('/alerts/<int:aid>/ack')
@login_required
def ack(aid):
    db=get_db(); db.execute('INSERT INTO alert_acknowledgements(alert_id,user_id,note,created_at) VALUES(?,?,?,?)',(aid,session['user_id'],request.form.get('note',''),now())); db.execute("UPDATE alerts SET status='ACKNOWLEDGED' WHERE id=?",(aid,)); db.commit(); return redirect(request.referrer or url_for('homes'))
@app.get('/monitor/alerts')
@roles_required('monitor','admin','installer')
def monitor_alerts():
    rows=get_db().execute("SELECT a.*,h.name home FROM alerts a JOIN homes h ON h.id=a.home_id WHERE a.status!='RESOLVED' ORDER BY a.id DESC").fetchall(); return render_template('alerts.html',rows=rows,title='Monitoring Alerts')
@app.get('/api/homes/<int:hid>/status')
@login_required
def home_status(hid):
    db=get_db(); devices=db.execute('SELECT id,name,device_type,status,last_seen_at FROM devices WHERE home_id=?',(hid,)).fetchall(); alerts=db.execute("SELECT id,kind,severity,status,message FROM alerts WHERE home_id=? AND status!='RESOLVED'",(hid,)).fetchall(); return jsonify(home_id=hid,devices=[dict(d) for d in devices],alerts=[dict(a) for a in alerts])
@app.post('/admin/webhooks/<int:wid>/deliver')
@roles_required('admin')
def webhook_deliver(wid):
    db=get_db(); w=db.execute('SELECT * FROM webhooks WHERE id=?',(wid,)).fetchone(); event_id=request.form.get('event_id') or str(uuid.uuid4()); payload=request.form.get('payload','{}'); result=webhook_gateway.post(w['target_url'],payload,w['secret']); db.execute('INSERT INTO webhook_deliveries(webhook_id,event_id,payload,status,attempt,response_code,created_at,next_retry_at) VALUES(?,?,?,?,?,?,?,?)',(wid,event_id,payload,result['status'],1,result['code'],now(),(datetime.utcnow()+timedelta(minutes=5)).isoformat(timespec='seconds'))); db.commit(); return jsonify(result)
@app.post('/admin/webhook-retry')
@roles_required('admin')
def retry_webhooks():
    db=get_db(); rows=db.execute("SELECT d.*,w.target_url,w.secret FROM webhook_deliveries d JOIN webhooks w ON w.id=d.webhook_id WHERE d.status='FAILED' AND d.attempt<3").fetchall();
    for d in rows: result=webhook_gateway.post(d['target_url'],d['payload'],d['secret']); db.execute('INSERT INTO webhook_deliveries(webhook_id,event_id,payload,status,attempt,response_code,created_at) VALUES(?,?,?,?,?,?,?)',(d['webhook_id'],str(uuid.uuid4()),d['payload'],result['status'],d['attempt']+1,result['code'],now()))
    db.commit(); return jsonify(retried=len(rows))
@app.post('/admin/retention')
@roles_required('admin')
def retention():
    db=get_db(); cutoff=(datetime.utcnow()-timedelta(days=int(request.form.get('days','30')))).isoformat(); count=db.execute('SELECT COUNT(*) c FROM telemetry WHERE reported_at>?',(cutoff,)).fetchone()['c']; db.execute('DELETE FROM telemetry WHERE reported_at>?',(cutoff,)); db.execute('INSERT INTO archives(home_id,kind,record_count,path,created_at) VALUES(?,?,?,?,?)',(1,'TELEMETRY',count,'archive/demo.json',now())); db.commit(); return jsonify(archived=count)
@app.get('/admin/export/<int:hid>')
@roles_required('admin')
def export_home(hid):
    db=get_db(); home=db.execute('SELECT * FROM homes WHERE id=?',(hid,)).fetchone(); devices=db.execute('SELECT d.*,t.token FROM devices d LEFT JOIN device_tokens t ON t.device_id=d.id AND t.revoked_at IS NULL WHERE d.home_id=?',(hid,)).fetchall(); rules=db.execute('SELECT * FROM rules WHERE home_id=?',(hid,)).fetchall(); return jsonify(home=dict(home),devices=[dict(x) for x in devices],rules=[dict(x) for x in rules])
@app.get('/admin/reconciliation')
@roles_required('admin')
def reconcile():
    db=get_db(); issues=[]
    for d in db.execute('SELECT * FROM devices').fetchall():
        latest=db.execute('SELECT MAX(reported_at) t FROM telemetry WHERE device_id=?',(d['id'],)).fetchone()['t']
        if latest and d['last_seen_at']!=latest: issues.append({'device':d['id'],'type':'LAST_SEEN_MISMATCH','device_value':d['last_seen_at'],'telemetry':latest})
    return jsonify(issues=issues)
if __name__=='__main__':
    with app.app_context(): init_db()
    app.run(debug=True)
