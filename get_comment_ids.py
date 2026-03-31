import json, urllib.request, sys

TOKEN = sys.argv[1]
DISC_NUM = sys.argv[2]

query = f'''
{{
  repository(owner:"sfex11", name:"xiaomi_1_public") {{
    discussion(number: {DISC_NUM}) {{
      comments(first: 10) {{
        nodes {{ id databaseId body }}
      }}
    }}
  }}
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
for c in result["data"]["repository"]["discussion"]["comments"]["nodes"]:
    print(f"{c['id']}")
