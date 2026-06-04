"""DynamoDB access for per-(meet,race) authoritative class overrides.

Partition key meet_id (S), sort key race_id (N). Sparse: only the handful of
races the heuristic gets wrong."""
import boto3
from boto3.dynamodb.conditions import Key


class ClassOverrides:
    def __init__(self, table_name, region=None):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def set_override(self, meet_id, race_id, klass, reason=""):
        if klass not in ("open", "para"):
            raise ValueError(f"class must be 'open' or 'para', got {klass!r}")
        self._table.put_item(Item={
            "meet_id": str(meet_id), "race_id": int(race_id),
            "class": klass, "reason": reason,
        })

    def get_for_meet(self, meet_id):
        """Return {race_id(int): class} for one meet."""
        resp = self._table.query(
            KeyConditionExpression=Key("meet_id").eq(str(meet_id)))
        return {int(i["race_id"]): i["class"] for i in resp.get("Items", [])}
