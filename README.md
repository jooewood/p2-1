# Elastic Image Recognition Service on AWS IaaS

This project provides an elastic and cost-effective image recognition service using AWS IaaS, designed for automatic scaling based on demand.


## Project Overview

The service operates with two tiers:

1.  **Web Tier:** A FastAPI application on an EC2 instance that handles image uploads, sends requests to an SQS queue, and returns classification results from a response SQS queue.
2.  **App Tier:** EC2 instances running worker scripts that process SQS requests, classify images using an external script, and send results back. This tier auto-scales based on demand.


## Files

* `web_tier_app.py`: Web tier FastAPI application.
* `app_tier_worker.py`: App tier worker for image classification.
* `setup_aws.py`: Script to set up all AWS resources.
* `cleanup_aws.py`: Script to tear down all AWS resources.
* `check.py`: Checks current AWS instance and S3 status.
* `multithread_workload_generator.py`: Client-side script to send requests and evaluate performance.
* `config.py`: **Configurable parameters for AWS setup.**
* `key.py`: **Your AWS Access Keys (KEEP SECURE!).**

## Configuration

```python
AWS_REGION = 'ap-northeast-3'
# S3 Bucket Names
S3_INPUT_BUCKET = 'cse546-zhoudixin-image-input-bucket' + '-' + AWS_REGION
S3_OUTPUT_BUCKET = 'cse546-zhoudixin-image-output-bucket' + '-' + AWS_REGION
# SQS Queue Name
SQS_QUEUE_NAME = 'cse546-zhoudixin-image-request-queue' + '-' + AWS_REGION
RESPONSE_SQS_QUEUE_NAME = 'cse546-zhoudixin-image-response-queue' + '-' + AWS_REGION
# EC2 Key Pair Name
EC2_KEY_PAIR_NAME = 'zhoudixin' + '-' + AWS_REGION
```

## AWS Resources & Key Info

Upon successful `setup_aws.py` execution, the following are created:

  * **EC2 Instances:**
      * **Web Tier:** Public IP: `13.208.206.157`
      * **App Tier:** Auto-scaled instances.
  * **S3 Buckets:**
      * `cse546-zhoudixin-image-input-bucket-ap-northeast-3`
      * `cse546-zhoudixin-image-output-bucket-ap-northeast-3`
  * **SQS Queues:**
      * Request Queue: `cse546-zhoudixin-image-request-queue-ap-northeast-3` 
      (URL: `https://sqs.ap-northeast-3.amazonaws.com/129271359039/cse546-zhoudixin-image-request-queue-ap-northeast-3`)
      * Response Queue: `cse546-zhoudixin-image-response-queue-ap-northeast-3` 
      (URL: `https://sqs.ap-northeast-3.amazonaws.com/129271359039/cse546-zhoudixin-image-response-queue-ap-northeast-3`)
  * **EC2 Key Pair:** `zhoudixin-ap-northeast-2` (saved as `zhoudixin-ap-northeast-2.pem`).

**Web Tier URL:** `http://13.208.206.157:8000/upload`

## How to Use

### Prerequisites

  * AWS Account & CLI configured.
  * Python 3.x with `boto3`, `fastapi`, `uvicorn`, `requests`, `pandas`, `openpyxl`.
  * ImageNet 100 dataset (or similar with `label.xlsx`).
  * `key.py` with your AWS credentials.

### Setup

Run locally to create all AWS resources:

```bash
python setup_aws.py
```

*Note the Web Tier Public IP displayed after execution.*

### Monitor

Check current EC2 instances and S3 bucket contents:

```bash
python check.py
```

### Test

Send image classification requests. Replace `<YOUR_WEB_TIER_PUBLIC_IP>` with the actual IP (e.g., `13.208.206.157`):

```bash
python multithread_workload_generator.py --num_request 100 --url http://13.208.206.157:8000/upload --image_folder ./imagenet-100
```

This will show real-time results and a final performance summary. Run `check.py` again afterward to see resource changes.

### Cleanup

**Important:** Terminate all AWS EC2 and delete other resources:

```bash
python cleanup_aws.py --mode delete
```

Alternatively, Terminate all AWS EC2 and clear S3 buckets and SQS:

```bash
python cleanup_aws.py --mode clear
```