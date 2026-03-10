"""Trigger a Dagster job via GraphQL API. Disposable helper."""
import json
import sys
import requests

DAGSTER_URL = "http://127.0.0.1:3070/graphql"
JOB = sys.argv[1] if len(sys.argv) > 1 else "full_pipeline_job"


def gql(query, variables=None):
    r = requests.post(DAGSTER_URL, json={"query": query, **({"variables": variables} if variables else {})}, timeout=30)
    return r.json()


if "--list" in sys.argv:
    data = gql("""
    {
      repositoriesOrError {
        ... on RepositoryConnection {
          nodes {
            name
            location { name }
            jobs { name }
          }
        }
      }
    }
    """)
    for repo in data["data"]["repositoriesOrError"]["nodes"]:
        loc = repo["location"]["name"]
        name = repo["name"]
        print(f"Location: {loc}")
        print(f"Repository: {name}")
        for j in repo["jobs"]:
            print(f"  Job: {j['name']}")
    sys.exit(0)


# First discover the location/repo names
data = gql("""
{
  repositoriesOrError {
    ... on RepositoryConnection {
      nodes { name location { name } }
    }
  }
}
""")
repos = data["data"]["repositoriesOrError"]["nodes"]
if not repos:
    print("No repositories found", file=sys.stderr)
    sys.exit(1)

repo = repos[0]
loc_name = repo["location"]["name"]
repo_name = repo["name"]
print(f"Using location={loc_name} repo={repo_name}")

# Launch
result = gql("""
mutation($loc: String!, $repo: String!, $job: String!) {
  launchPipelineExecution(
    executionParams: {
      selector: {
        repositoryLocationName: $loc
        repositoryName: $repo
        jobName: $job
      }
    }
  ) {
    __typename
    ... on LaunchRunSuccess { run { runId status } }
    ... on PythonError { message }
    ... on InvalidSubsetError { message }
    ... on RunConflict { message }
  }
}
""", {"loc": loc_name, "repo": repo_name, "job": JOB})

launch = result["data"]["launchPipelineExecution"]
if launch["__typename"] == "LaunchRunSuccess":
    run_id = launch["run"]["runId"]
    print(f"\nJob '{JOB}' launched successfully!")
    print(f"Run ID: {run_id}")
    print(f"Monitor: http://127.0.0.1:3070/runs/{run_id}")
else:
    print(f"\nFailed: {json.dumps(launch, indent=2)}", file=sys.stderr)
    sys.exit(1)
