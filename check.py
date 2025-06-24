import boto3


from key import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY
)

from config import (
    AWS_REGION,
    S3_INPUT_BUCKET, S3_OUTPUT_BUCKET
)

def show_status():
    """Display current EC2 app instances and S3 input/output bucket contents."""
    ec2 = boto3.client(
        'ec2',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
    s3 = boto3.client(
        's3',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    # Show running app instances
    print("=== EC2 App Instances (pending/running) ===")
    try:
        resp = ec2.describe_instances(
            Filters=[
                {'Name': 'instance-state-name', 'Values': ['pending', 'running']},
                {'Name': 'tag:Name', 'Values': ['app-instance-*']}
            ]
        )
        ids = []
        for reservation in resp['Reservations']:
            for instance in reservation['Instances']:
                ids.append(instance['InstanceId'])
        print(f"App instance count: {len(ids)}")
        print("Instance IDs:", ids)
    except Exception as e:
        print("Error retrieving EC2 instances:", e)

    # Show S3 input bucket contents
    print("=== S3 Input Bucket ===")
    try:
        objs = s3.list_objects_v2(Bucket=S3_INPUT_BUCKET)
        keys = [obj['Key'] for obj in objs.get('Contents', [])]
        print(f"Total objects: {len(keys)}")
        print("Keys:", keys)
    except Exception as e:
        print("Error retrieving S3 input bucket:", e)

    # Show S3 output bucket contents
    print("=== S3 Output Bucket ===")
    try:
        objs = s3.list_objects_v2(Bucket=S3_OUTPUT_BUCKET)
        keys = [obj['Key'] for obj in objs.get('Contents', [])]
        l = len(keys)
        print(f"Total objects: {l}")
        for i in range(l):
            key = f"test_{i}"
            try:
                obj = s3.get_object(Bucket=S3_OUTPUT_BUCKET, Key=key)
                value = obj['Body'].read(128)
                try:
                    value = value.decode('utf-8')
                except Exception:
                    pass
                print(value)
            except Exception as e:
                print(f"Key: {key} | Error reading value: {e}")
        print("Keys:", keys)
    except Exception as e:
        print("Error retrieving S3 output bucket:", e)

if __name__ == "__main__":
    show_status()
