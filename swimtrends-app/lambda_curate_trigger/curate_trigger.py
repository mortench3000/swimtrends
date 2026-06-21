"""S3 ObjectCreated(raw/.../results.jsonl) -> RunTask the curate Fargate task
for that meet. Parses meet_id from the key 'raw/meet=<id>/results.jsonl'.

S3 event notifications URL-encode the object key, so the Hive-style partition
'meet=9780' is delivered as 'meet%3D9780'. The key must be unquoted before
matching, otherwise the literal '=' in KEY_RE never matches and the trigger
silently launches nothing.
"""
import os
import re
import urllib.parse

import boto3

KEY_RE = re.compile(r"raw/meet=([^/]+)/results\.jsonl$")


def lambda_handler(event, context):
    ecs = boto3.client("ecs")
    launched = []
    for record in event.get("Records", []):
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        m = KEY_RE.search(key)
        if not m:
            continue
        meet_id = m.group(1)
        resp = ecs.run_task(
            cluster=os.environ["ECS_CLUSTER"],
            taskDefinition=os.environ["TASK_DEFINITION"],
            launchType="FARGATE",
            count=1,
            networkConfiguration={"awsvpcConfiguration": {
                "subnets": os.environ["SUBNET_IDS"].split(","),
                "securityGroups": [os.environ["SECURITY_GROUP_ID"]],
                "assignPublicIp": "ENABLED",
            }},
            overrides={"containerOverrides": [{
                "name": os.environ["CONTAINER_NAME"],
                "environment": [{"name": "MEET_ID", "value": meet_id}],
            }]},
        )
        failures = resp.get("failures") or []
        if failures:
            # Do not swallow a launch failure: raising lets the Lambda retry and
            # surfaces the problem instead of a meet silently never being curated.
            raise RuntimeError(
                f"RunTask failed to launch curate for meet {meet_id}: {failures}")
        launched.append(meet_id)
    return {"launched": launched}
