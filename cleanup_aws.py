# cleanup_aws.py

import boto3
import os
import time


from key import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY
)

from config import (
    AWS_REGION,
    S3_INPUT_BUCKET, S3_OUTPUT_BUCKET, SQS_QUEUE_NAME,
    EC2_KEY_PAIR_NAME, KEY_FILE_PATH
)

# Initialize AWS clients
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
sqs = boto3.client(
    'sqs',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def terminate_all_instances():
    """Terminates all running EC2 instances launched by this project."""
    print("\n--- Terminating EC2 Instances ---")
    try:
        response = ec2.describe_instances(
            Filters=[
                {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']},
                {
                    'Name': 'tag:Name',
                    'Values': [
                        'web-instance-*', # Covers web-instance-1
                        'app-instance-*'  # Covers app-instance-X
                    ]
                }
            ]
        )
        instance_ids = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instance_ids.append(instance['InstanceId'])

        if instance_ids:
            print(f"Found {len(instance_ids)} instances to terminate: {instance_ids}")
            ec2.terminate_instances(InstanceIds=instance_ids)
            print("Initiated termination of instances. Waiting for them to stop...")
            waiter = ec2.get_waiter('instance_terminated')
            waiter.wait(InstanceIds=instance_ids)
            print("All instances terminated successfully.")
        else:
            print("No project-related instances found to terminate.")
        return True
    except Exception as e:
        print(f"Error terminating instances: {e}")
        return False

def delete_s3_buckets():
    """Deletes S3 buckets and their contents."""
    print("\n--- Deleting S3 Buckets ---")
    buckets = [S3_INPUT_BUCKET, S3_OUTPUT_BUCKET]
    for bucket_name in buckets:
        try:
            # First, delete all objects in the bucket
            paginator = s3.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name)
            for page in pages:
                if 'Contents' in page:
                    objects_to_delete = [{'Key': obj['Key']} for obj in page['Contents']]
                    s3.delete_objects(Bucket=bucket_name, Delete={'Objects': objects_to_delete})
                    print(f"Deleted objects from bucket: {bucket_name}")
            
            # Then, delete the bucket itself
            s3.delete_bucket(Bucket=bucket_name)
            print(f"Bucket '{bucket_name}' deleted successfully.")
        except s3.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchBucket':
                print(f"Bucket '{bucket_name}' does not exist.")
            else:
                print(f"Error deleting bucket '{bucket_name}': {e}")
                return False
        except Exception as e:
            print(f"An unexpected error occurred while deleting bucket '{bucket_name}': {e}")
            return False
    return True

def delete_sqs_queue():
    """Deletes the SQS queue."""
    print("\n--- Deleting SQS Queue ---")
    try:
        response = sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)
        queue_url = response['QueueUrl']
        sqs.delete_queue(QueueUrl=queue_url)
        print(f"SQS queue '{SQS_QUEUE_NAME}' deleted successfully.")
        return True
    except sqs.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'QueueDoesNotExist':
            print(f"SQS queue '{SQS_QUEUE_NAME}' does not exist.")
        else:
            print(f"Error deleting SQS queue: {e}")
            return False
    except Exception as e:
        print(f"An unexpected error occurred while deleting SQS queue: {e}")
        return False

def delete_ec2_key_pair():
    """Deletes the EC2 key pair and the local .pem file."""
    print("\n--- Deleting EC2 Key Pair ---")
    try:
        ec2.delete_key_pair(KeyName=EC2_KEY_PAIR_NAME)
        print(f"EC2 key pair '{EC2_KEY_PAIR_NAME}' deleted from AWS.")
    except ec2.exceptions.ClientError as e:
        if e.response['Error']['Code'] == 'InvalidKeyPair.NotFound':
            print(f"EC2 key pair '{EC2_KEY_PAIR_NAME}' not found on AWS.")
        else:
            print(f"Error deleting EC2 key pair from AWS: {e}")
            return False
    except Exception as e:
        print(f"An unexpected error occurred while deleting EC2 key pair from AWS: {e}")
        return False

    if os.path.exists(KEY_FILE_PATH):
        try:
            os.chmod(KEY_FILE_PATH, 0o666) # Change permissions to allow deletion
            os.remove(KEY_FILE_PATH)
            print(f"Local key file '{KEY_FILE_PATH}' deleted.")
        except PermissionError as e:
            print(f"Warning: Cannot delete local key file due to permissions: {e}")
        except Exception as e:
            print(f"Error deleting local key file: {e}")
    else:
        print(f"Local key file '{KEY_FILE_PATH}' not found.")
    return True

def delete_security_groups():
    """Deletes security groups."""
    print("\n--- Deleting Security Groups ---")
    security_group_names = [f"{EC2_KEY_PAIR_NAME}-web-sg", f"{EC2_KEY_PAIR_NAME}-app-sg"]
    for sg_name in security_group_names:
        try:
            response = ec2.describe_security_groups(GroupNames=[sg_name])
            sg_id = response['SecurityGroups'][0]['GroupId']
            ec2.delete_security_group(GroupId=sg_id)
            print(f"Security Group '{sg_name}' (ID: {sg_id}) deleted successfully.")
        except ec2.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
                print(f"Security Group '{sg_name}' does not exist.")
            elif e.response['Error']['Code'] == 'DependencyViolation':
                print(f"Security Group '{sg_name}' cannot be deleted due to dependencies. This usually means instances are still associated. Please ensure all instances are terminated.")
            else:
                print(f"Error deleting Security Group '{sg_name}': {e}")
                return False
        except Exception as e:
            print(f"An unexpected error occurred while deleting Security Group '{sg_name}': {e}")
            return False
    return True

if __name__ == "__main__":
    print("Starting AWS resource cleanup...")
    
    # Order of deletion is important due to dependencies
    # 1. Terminate all instances
    # 2. Delete security groups (after instances are gone)
    # 3. Delete SQS queue
    # 4. Delete S3 buckets (after queue is empty)
    # 5. Delete key pair

    if not terminate_all_instances():
        print("Cleanup failed at instance termination. Please manually verify and terminate instances before retrying.")
        exit(1)

    # Give AWS some time to fully terminate instances before deleting SGs
    time.sleep(10)

    if not delete_security_groups():
        print("Cleanup failed at security group deletion. Please manually verify.")
        exit(1)

    if not delete_sqs_queue():
        print("Cleanup failed at SQS queue deletion. Please manually verify.")
        exit(1)

    if not delete_s3_buckets():
        print("Cleanup failed at S3 bucket deletion. Please manually verify contents and then bucket.")
        exit(1)

    if not delete_ec2_key_pair():
        print("Cleanup failed at EC2 key pair deletion. Please manually verify.")
        exit(1)

    print("\n--- AWS Cleanup Complete ---")
    print("All specified AWS resources have been deleted.")

