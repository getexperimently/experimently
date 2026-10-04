# Segments

A segment is a named group of users. It is one of two kinds, chosen when you create it and
never changed:

- **Rules** (`kind: rules`, the default): the users whose attributes match conditions you
  set, such as plan is `enterprise`. The rule format and its limits are in the
  [API reference](../api/endpoints.md#audience-segments).
- **ID list** (`kind: id_list`): the users whose `user_id` you upload, for example a customer
  export. This page is about these.

The member routes are beta (`x-stability: beta`): their shape may still change. The full
contract and every refusal are in the
[API reference](../api/endpoints.md#segments-made-from-a-list-of-user-ids-beta).

The examples run against the [Quick Start](../getting-started/quick-start.md) stack and its
demo data.

## Sign in

Changing a segment takes the ADMIN or DEVELOPER role. Sign in as the demo administrator:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`.

## Create an ID-list segment

An ID-list segment has no rules. This creates one and saves its id in `$SEGMENT`:

```{.bash exec}
SEGMENT=$(curl -s -X POST localhost:8000/api/v1/segments \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"name": "Enterprise pilot", "kind": "id_list"}' | jq -r .id)

curl -s localhost:8000/api/v1/segments/$SEGMENT \
  -H "Authorization: Bearer $TOKEN" | jq -c '{kind, rules, member_count}'
```
<!-- expect: {"kind":"id_list","rules":null,"member_count":0} -->

It prints `{"kind":"id_list","rules":null,"member_count":0}`.

## Add IDs

Send up to 10,000 IDs per request. Each is 1 to 255 characters and is matched exactly: not
trimmed, not case-folded.

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/segments/$SEGMENT/members \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"add": ["cust-001", "cust-002", "cust-003"]}' | jq -c .
```
<!-- expect: {"added":3,"already_members":0,"member_count":3} -->

It prints `{"added":3,"already_members":0,"member_count":3}`.

**Sending the same IDs again is safe.** An ID already in the segment is counted in
`already_members` and left alone, so after a failure you can send the whole chunk again:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/segments/$SEGMENT/members \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"add": ["cust-003", "cust-004"]}' | jq -c .
```
<!-- expect: {"added":1,"already_members":1,"member_count":4} -->

It prints `{"added":1,"already_members":1,"member_count":4}`.

## Add IDs from a file

A segment holds at most 1,000,000 IDs. Send a longer file in chunks of 10,000, one request
at a time, and stop at the first error. This writes 25,000 IDs, one per line, to a file in a
scratch directory, sends them in three chunks and prints each answer. Each body is piped to
`curl` (`--data-binary @-`): 10,000 IDs are too long for one command-line argument on Linux.

```{.bash exec timeout=300}
cd "$(mktemp -d)"
seq -f 'cust-%06g' 1 25000 > customers.txt
split -l 10000 customers.txt chunk-
for chunk in chunk-*; do
  RESPONSE=$(jq -R . "$chunk" | jq -s '{add: .}' | curl -s -f -X POST localhost:8000/api/v1/segments/$SEGMENT/members \
    -H "Authorization: Bearer $TOKEN" \
    -H 'content-type: application/json' \
    --data-binary @-) || break
  jq -c . <<<"$RESPONSE"
done
```
<!-- expect: "member_count":25004 -->

It prints one line per chunk. The last is `{"added":5000,"already_members":0,"member_count":25004}`.
The file's IDs are written `cust-000001` to `cust-025000`, so none of them was in the segment
before (`cust-001` is a different ID).

A request over a limit answers 422 and adds nothing. The message names the field and the
position, never an ID: `add: at most 10,000 IDs per request`, `add[17]: an ID is 1 to 255
characters`, or, past the cap, `this segment would have 1,000,250 members; a segment holds
at most 1,000,000`.

## Check a user

A user is a member when the `user_id` in the context you send is in the list:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/segments/$SEGMENT/evaluate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"user_context": {"user_id": "cust-002"}}' | jq .is_member
```
<!-- expect: true -->

It prints `true`. A `user_id` that is not in the list, or a context with no `user_id`, prints
`false`.

## Remove IDs

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/segments/$SEGMENT/members/remove \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"remove": ["cust-002", "cust-999"]}' | jq -c .
```
<!-- expect: {"removed":1,"not_members":1,"member_count":25003} -->

It prints `{"removed":1,"not_members":1,"member_count":25003}`: `cust-999` was not a member.

## Limits

| Limit | Value |
|---|---|
| IDs per request | 1 to 10,000 |
| Characters per ID | 1 to 255 |
| IDs per segment | 1,000,000 |
| Who can change members | ADMIN and DEVELOPER (ANALYST and VIEWER get `403`) |

Each add or remove writes one `segment_update` entry to the audit log with the counts, never
the IDs. A rules segment answers `409` on the member routes, and so does an archived one.

**Before you roll a database back** past the release that added ID lists, read
[`37dcb2969766`](../self-hosting/migrations.md#37dcb2969766-adds-segments-made-from-a-list-of-user-ids):
its downgrade deletes every list's members, so it refuses while any list has members.
