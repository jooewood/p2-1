# setup_aws.py

import boto3
import os
import time
from config import (
    AWS_REGION,
    S3_INPUT_BUCKET, S3_OUTPUT_BUCKET, SQS_QUEUE_NAME,
    EC2_KEY_PAIR_NAME, AMI_ID, WEB_TIER_INSTANCE_TYPE,
    KEY_FILE_PATH, REMOTE_APP_DIR, GIT_REPO_URL
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

def create_s3_buckets():
    """Creates input and output S3 buckets."""
    print("\n--- Creating S3 Buckets ---")
    buckets = [S3_INPUT_BUCKET, S3_OUTPUT_BUCKET]
    for bucket_name in buckets:
        try:
            # Check if bucket already exists
            s3.head_bucket(Bucket=bucket_name)
            print(f"Bucket '{bucket_name}' already exists.")
        except s3.exceptions.ClientError as e:
            error_code = int(e.response['Error']['Code'])
            if error_code == 404:
                # Bucket does not exist, create it
                print(f"Creating S3 bucket: {bucket_name} in region {AWS_REGION}...")
                s3.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={'LocationConstraint': AWS_REGION}
                )
                print(f"Bucket '{bucket_name}' created successfully.")
            else:
                print(f"Error checking or creating bucket '{bucket_name}': {e}")
                return False
        except Exception as e:
            print(f"An unexpected error occurred with bucket '{bucket_name}': {e}")
            return False
    return True

def create_sqs_queue():
    """Creates an SQS queue."""
    print("\n--- Creating SQS Queue ---")
    try:
        response = sqs.create_queue(QueueName=SQS_QUEUE_NAME)
        queue_url = response['QueueUrl']
        print(f"SQS queue '{SQS_QUEUE_NAME}' created successfully. URL: {queue_url}")
        return queue_url
    except sqs.exceptions.ClientError as e:
        if "QueueAlreadyExists" in str(e):
            print(f"SQS queue '{SQS_QUEUE_NAME}' already exists. Retrieving URL...")
            response = sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)
            queue_url = response['QueueUrl']
            print(f"SQS queue URL: {queue_url}")
            return queue_url
        else:
            print(f"Failed to create SQS queue: {e}")
            return None
    except Exception as e:
        print(f"An unexpected error occurred with SQS queue: {e}")
        return None

def create_ec2_key_pair():
    """Creates an EC2 key pair and saves the .pem file."""
    try:
        print("\n--- Creating EC2 key pair ---")
        # Check and delete existing key pair locally and on AWS
        if os.path.exists(KEY_FILE_PATH):
            try:
                # Change file permissions before deletion
                os.chmod(KEY_FILE_PATH, 0o666)
                os.remove(KEY_FILE_PATH)
                print(f"Local key file '{KEY_FILE_PATH}' deleted.")
            except PermissionError as e:
                print(f"Warning: Cannot delete local key file due to permissions: {e}")
            except Exception as e:
                print(f"Warning: Error deleting local key file: {e}")

        print(f"Checking for existing EC2 key pair on AWS: {EC2_KEY_PAIR_NAME}")
        try:
            ec2.describe_key_pairs(KeyNames=[EC2_KEY_PAIR_NAME])
            print(f"Found existing key pair '{EC2_KEY_PAIR_NAME}' on AWS, deleting...")
            ec2.delete_key_pair(KeyName=EC2_KEY_PAIR_NAME)
            print(f"Existing key pair deleted from AWS.")
        except ec2.exceptions.ClientError as e:
            if e.response['Error']['Code'] != 'InvalidKeyPair.NotFound':
                print(f"Error checking AWS key pair: {e}")
                return False

        # Creating EC2 key pair
        print(f"Creating new EC2 key pair: {EC2_KEY_PAIR_NAME}...")
        try:
            key_pair = ec2.create_key_pair(KeyName=EC2_KEY_PAIR_NAME)
            # Save private key to file for future SSH connection
            with open(KEY_FILE_PATH, "w") as f:
                f.write(key_pair['KeyMaterial'])
            os.chmod(KEY_FILE_PATH, 0o400)  # Required permissions for SSH
            print(f"EC2 key pair '{EC2_KEY_PAIR_NAME}' created successfully and saved to '{KEY_FILE_PATH}'")
            return True
        except Exception as e:
            print(f"Failed to create EC2 key pair: {e}")
            return False
    except Exception as e:
        print(f"An unexpected error occurred during key pair creation: {e}")
        return False


def create_security_groups():
    """Creates security groups for web tier and app tier."""
    print("\n--- Creating Security Groups ---")
    try:
        # Create Web Tier Security Group
        web_sg_name = f"{EC2_KEY_PAIR_NAME}-web-sg"
        app_sg_name = f"{EC2_KEY_PAIR_NAME}-app-sg"

        # Check if web security group already exists
        web_sg_id = None
        try:
            response = ec2.describe_security_groups(GroupNames=[web_sg_name])
            web_sg_id = response['SecurityGroups'][0]['GroupId']
            print(f"Web Tier Security Group '{web_sg_name}' already exists with ID: {web_sg_id}")
        except ec2.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
                print(f"Creating Web Tier Security Group: {web_sg_name}...")
                response = ec2.create_security_group(
                    GroupName=web_sg_name,
                    Description='Security group for Web Tier instances'
                )
                web_sg_id = response['GroupId']
                print(f"Web Tier Security Group '{web_sg_name}' created with ID: {web_sg_id}")

                # Add rules for HTTP (80), FastAPI (8000), SSH (22) from anywhere
                ec2.authorize_security_group_ingress(
                    GroupId=web_sg_id,
                    IpPermissions=[
                        {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                        {'IpProtocol': 'tcp', 'FromPort': 8000, 'ToPort': 8000, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]},
                        {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                    ]
                )
                print("Inbound rules added to Web Tier Security Group.")
            else:
                raise

        # Create App Tier Security Group
        app_sg_id = None
        try:
            response = ec2.describe_security_groups(GroupNames=[app_sg_name])
            app_sg_id = response['SecurityGroups'][0]['GroupId']
            print(f"App Tier Security Group '{app_sg_name}' already exists with ID: {app_sg_id}")
        except ec2.exceptions.ClientError as e:
            if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
                print(f"Creating App Tier Security Group: {app_sg_name}...")
                response = ec2.create_security_group(
                    GroupName=app_sg_name,
                    Description='Security group for App Tier instances'
                )
                app_sg_id = response['GroupId']
                print(f"App Tier Security Group '{app_sg_name}' created with ID: {app_sg_id}")

                # Add rule for SSH (22) from anywhere for initial setup/debugging
                # App tier instances typically don't need public HTTP/HTTPS access.
                # They will communicate with SQS/S3 over internal AWS network.
                ec2.authorize_security_group_ingress(
                    GroupId=app_sg_id,
                    IpPermissions=[
                        {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}
                    ]
                )
                print("Inbound rules added to App Tier Security Group.")
            else:
                raise

        return web_sg_id, app_sg_id
    except Exception as e:
        print(f"Failed to create security groups: {e}")
        return None, None

def launch_web_tier_instance(web_sg_id):
    """Launches a single Web Tier EC2 instance."""
    print("\n--- Launching Web Tier Instance ---")

    # This user data script will install necessary packages and start the FastAPI app
    # It dynamically embeds the content of config.py and web_tier_app.py
    try:
        with open("config.py", "r") as f_config:
            config_content = f_config.read()
        user_data_script = f"""#!/bin/bash
sudo -i
cd /home/ubuntu
apt update -y
apt install python3 -y
apt install python3-pip -y
apt install python3-venv -y
apt install git -y

mkdir -p {REMOTE_APP_DIR}
cd {REMOTE_APP_DIR}

git clone {GIT_REPO_URL} .

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install fastapi uvicorn python-multipart boto3

cat << 'EOF_CONFIG' > config.py
{config_content}
EOF_CONFIG

nohup venv/bin/uvicorn web_tier_app:app --host 0.0.0.0 --port 8000 &> web_tier_app.log &
echo "Web tier app started."
echo "==== USER DATA SCRIPT FINISHED ===="
sleep 2
"""
# nohup venv/bin/uvicorn web_tier_app:app --host 0.0.0.0 --port 8000 &> web_tier_app.log &
# source venv/bin/activate
# uvicorn web_tier_app:app --host 0.0.0.0 --port 8000
# tail /var/log/cloud-init-output.log

    except FileNotFoundError as e:
        print(f"Error reading file for user_data_web.sh: {e}. Make sure config.py and web_tier_app.py exist locally.")
        return None
    except Exception as e:
        print(f"Error preparing user data script for web tier: {e}")
        return None

    try:
        # Check for existing web-tier instances to avoid launching duplicates
        existing_instances = ec2.describe_instances(
            Filters=[
                {'Name': 'instance-state-name', 'Values': ['pending', 'running']},
                {'Name': 'tag:Name', 'Values': ['web-instance-1']}
            ]
        )
        if existing_instances['Reservations']:
            print("Web tier instance 'web-instance-1' already exists and is running/pending.")
            web_instance_id = existing_instances['Reservations'][0]['Instances'][0]['InstanceId']
            
            # Get public IP of existing instance
            instance_info = ec2.describe_instances(InstanceIds=[web_instance_id])
            public_ip = instance_info['Reservations'][0]['Instances'][0]['PublicIpAddress']
            print(f"Existing Web Tier instance '{web_instance_id}'. Public IP: {public_ip}")
            return web_instance_id

        # Launch new instance
        response = ec2.run_instances(
            ImageId=AMI_ID,
            MinCount=1,
            MaxCount=1,
            InstanceType=WEB_TIER_INSTANCE_TYPE,
            KeyName=EC2_KEY_PAIR_NAME,
            SecurityGroupIds=[web_sg_id],
            UserData=user_data_script,
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [{'Key': 'Name', 'Value': 'web-instance-1'}]
                }
            ]
        )
        instance_id = response['Instances'][0]['InstanceId']
        print(f"Launched Web Tier instance with ID: {instance_id}")

        # Wait for the instance to be running
        print("Waiting for Web Tier instance to be running...")
        waiter = ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])

        # Get public IP
        instance_info = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instance_info['Reservations'][0]['Instances'][0]['PublicIpAddress']
        print(f"Web Tier instance '{instance_id}' is running. Public IP: {public_ip}")
        # Optionally, update config.py with this IP if you need to read it later from config.
        # This is for display purposes here.
        return instance_id
    except Exception as e:
        print(f"Failed to launch Web Tier instance: {e}")
        return None

if __name__ == "__main__":
    # Create dummy files if they don't exist, so 'open' calls in launch_web_tier_instance don't fail initially
    # These will be overwritten or contain actual content later.
    # Ensure config.py exists as it's modified by the user
    if not os.path.exists("config.py"):
        print("Error: config.py not found. Please create it with your AWS details.")
        exit(1)


    if not create_s3_buckets():
        print("Failed to set up S3 buckets. Exiting.")
        exit(1)

    if not create_sqs_queue():
        print("Failed to set up SQS queue. Exiting.")
        exit(1)

    if not create_ec2_key_pair():
        print("Failed to set up EC2 key pair. Exiting.")
        exit(1)

    web_sg_id, app_sg_id = create_security_groups()
    if not web_sg_id or not app_sg_id:
        print("Failed to create security groups. Exiting.")
        exit(1)

    web_instance_id = launch_web_tier_instance(web_sg_id)
    if not web_instance_id:
        print("Failed to launch Web Tier instance. Exiting.")
        exit(1)

    print("\n--- AWS Setup Complete ---")
    print(f"Web Tier instance (ID: {web_instance_id}) is running.")
    print("Please check the console for its Public IP to configure your workload generator.")
    print("Next: Run your workload generator against http://<WEB_TIER_PUBLIC_IP>:8000/upload")

