# web_tier_app.py

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import PlainTextResponse
import boto3
import uuid
import os
import asyncio
import logging
import threading
import time

from key import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY
)

from config import (
    AWS_REGION,
    S3_INPUT_BUCKET, S3_OUTPUT_BUCKET, SQS_QUEUE_NAME,
    EC2_KEY_PAIR_NAME, AMI_ID, APP_TIER_INSTANCE_TYPE,
    MAX_APP_INSTANCES, MIN_APP_INSTANCES,
    SCALING_CHECK_INTERVAL,
    REMOTE_APP_DIR, WEB_TIER_POLLING_INTERVAL, GIT_REPO_URL
)

app = FastAPI()

# Set up logging to console (no file logging as per requirement)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize AWS clients
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
ec2 = boto3.client(
    'ec2',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

# Global variables for auto-scaling
app_tier_sg_id = None # Will be retrieved on startup
app_instance_count_lock = threading.Lock() # Lock for managing instance count
running_app_instances = set() # Store instance IDs of running app tier instances

def get_queue_url():
    """Retrieves the SQS queue URL."""
    try:
        response = sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)
        return response['QueueUrl']
    except Exception as e:
        logging.error(f"Failed to get SQS queue URL: {e}")
        return None

def get_app_tier_security_group_id():
    """Retrieves the Security Group ID for App Tier."""
    global app_tier_sg_id
    if app_tier_sg_id:
        return app_tier_sg_id

    try:
        response = ec2.describe_security_groups(GroupNames=[f"{EC2_KEY_PAIR_NAME}-app-sg"])
        app_tier_sg_id = response['SecurityGroups'][0]['GroupId']
        logging.info(f"Retrieved App Tier Security Group ID: {app_tier_sg_id}")
        return app_tier_sg_id
    except Exception as e:
        logging.error(f"Failed to retrieve App Tier Security Group ID: {e}")
        return None

def get_approximate_number_of_messages():
    """Gets the approximate number of messages in the SQS queue."""
    queue_url = get_queue_url()
    if not queue_url:
        return 0
    try:
        response = sqs.get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
        )
        visible = int(response['Attributes'].get('ApproximateNumberOfMessages', 0))
        not_visible = int(response['Attributes'].get('ApproximateNumberOfMessagesNotVisible', 0))
        total_messages = visible + not_visible
        return total_messages
    except Exception as e:
        logging.error(f"Failed to get SQS queue attributes: {e}")
        return 0

def get_running_app_instances():
    """Gets a list of running App Tier instance IDs."""
    try:
        response = ec2.describe_instances(
            Filters=[
                {'Name': 'instance-state-name', 'Values': ['pending', 'running']},
                {'Name': 'tag:Name', 'Values': ['app-instance-*']} # Match instances named app-instance-X
            ]
        )
        instances = []
        for reservation in response['Reservations']:
            for instance in reservation['Instances']:
                instances.append(instance['InstanceId'])
        return instances
    except Exception as e:
        logging.error(f"Failed to describe App Tier instances: {e}")
        return []

def launch_app_instance(instance_name_tag):
    """Launches a new App Tier EC2 instance."""
    app_sg_id = get_app_tier_security_group_id()
    if not app_sg_id:
        logging.error("Cannot launch App Tier instance: Security Group ID not found.")
        return None

    # This user data script will install necessary packages, clone the classifier repo,
    # and start the app_tier_worker.
    try:
        with open("config.py", "r") as f_config:
            config_content = f_config.read()

        user_data_app_script = f"""#!/bin/bash
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
pip install boto3
pip install --break-system-packages torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Embed config.py content (overwrite repo's config.py)
cat << 'EOF_CONFIG' > config.py
{config_content}
EOF_CONFIG

# Start the App Tier Worker in the background

nohup python3 app_tier_worker.py &> app_tier_worker.log &
echo "App tier worker started."
"""
# nohup python3 app_tier_worker.py &> app_tier_worker.log &
# python3 app_tier_worker.py

    except FileNotFoundError as e:
        logging.error(f"Error reading file for user_data_app_script: {e}. Make sure config.py and app_tier_worker.py exist.")
        return None
    except Exception as e:
        logging.error(f"Error preparing user data for app tier: {e}")
        return None

    try:
        response = ec2.run_instances(
            ImageId=AMI_ID,
            MinCount=1,
            MaxCount=1,
            InstanceType=APP_TIER_INSTANCE_TYPE,
            KeyName=EC2_KEY_PAIR_NAME,
            SecurityGroupIds=[app_sg_id],
            UserData=user_data_app_script,
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [{'Key': 'Name', 'Value': instance_name_tag}]
                }
            ]
        )
        instance_id = response['Instances'][0]['InstanceId']
        logging.info(f"Launched App Tier instance: {instance_id} with name {instance_name_tag}")
        with app_instance_count_lock:
            running_app_instances.add(instance_id)
        return instance_id
    except Exception as e:
        logging.error(f"Failed to launch App Tier instance {instance_name_tag}: {e}")
        return None

def terminate_app_instance(instance_id):
    """Terminates an App Tier EC2 instance."""
    try:
        ec2.terminate_instances(InstanceIds=[instance_id])
        logging.info(f"Terminating App Tier instance: {instance_id}")
        with app_instance_count_lock:
            if instance_id in running_app_instances:
                running_app_instances.remove(instance_id)
    except Exception as e:
        logging.error(f"Failed to terminate App Tier instance {instance_id}: {e}")

async def auto_scaling_controller():
    """
    Monitors SQS queue depth and adjusts App Tier EC2 instances.
    Scaling policy:
    - If queue depth > 2, scale out to 19 app instances (max).
    - If queue depth <= 2, gradually scale in to 0.
    - Never exceed 19 running app instances.
    """
    logging.info("Auto-scaling controller started.")
    MAX_INSTANCES = MAX_APP_INSTANCES
    MIN_INSTANCES = MIN_APP_INSTANCES
    while True:
        try:
            queue_messages = get_approximate_number_of_messages()
            current_running_instances = get_running_app_instances()
            # Update the set of running instances to remove terminated ones
            with app_instance_count_lock:
                running_app_instances.intersection_update(current_running_instances)
            current_instance_count = len(running_app_instances)

            logging.info(f"SQS messages: {queue_messages}, Current App instances: {current_instance_count}")

            # Decide target number of app instances
            if queue_messages > 2:
                target_instances = MAX_INSTANCES
            else:
                target_instances = MIN_INSTANCES

            # Scale out: launch new instances up to target (max 19)
            if current_instance_count < target_instances:
                instances_to_launch = min(target_instances - current_instance_count, MAX_INSTANCES - current_instance_count)
                used_numbers = set()
                try:
                    response = ec2.describe_instances(
                        Filters=[
                            {'Name': 'instance-state-name', 'Values': ['pending', 'running']},
                            {'Name': 'tag:Name', 'Values': [f'app-instance-*']}
                        ]
                    )
                    for reservation in response['Reservations']:
                        for instance in reservation['Instances']:
                            for tag in instance.get('Tags', []):
                                if tag['Key'] == 'Name' and tag['Value'].startswith('app-instance-'):
                                    try:
                                        num = int(tag['Value'].split('-')[-1])
                                        used_numbers.add(num)
                                    except Exception:
                                        continue
                except Exception as e:
                    logging.error(f"Error retrieving existing app-instance names: {e}")

                for _ in range(instances_to_launch):
                    # Find the smallest unused number in 1..MAX_INSTANCES
                    for num in range(1, MAX_INSTANCES + 1):
                        if num not in used_numbers:
                            instance_name = f"app-instance-{num}"
                            used_numbers.add(num)
                            logging.info(f"Scaling out: Launching new App Tier instance ({instance_name})...")
                            launch_app_instance(instance_name)
                            await asyncio.sleep(2)
                            break
                    else:
                        logging.info("Reached MAX_INSTANCES limit. Not launching more.")
                        break

            # Scale in: terminate instances down to target (possibly 0)
            elif current_instance_count > target_instances:
                instances_to_terminate = current_instance_count - target_instances
                logging.info(f"Scaling in: Terminating {instances_to_terminate} App Tier instance(s)...")
                for instance_id in list(running_app_instances):
                    if len(running_app_instances) > target_instances:
                        terminate_app_instance(instance_id)
                        await asyncio.sleep(2)
                    else:
                        break

        except Exception as e:
            logging.error(f"Error in auto-scaling controller: {e}")
        finally:
            await asyncio.sleep(SCALING_CHECK_INTERVAL)

@app.on_event("startup")
async def startup_event():
    """On startup, ensure SQS queue URL is known and start the auto-scaling controller."""
    logging.info("FastAPI app starting up.")
    get_queue_url() # Attempt to get queue URL on startup
    get_app_tier_security_group_id() # Attempt to get App Tier SG ID
    asyncio.create_task(auto_scaling_controller())
    logging.info("Auto-scaling controller scheduled.")

@app.get("/")
async def health_check():
    """
    Health check endpoint to verify the web tier is running.
    """
    return PlainTextResponse("Web Tier is running.")

@app.post("/upload", response_class=PlainTextResponse)
async def upload_image(file: UploadFile = File(...)):
    """
    Handles image uploads, stores them in S3, sends a message to SQS,
    then polls S3 for the result and returns it.
    """
    if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        raise HTTPException(status_code=400, detail="Invalid file type. Only PNG, JPG, JPEG are allowed.")

    # Original filename provided by the user (e.g., test_0.JPEG)
    original_filename = file.filename
    # Generate a unique S3 input key using UUID to prevent collisions
    file_extension = os.path.splitext(original_filename)[1]
    # Use original filename as part of the key to track it, combined with UUID for uniqueness
    unique_input_s3_key = f"{uuid.uuid4()}-{original_filename}"

    # The S3 output key should be the original filename without extension (e.g., test_0)
    # as per the problem description: "图像名称就是键值（如 test_0）"
    output_s3_key_base = os.path.splitext(original_filename)[0]

    try:
        # Upload image to S3 input bucket
        file_content = await file.read()
        s3.put_object(Bucket=S3_INPUT_BUCKET, Key=unique_input_s3_key, Body=file_content, ContentType=file.content_type)
        logging.info(f"Uploaded {original_filename} to S3 as {unique_input_s3_key}")

        # Send message to SQS queue with the unique S3 input key AND the expected S3 output key
        # App tier will use unique_input_s3_key to download, and output_s3_key_base to upload result
        queue_url = get_queue_url()
        if not queue_url:
            raise HTTPException(status_code=500, detail="SQS queue URL not found.")

        # Message body contains both the input S3 key and the expected output S3 key base
        # This allows the app tier to know where to save the result.
        message_body = f"{unique_input_s3_key},{output_s3_key_base}"
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=message_body
        )
        logging.info(f"Sent message '{message_body}' to SQS queue for {original_filename}.")

        # --- Polling S3 for result ---
        # Remove timeout: loop until result is found
        result_found = False
        prediction_result = None

        while True:
            try:
                response = s3.get_object(Bucket=S3_OUTPUT_BUCKET, Key=output_s3_key_base)
                result_content = response['Body'].read().decode('utf-8')
                logging.info(f"Retrieved result for {original_filename} (S3 key: {output_s3_key_base}): {result_content}")
                
                # The output format expected by workload generator is just the prediction
                # The S3 content should be "(image_name, prediction)"
                # Example: "(test_0, bathtub)" -> we need to extract "bathtub"
                if result_content.startswith('(') and result_content.endswith(')'):
                    # Remove parentheses and split by comma
                    parts = result_content[1:-1].split(', ', 1) # Split only on the first comma and space
                    if len(parts) == 2:
                        # The first part is the image name, second is the prediction
                        prediction_result = parts[1].strip()
                        logging.info(f"Parsed prediction for {original_filename}: {prediction_result}")
                        result_found = True
                        break
                    else:
                        logging.warning(f"Unexpected format for S3 output content: {result_content}")
                        # If parsing fails, maybe just return raw content or handle as an error
                        prediction_result = result_content # Fallback
                        result_found = True
                        break # Break anyway, don't want to loop forever on bad data
                else:
                    prediction_result = result_content # If not in expected format, just return as is
                    result_found = True
                    break

            except s3.exceptions.ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    # Result not yet available, continue polling
                    logging.debug(f"Result for '{output_s3_key_base}' not yet available. Polling...")
                    await asyncio.sleep(WEB_TIER_POLLING_INTERVAL)
                else:
                    logging.error(f"Error retrieving result for {output_s3_key_base} from S3: {e}")
                    raise HTTPException(status_code=500, detail=f"Error retrieving result: {e}")
            except Exception as e:
                logging.error(f"An unexpected error occurred during polling for {output_s3_key_base}: {e}")
                raise HTTPException(status_code=500, detail=f"An unexpected error occurred during result retrieval: {e}")

        # Return only the prediction result as plain text
        return PlainTextResponse(prediction_result)

    except Exception as e:
        logging.error(f"Error processing upload for {original_filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process image upload: {e}")

