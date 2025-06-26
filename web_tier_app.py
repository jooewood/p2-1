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
    S3_INPUT_BUCKET, S3_OUTPUT_BUCKET, SQS_QUEUE_NAME, RESPONSE_SQS_QUEUE_NAME,
    EC2_KEY_PAIR_NAME, AMI_ID, APP_TIER_INSTANCE_TYPE,
    MAX_APP_INSTANCES, MIN_APP_INSTANCES,
    SCALING_CHECK_INTERVAL, WEB_TIER_POLLING_INTERVAL,
    REMOTE_APP_DIR, GIT_REPO_URL, APP_SG_ID
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

# Dictionary to hold futures for pending requests
# Key: unique_request_id (derived from output_s3_key_base + UUID)
# Value: asyncio.Future object
pending_requests = {}

# SQS Queue URLs
request_queue_url = None
response_queue_url = None


def get_queue_url(queue_name):
    """Retrieves the SQS queue URL for a given queue name."""
    try:
        response = sqs.get_queue_url(QueueName=queue_name)
        return response['QueueUrl']
    except Exception as e:
        logging.error(f"Failed to get SQS queue URL for {queue_name}: {e}")
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
    queue_url = get_queue_url(SQS_QUEUE_NAME)
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

def get_approximate_number_of_response_messages():
    """Gets the approximate number of messages in the response SQS queue."""
    queue_url = get_queue_url(RESPONSE_SQS_QUEUE_NAME)
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
        logging.error(f"Failed to get response SQS queue attributes: {e}")
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

    # This user data script will install necessary packages, clone the classifier repo,
    # and start the app_tier_worker.
    try:
        with open("key.py", "r") as f_key:
            key_content = f_key.read()

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

cat << 'EOF_CONFIG' > key.py
{key_content}
EOF_CONFIG

# Start the App Tier Worker in the background
nohup python3 app_tier_worker.py &> app_tier_worker.log &
echo "App tier worker started."
"""

    except FileNotFoundError as e:
        logging.error(f"Error reading file for user_data_app_script: {e}. Make sure key.py exists.")
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
            SecurityGroupIds=[APP_SG_ID],
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
    - If queue depth > 10, scale out to 19 app instances (max).
    - If queue depth <= 10, gradually scale in to 0.
    - Never exceed 19 running app instances.
    """
    logging.info("Auto-scaling controller started.")
    MAX_INSTANCES = MAX_APP_INSTANCES
    MIN_INSTANCES = MIN_APP_INSTANCES
    while True:
        try:
            queue_messages = get_approximate_number_of_messages()
            response_queue_messages = get_approximate_number_of_response_messages()
            current_running_instances = get_running_app_instances()
            # Update the set of running instances to remove terminated ones
            with app_instance_count_lock:
                running_app_instances.intersection_update(current_running_instances)
            current_instance_count = len(running_app_instances)

            logging.info(f"Request SQS: {queue_messages}, Response SQS: {response_queue_messages}, Current App instances: {current_instance_count}")

            # Decide target number of app instances
            if queue_messages > 10:
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

async def response_queue_poller():
    """
    Continuously polls the response SQS queue for results and
    sets the result on the corresponding Future object in pending_requests.
    """
    global response_queue_url
    logging.info("Response queue poller started.")
    while True:
        try:
            if not response_queue_url:
                response_queue_url = get_queue_url(RESPONSE_SQS_QUEUE_NAME)
                if not response_queue_url:
                    logging.error("Response SQS queue URL not found. Retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue

            response = sqs.receive_message(
                QueueUrl=response_queue_url,
                MaxNumberOfMessages=10, # Fetch up to 10 messages at once
                WaitTimeSeconds=WEB_TIER_POLLING_INTERVAL # Use configured polling interval for long polling
            )

            messages = response.get('Messages', [])
            if not messages:
                logging.debug("No messages in response queue. Waiting...")
                await asyncio.sleep(1) # Short sleep if no messages, to avoid busy-waiting
                continue

            for message in messages:
                receipt_handle = message['ReceiptHandle']
                # Expected format: "original_filename,prediction_result,unique_request_id"
                message_body = message['Body']
                logging.info(f"Received response message: {message_body}")

                try:
                    parts = message_body.split(',', 2) # Split into at most 3 parts
                    if len(parts) == 3:
                        original_filename = parts[0]
                        prediction_result = parts[1]
                        unique_request_id = parts[2]

                        if unique_request_id in pending_requests:
                            future = pending_requests.pop(unique_request_id)
                            if not future.done():
                                future.set_result(prediction_result)
                                logging.info(f"Set result for request {unique_request_id} (file: {original_filename}): {prediction_result}")
                            else:
                                logging.warning(f"Future for {unique_request_id} already done. Message might be duplicate.")
                        else:
                            logging.warning(f"Received result for unknown request ID: {unique_request_id} (file: {original_filename}).")
                        
                        # Delete message from queue after processing
                        sqs.delete_message(QueueUrl=response_queue_url, ReceiptHandle=receipt_handle)
                        logging.info(f"Deleted response message with ReceiptHandle: {receipt_handle}")
                    else:
                        logging.error(f"Malformed response SQS message body: {message_body}. Skipping and deleting.")
                        # Delete malformed message to prevent re-processing
                        sqs.delete_message(QueueUrl=response_queue_url, ReceiptHandle=receipt_handle)

                except Exception as parse_e:
                    logging.error(f"Error processing response SQS message '{message_body}': {parse_e}. Deleting message.")
                    sqs.delete_message(QueueUrl=response_queue_url, ReceiptHandle=receipt_handle)
        
        except Exception as e:
            logging.error(f"Error in response queue poller: {e}")
        finally:
            # Short sleep to prevent busy-waiting even if polling is quick
            await asyncio.sleep(1) 


@app.on_event("startup")
async def startup_event():
    """On startup, ensure SQS queue URLs are known and start background tasks."""
    global request_queue_url, response_queue_url
    logging.info("FastAPI app starting up.")
    
    # Get request and response queue URLs
    request_queue_url = get_queue_url(SQS_QUEUE_NAME)
    response_queue_url = get_queue_url(RESPONSE_SQS_QUEUE_NAME)

    if not request_queue_url:
        logging.error("Failed to get request SQS queue URL on startup.")
    if not response_queue_url:
        logging.error("Failed to get response SQS queue URL on startup.")

    get_app_tier_security_group_id() # Attempt to get App Tier SG ID

    # Start background tasks
    asyncio.create_task(auto_scaling_controller())
    asyncio.create_task(response_queue_poller())
    logging.info("Auto-scaling controller and response queue poller scheduled.")

@app.get("/")
async def health_check():
    """
    Health check endpoint to verify the web tier is running.
    """
    return PlainTextResponse("Web Tier is running.")

@app.post("/upload", response_class=PlainTextResponse)
async def upload_image(myfile: UploadFile = File(...)):
    """
    Handles image uploads, stores them in S3, sends a message to the request SQS queue,
    and awaits the result from the response SQS queue.
    """
    content_type = "image/jpeg"

    original_filename = myfile.filename
    # Generate a unique ID for this specific request, combining with original filename for traceability
    # This ID will be used to match the response later.
    unique_request_id = f"{os.path.splitext(original_filename)[0]}-{uuid.uuid4()}" 
    
    # Generate a unique S3 input key using UUID to prevent collisions
    # This is for the input bucket, as App Tier will download using this key
    unique_input_s3_key = f"{uuid.uuid4()}-{original_filename}"


    try:
        # Upload image to S3 input bucket
        file_content = await myfile.read()
        s3.put_object(Bucket=S3_INPUT_BUCKET, Key=unique_input_s3_key, Body=file_content, ContentType=content_type)
        logging.info(f"Uploaded {original_filename} to S3 as {unique_input_s3_key}")

        # Ensure queue URLs are available
        if not request_queue_url:
            raise HTTPException(status_code=500, detail="Request SQS queue URL not found.")

        # Message body contains unique_input_s3_key, original_filename, and unique_request_id
        # The App Tier will use original_filename and unique_request_id when sending to response SQS.
        message_body = f"{unique_input_s3_key},{original_filename},{unique_request_id}"
        sqs.send_message(
            QueueUrl=request_queue_url,
            MessageBody=message_body
        )
        logging.info(f"Sent message '{message_body}' to request SQS queue for {original_filename}.")

        # Create a Future object for this request and store it
        loop = asyncio.get_event_loop()
        future_result = loop.create_future()
        pending_requests[unique_request_id] = future_result
        logging.info(f"Added request {unique_request_id} to pending_requests.")

        # Await the result from the response queue poller indefinitely (no timeout)
        prediction_result = await future_result
        
        logging.info(f"Returning prediction for {original_filename}: {prediction_result}")
        return PlainTextResponse(prediction_result)

    except Exception as e: # Catch all exceptions, including cancelled futures if the app shuts down
        logging.error(f"Error processing upload for {original_filename}: {e}")
        # Clean up pending request if an error occurs before awaiting result
        if unique_request_id in pending_requests:
            del pending_requests[unique_request_id]
        # Depending on the type of error, you might want to return a different HTTPException status code
        if isinstance(e, asyncio.CancelledError):
            raise HTTPException(status_code=500, detail="Request processing cancelled (e.g., server shutdown).")
        else:
            raise HTTPException(status_code=500, detail=f"Failed to process image upload: {e}")

