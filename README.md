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
* `clear_s3.py`: Clears contents of S3 buckets.
* `check.py`: Checks current AWS instance and S3 status.
* `multithread_workload_generator.py`: Client-side script to send requests and evaluate performance.
* `config.py`: **Configurable parameters for AWS setup.**
* `key.py`: **Your AWS Access Keys (KEEP SECURE!).**

## Configuration

```python
AWS_REGION = 'ap-northeast-2'
S3_INPUT_BUCKET = 'cse546-zhoudixin-image-input-bucket'
S3_OUTPUT_BUCKET = 'cse546-zhoudixin-image-output-bucket'
SQS_QUEUE_NAME = 'cse546-zhoudixin-image-processing-queue'
RESPONSE_SQS_QUEUE_NAME = 'cse546-zhoudixin-image-response-queue'
EC2_KEY_PAIR_NAME = 'zhoudixin-ap-northeast-2'
AMI_ID = "ami-0662f4965dfc70aca"
```

## AWS Resources & Key Info

Upon successful `setup_aws.py` execution, the following are created:

  * **EC2 Instances:**
      * **Web Tier:** Instance ID `i-01aff404736c53130`, Public IP: `15.164.104.175`
      * **App Tier:** Auto-scaled instances.
  * **S3 Buckets:**
      * `cse546-zhoudixin-image-input-bucket`
      * `cse546-zhoudixin-image-output-bucket`
  * **SQS Queues:**
      * Request Queue: `cse546-zhoudixin-image-processing-queue` (URL: `https://sqs.ap-northeast-2.amazonaws.com/129271359039/cse546-zhoudixin-image-processing-queue`)
      * Response Queue: `cse546-zhoudixin-image-response-queue` (URL: `https://sqs.ap-northeast-2.amazonaws.com/129271359039/cse546-zhoudixin-image-response-queue`)
  * **EC2 Key Pair:** `zhoudixin-ap-northeast-2` (saved as `zhoudixin-ap-northeast-2.pem`).
  * **Security Groups:**
      * Web Tier SG: `zhoudixin-ap-northeast-2-web-sg` (ID: `sg-0bcc0673bda8a5f28`)
      * App Tier SG: `zhoudixin-ap-northeast-2-app-sg` (ID: `sg-0f147d724933ace45`)

**Web Tier URL:** `http://15.164.104.175:8000/upload`

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

Send image classification requests. Replace `<YOUR_WEB_TIER_PUBLIC_IP>` with the actual IP (e.g., `15.164.104.175`):

```bash
python multithread_workload_generator.py --num_request 100 --url [http://15.164.104.175:8000/upload](http://15.164.104.175:8000/upload) --image_folder ./imagenet-100
```

This will show real-time results and a final performance summary. Run `check.py` again afterward to see resource changes.

### Cleanup

**Important:** Terminate all AWS resources to avoid charges:

```bash
python cleanup_aws.py
```

Alternatively, just clear S3 buckets:

```bash
python clear_s3.py
```