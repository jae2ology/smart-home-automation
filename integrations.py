import uuid
class DeviceGateway:
    def send(self,external_id,command,payload): return {'status':'ACK','gateway_id':'CMD-'+str(uuid.uuid4())[:8]}
class WebhookGateway:
    def post(self,url,payload,signature): return {'status':'FAILED','code':503}
