import valkey
r = valkey.Valkey(host='redis', port=6379, db=1, password='OqoCT3e6tWShB2aKlqt0S0lP69yioXYY')
stream = b'te.0.common'
group = b'rag_flow_svr_task_broker'
msgs = r.xpending_range(stream, group, min=b'-', max=b'+', count=50)
ids = [m['message_id'] for m in msgs]
print(f'XACK {len(ids)} messages: {[i.decode() for i in ids]}')
if ids:
    acked = r.xack(stream, group, *ids)
    print('acked:', acked)
print('pending now:', r.xpending(stream, group).get('pending', 0))
