import argparse
import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor

def send_one_request(image_path):
    file = {"myfile": open(image_path, 'rb')}
    r = requests.post(args.url, files=file)
    if r.status_code != 200:
        print('sendErr: ' + r.url)
    else:
        image_msg = os.path.basename(image_path) + ' uploaded!'
        msg = image_msg + '\n' + 'Classification result: ' + r.text
        print(msg)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Upload images')
    parser.add_argument('--num_request', type=int, help='one image per request', required=True)
    parser.add_argument('--url', type=str, help='URL to the backend server, e.g. http://3.86.108.221/upload', required=True)
    parser.add_argument('--image_folder', type=str, help='Path to the folder containing images', required=True)
    args = parser.parse_args()

    start_time = time.time()
    num_max_workers = args.num_request
    image_path_list = []

    for i, name in enumerate(os.listdir(args.image_folder)):
        if i == args.num_request:
            break
        image_path_list.append(os.path.join(args.image_folder, name))

    with ThreadPoolExecutor(max_workers=num_max_workers) as executor:
        executor.map(send_one_request, image_path_list)

    elapsed = time.time() - start_time
    print(f"\nFinished uploading {args.num_request} images in {elapsed/60:.2f} minutes.")
