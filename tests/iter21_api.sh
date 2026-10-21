#!/bin/bash
# helper: iter21 api helper. usage: iter21_api.sh METHOD PATH [JSON]
URL=$(grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2)
TOK=$(curl -s -X POST "$URL/api/auth/login" -H 'Content-Type: application/json' -d '{"password":"BlackCat2233@"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
if [ -n "$3" ]; then
  curl -s -X "$1" "$URL$2" -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d "$3"
else
  curl -s -X "$1" "$URL$2" -H "Authorization: Bearer $TOK"
fi
echo
