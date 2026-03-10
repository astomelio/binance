"""Check status of a Dagster run. Disposable helper."""
import json
import sys
import requests

RUN_ID = sys.argv[1] if len(sys.argv) > 1 else None
DAGSTER_URL = "http://127.0.0.1:3070/graphql"


def gql(query, variables=None):
    r = requests.post(DAGSTER_URL, json={"query": query, **({"variables": variables} if variables else {})}, timeout=15)
    return r.json()


if not RUN_ID:
    data = gql("""{ runsOrError(limit: 3) { ... on Runs { results { runId status } } } }""")
    runs = data["data"]["runsOrError"]["results"]
    for r in runs:
        print(f"  {r['runId']} -> {r['status']}")
    sys.exit(0)

data = gql("""
query($runId: ID!) {
  runOrError(runId: $runId) {
    ... on Run {
      runId status startTime endTime
      stepStats { stepKey status startTime endTime }
    }
    ... on RunNotFoundError { message }
  }
}
""", {"runId": RUN_ID})

run = data["data"]["runOrError"]
print(f"Run {run.get('runId', '?')}: {run.get('status', '?')}")
if "stepStats" in run:
    for s in run["stepStats"]:
        dur = ""
        if s.get("startTime") and s.get("endTime"):
            dur = f" ({s['endTime'] - s['startTime']:.0f}s)"
        print(f"  {s['stepKey']}: {s['status']}{dur}")

# Fetch logs for failed steps
events_q = """
query($runId: ID!) {
  logsForRun(runId: $runId) {
    ... on EventConnection {
      events {
        __typename
        ... on ExecutionStepFailureEvent {
          stepKey
          error { message stack }
        }
      }
    }
  }
}
"""
data2 = gql(events_q, {"runId": RUN_ID})
events = data2.get("data", {}).get("logsForRun", {}).get("events", [])
for ev in events:
    if ev["__typename"] == "ExecutionStepFailureEvent":
        print(f"\n--- FAILURE: {ev['stepKey']} ---")
        print(ev["error"]["message"])
        stack = ev["error"].get("stack", [])
        if stack:
            print("".join(stack[-5:]))
