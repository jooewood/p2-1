import argparse
import requests
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

def compute_accuracy(results):
    # results: list of tuples (image_name, predicted_label)
    df = pd.read_excel('label.xlsx')
    label_dict = dict(zip(df['Input'], df['Result']))
    correct = 0
    total = 0
    for image_name, pred in results:
        # Remove extension if needed, or match with Input column
        key = os.path.splitext(image_name)[0]
        if key in label_dict:
            total += 1
            if str(label_dict[key]).strip().lower() == str(pred).strip().lower():
                correct += 1
    accuracy = correct / total if total > 0 else 0
    print(f"{accuracy:.4f} ({correct}/{total})")

def send_one_request(image_path):
    file = {"myfile": open(image_path, 'rb')}
    r = requests.post(args.url, files=file)
    image_name = os.path.basename(image_path)
    if r.status_code != 200:
        print('sendErr: ' + r.url)
        return (image_name, None)
    else:
        image_msg = image_name + ' uploaded!'
        msg = image_msg + '\n' + 'Classification result: ' + r.text
        print(msg)
        return (image_name, r.text.strip())

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

    results = []
    with ThreadPoolExecutor(max_workers=num_max_workers) as executor:
        futures = [executor.submit(send_one_request, path) for path in image_path_list]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    elapsed = time.time() - start_time 
    print("All requests completed.")

    print("------ Summary ---")
    print("Input images number: ", len(image_path_list))
    print("Results received: ", len(results))
    print(f"Total time taken: {elapsed/60:.2f} minutes.")
    print("Accuracy: ")
    compute_accuracy(results)
    print("------ End of Summary ---\n")
    
