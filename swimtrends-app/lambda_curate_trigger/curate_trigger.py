"""S3 ObjectCreated(raw/.../results.jsonl) -> RunTask the curate Fargate task
for that meet. Parses meet_id from the key 'raw/meet=<id>/results.jsonl'."""
import os
import re

import boto3

KEY_RE = re.compile(r"raw/meet=([^/]+)/results\.jsonl$")


def lambda_handler(event, context):
    ecs = boto3.client("ecs")
    launched = []
    for record in event.get("Records", []):
        key = record["s3"]["object"]["key"]
        m = KEY_RE.search(key)
        if not m:
            continue
        meet_id = m.group(1)
        ecs.run_task(
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
        launched.append(meet_id)
    return {"launched": launched}
