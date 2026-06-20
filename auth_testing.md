# Atmos Auth-Gated Testing Playbook

1) Create a test user + session in MongoDB:

```
mongosh test_database --eval "
var u='test-user-'+Date.now(), s='test_session_'+Date.now();
db.users.insertOne({user_id:u,email:'qa.'+Date.now()+'@example.com',name:'QA',picture:null,created_at:new Date().toISOString()});
db.user_sessions.insertOne({user_id:u,session_token:s,expires_at:new Date(Date.now()+7*24*60*60*1000).toISOString(),created_at:new Date().toISOString()});
print(s); print(u);
"
```

2) Backend smoke (Bearer header works because the dependency accepts `Authorization`):
```
TOKEN=<paste>
API=https://ai-testing-agent.preview.emergentagent.com/api
curl -s $API/auth/me -H "Authorization: Bearer $TOKEN"
curl -s $API/projects -H "Authorization: Bearer $TOKEN"
curl -s -X POST $API/projects -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"name":"Stripe","url":"https://stripe.com"}'
```

3) Browser SSE / cookie-based UI testing:
```
context.add_cookies([{
  "name":"session_token","value":TOKEN,
  "domain":"ai-testing-agent.preview.emergentagent.com",
  "path":"/","httpOnly":True,"secure":True,"sameSite":"None"
}])
```
