# config.py

import os


AWS_REGION = 'ap-northeast-3'
# S3 Bucket Names
S3_INPUT_BUCKET = 'cse546-zhoudixin-image-input-bucket' + '-' + AWS_REGION
S3_OUTPUT_BUCKET = 'cse546-zhoudixin-image-output-bucket' + '-' + AWS_REGION

# SQS Queue Name
SQS_QUEUE_NAME = 'cse546-zhoudixin-image-request-queue' + '-' + AWS_REGION
RESPONSE_SQS_QUEUE_NAME = 'cse546-zhoudixin-image-response-queue' + '-' + AWS_REGION

# EC2 Key Pair Name
EC2_KEY_PAIR_NAME = 'zhoudixin' + '-' + AWS_REGION

if AWS_REGION == 'ap-northeast-2':
    AMI_ID = "ami-0662f4965dfc70aca"
elif AWS_REGION == 'ap-northeast-3':
    AMI_ID = "ami-0aafffc426e129572"

# Instance Types
WEB_TIER_INSTANCE_TYPE = 't2.micro'
APP_TIER_INSTANCE_TYPE = 't2.micro'

# Application Directory on EC2 Instances
REMOTE_APP_DIR = '/home/ubuntu/cse546-iaas-app' # Directory to clone/store our app code

# Auto-scaling Parameters
MAX_APP_INSTANCES = 10
MIN_APP_INSTANCES = 0
# When queue depth is at max, at least 10 instances should be running
MIN_INSTANCES_AT_MAX_QUEUE = 10
# Number of messages per app instance to trigger scaling out
MESSAGES_PER_INSTANCE = 5
# Time interval (seconds) for the auto-scaling controller to check SQS queue depth
SCALING_CHECK_INTERVAL = 15
# Number of messages in queue considered "max depth" (adjust based on expected load)
MAX_QUEUE_DEPTH_THRESHOLD = 50

# Paths for local files
KEY_FILE_PATH = f"{EC2_KEY_PAIR_NAME}.pem"

# Web Tier Public IP placeholder (will be filled after instance creation)
WEB_TIER_PUBLIC_IP = "" # No longer directly used by user, but still useful for workload generator setup

# Polling interval and timeout for Web Tier to retrieve results from S3
WEB_TIER_POLLING_INTERVAL = 1 # seconds

GIT_REPO_URL = 'https://github.com/jooewood/p2-1.git'

if AWS_REGION == 'ap-northeast-2':
    WEB_SG_ID = 'sg-0303e7ac2a2d00420'
    APP_SG_ID = 'sg-0960071d7e59020f4'
elif AWS_REGION == 'ap-northeast-3':
    WEB_SG_ID = 'sg-037389aae84d1d5a2'
    APP_SG_ID = 'sg-009732a972aebd8e2'