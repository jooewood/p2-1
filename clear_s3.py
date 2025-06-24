# -*- coding: utf-8 -*-
"""
Created on Mon Jun 23 23:51:21 2025

@author: F
"""

import boto3

from key import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY
)

from config import (
    AWS_REGION,
    S3_INPUT_BUCKET,
    S3_OUTPUT_BUCKET
)

# Create S3 client and resource
s3 = boto3.resource(
    's3',
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def clear_bucket(bucket_name):
    bucket = s3.Bucket(bucket_name)
    print(f'Clearing bucket: {bucket_name} ...')
    deleted = bucket.objects.all().delete()
    print(f'✔ Done: {bucket_name}, deleted {len(deleted)} batch(es)')

if __name__ == "__main__":
    clear_bucket(S3_INPUT_BUCKET)
    clear_bucket(S3_OUTPUT_BUCKET)
