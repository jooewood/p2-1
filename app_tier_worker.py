# app_tier_worker.py

import boto3
import os
import time
import logging
import subprocess # To call the external image classification script

from key import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY
)

from config import (
    AWS_REGION,
    S3_INPUT_BUCKET, S3_OUTPUT_BUCKET, SQS_QUEUE_NAME,
    REMOTE_APP_DIR
)

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

def get_queue_url():
    """Retrieves the SQS queue URL."""
    try:
        response = sqs.get_queue_url(QueueName=SQS_QUEUE_NAME)
        return response['QueueUrl']
    except Exception as e:
        logging.error(f"Failed to get SQS queue URL for {SQS_QUEUE_NAME}: {e}")
        return None

def download_image_from_s3(s3_key, download_path):
    """Downloads an image from S3 to a local path."""
    try:
        s3.download_file(S3_INPUT_BUCKET, s3_key, download_path)
        logging.info(f"Downloaded s3://{S3_INPUT_BUCKET}/{s3_key} to {download_path}")
        return True
    except Exception as e:
        logging.error(f"Error downloading {s3_key} from S3: {e}")
        return False

def upload_result_to_s3(output_s3_key, result_text_content):
    """
    Uploads the image recognition result to S3.
    output_s3_key: The specific key to use in the output S3 bucket (e.g., 'test_0').
    result_text_content: The content to store (e.g., '(test_0, bathtub)').
    """
    try:
        s3.put_object(Bucket=S3_OUTPUT_BUCKET, Key=output_s3_key, Body=result_text_content.encode('utf-8'))
        logging.info(f"Uploaded result for {output_s3_key} to s3://{S3_OUTPUT_BUCKET}/{output_s3_key}")
        return True
    except Exception as e:
        logging.error(f"Error uploading result for {output_s3_key} to S3: {e}")
        return False

def perform_image_classification(image_path):
    """
    Executes the external image classification script and returns its raw output.
    The script is expected to output "image_name_with_ext,prediction_label".
    """
    cmd = [
        "python3",
        os.path.join(REMOTE_APP_DIR, "image_classification.py"),
        image_path
    ]
    logging.info(f"Executing classification command: {' '.join(cmd)}")
    try:
        # Run the command and capture output
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # The output of the script is expected to be "image_name,result" e.g., "test_0.JPEG,bathtub"
        raw_prediction_output = result.stdout.strip()
        logging.info(f"Classification script raw output for {image_path}: {raw_prediction_output}")
        return raw_prediction_output
    except subprocess.CalledProcessError as e:
        logging.error(f"Image classification script failed for {image_path}. Stderr: {e.stderr}")
        return None
    except Exception as e:
        logging.error(f"Error executing image classification script for {image_path}: {e}")
        return None

def main():
    """Main loop for the App Tier Worker."""
    queue_url = get_queue_url()
    if not queue_url:
        logging.error("Could not get SQS queue URL. Exiting worker.")
        return

    # Create a temporary directory for image downloads
    # Use /tmp for temporary files as it's typically cleared on reboot.
    temp_dir = "/tmp/image_processing"
    os.makedirs(temp_dir, exist_ok=True)
    logging.info(f"Created temporary directory: {temp_dir}")

    logging.info("App Tier Worker started. Polling SQS for messages...")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20 # Long polling
            )

            messages = response.get('Messages', [])
            if not messages:
                logging.info("No messages in queue. Waiting...")
                time.sleep(5) # Short sleep if no messages found quickly
                continue

            for message in messages:
                receipt_handle = message['ReceiptHandle']
                # Message body contains "unique_input_s3_key,output_s3_key_base"
                # Example: "uuid-test_0.JPEG,test_0"
                message_parts = message['Body'].split(',', 1)
                if len(message_parts) != 2:
                    logging.error(f"Malformed SQS message body: {message['Body']}. Skipping.")
                    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                    continue

                unique_input_s3_key = message_parts[0]
                output_s3_key_base = message_parts[1] # e.g., 'test_0'

                logging.info(f"Received message: Input S3 Key='{unique_input_s3_key}', Output S3 Key Base='{output_s3_key_base}', ReceiptHandle='{receipt_handle}'")

                # The original filename with extension is part of unique_input_s3_key (e.g., uuid-test_0.JPEG)
                original_filename_with_ext = unique_input_s3_key.split('-', 1)[-1] # Extracts "test_0.JPEG"

                local_image_path = os.path.join(temp_dir, original_filename_with_ext)

                if download_image_from_s3(unique_input_s3_key, local_image_path):
                    raw_prediction_output = perform_image_classification(local_image_path) # e.g., "test_0.JPEG,bathtub"

                    if raw_prediction_output:
                        # Parse the raw output from image_classification.py
                        # It's expected to be "image_name_with_ext,prediction_label"
                        output_parts = raw_prediction_output.split(',', 1)
                        if len(output_parts) == 2:
                            # image_name_from_classifier = output_parts[0] # e.g., test_0.JPEG
                            prediction_label = output_parts[1] # e.g., bathtub

                            # Format the content for S3 output bucket: "(image_name_base, prediction_label)"
                            # Example: "(test_0, bathtub)"
                            s3_output_content = f"({output_s3_key_base}, {prediction_label})"
                            
                            if upload_result_to_s3(output_s3_key_base, s3_output_content):
                                # Delete message from queue only after successful processing and upload
                                sqs.delete_message(
                                    QueueUrl=queue_url,
                                    ReceiptHandle=receipt_handle
                                )
                                logging.info(f"Successfully processed {unique_input_s3_key} and deleted message from queue.")
                            else:
                                logging.error(f"Failed to upload result for {unique_input_s3_key}. Message not deleted.")
                        else:
                            logging.error(f"Unexpected format from classification script: {raw_prediction_output}. Message not deleted.")
                    else:
                        logging.error(f"Image classification failed for {unique_input_s3_key}. Message not deleted.")
                else:
                    logging.error(f"Failed to download image {unique_input_s3_key}. Message not deleted.")

                # Clean up local image file
                if os.path.exists(local_image_path):
                    os.remove(local_image_path)
                    logging.info(f"Cleaned up local file: {local_image_path}")

        except Exception as e:
            logging.error(f"An error occurred in the worker loop: {e}")
            time.sleep(10) # Wait before retrying in case of transient errors

if __name__ == "__main__":
    main()

