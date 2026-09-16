INSERT INTO users(email,password,name,role) VALUES
('owner@example.com','student','Morgan Owner','owner'),('member@example.com','student','Mia Member','member'),('installer@example.com','install','Ian Installer','installer'),('monitor@example.com','monitor','Monica Monitoring','monitor'),('admin@example.com','admin','Avery Admin','admin');
INSERT INTO homes(name,timezone,address_label,owner_user_id,created_at) VALUES('Maple House','America/New_York','Statesboro Residence',1,'2026-08-01T10:00'),('Coastal Condo','America/New_York','Savannah Residence',1,'2026-08-02T10:00');
INSERT INTO memberships(home_id,user_id,home_role,status,created_at) VALUES(1,1,'OWNER','ACTIVE','2026-08-01'),(1,2,'MEMBER','ACTIVE','2026-08-01'),(2,1,'OWNER','ACTIVE','2026-08-02');
INSERT INTO devices(home_id,name,device_type,capabilities,status,last_seen_at,firmware,external_id) VALUES
(1,'Front Door Lock','LOCK','LOCK,UNLOCK,BATTERY','ONLINE','2026-08-18T12:00','1.2.1','dev-lock-1'),
(1,'Hall Motion','MOTION','MOTION,BATTERY','ONLINE','2026-08-18T12:01','2.0.0','dev-motion-1'),
(1,'Hall Light','LIGHT','ON,OFF,DIM','ONLINE','2026-08-18T12:02','3.4.0','dev-light-1'),
(1,'Downstairs Thermostat','THERMOSTAT','TEMPERATURE,SETPOINT,HEAT,COOL','ONLINE','2026-08-18T12:00','5.1.0','dev-thermo-1'),
(2,'Condo Leak Sensor','LEAK','WATER,BATTERY','ONLINE','2026-08-18T11:50','1.0.5','dev-leak-2');
INSERT INTO device_tokens(device_id,token,created_at) VALUES(1,'token-lock-plain','2026-08-01'),(2,'token-motion-plain','2026-08-01'),(3,'token-light-plain','2026-08-01'),(4,'token-thermo-plain','2026-08-01'),(5,'token-leak-plain','2026-08-02');
INSERT INTO telemetry(device_id,source_event_id,metric,value,text_value,reported_at,received_at) VALUES(4,'seed-t1','temperature',74,NULL,'2026-08-18T11:59','2026-08-18T12:00'),(1,'seed-t2','battery',81,NULL,'2026-08-18T11:58','2026-08-18T12:00');
INSERT INTO scenes(home_id,name,created_by,created_at) VALUES(1,'Good Night',1,'2026-08-05');
INSERT INTO scene_actions(scene_id,device_id,command,payload,sequence_no) VALUES(1,3,'OFF','{}',1),(1,1,'LOCK','{}',2),(1,4,'SETPOINT','{"value":70}',3);
INSERT INTO rules(home_id,name,trigger_device_id,trigger_metric,trigger_operator,trigger_value,priority,cooldown_sec,created_by) VALUES(1,'Motion after hours',2,'motion','==','1',10,60,1),(1,'Low battery warning',1,'battery','<','20',5,3600,1);
INSERT INTO rule_actions(rule_id,device_id,command,payload,sequence_no) VALUES(1,3,'ON','{}',1);
INSERT INTO schedules(home_id,name,timezone,cron_hour,cron_minute,weekday_mask,scene_id,enabled) VALUES(1,'Weeknight Good Night','America/New_York',22,30,'0,1,2,3,4',1,1);
INSERT INTO monitoring_enrollments(home_id,status,contact_name,contact_phone,created_at) VALUES(1,'ACTIVE','Morgan Owner','912-555-0101','2026-08-05');
INSERT INTO webhooks(home_id,name,target_url,secret,event_types,active) VALUES(1,'Owner Automation Hook','https://example.invalid/hooks/home','plain-webhook-secret','ALERT,RULE_RUN',1);
