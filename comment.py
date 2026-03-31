import json, urllib.request, sys

TOKEN = sys.argv[1]
DISCUSSION_ID = sys.argv[2]
BODY = sys.argv[3]

# Use block string for body
query = f'''
mutation {{
  addDiscussionComment(input: {{
    discussionId: "{DISCUSSION_ID}",
    body: {json.dumps(BODY)}
  }}) {{ comment {{ url }} }}
}}
'''

data = json.dumps({"query": query}).encode()
req = urllib.request.Request(
    "https://api.github.com/graphql",
    data=data,
    headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
if "errors" in result:
    print("ERROR:", result["errors"])
else:
    print("OK:", result["data"]["addDiscussionComment"]["comment"]["url"])
