import os
import sys
import json
from flask import Flask

# Add backend directory to sys.path
sys.path.append('/home/Larry/code/Ziqiu/LabelSystem/backend')

from app import app

def test_backend():
    print("Testing Backend...")
    
    # Create a test client
    client = app.test_client()
    
    # 1. Test /api/samples
    print("\n1. Testing /api/samples")
    response = client.get('/api/samples')
    if response.status_code == 200:
        samples = response.json
        print(f"Success! Found {len(samples)} samples.")
        if len(samples) > 0:
            sample_id = samples[0]['id']
            print(f"Testing with sample: {sample_id}")
            
            # 2. Test /api/samples/<sample_id>
            print(f"\n2. Testing /api/samples/{sample_id}")
            response = client.get(f'/api/samples/{sample_id}')
            if response.status_code == 200:
                data = response.json
                print("Success! Sequences found:")
                for seq in data['sequences']:
                    print(f" - {seq['name']} ({seq['count']} files)")
                
                if len(data['sequences']) > 0:
                    sequence = data['sequences'][0]['name']
                    
                    # 3. Test /api/samples/<sample_id>/<sequence>/files
                    print(f"\n3. Testing /api/samples/{sample_id}/{sequence}/files")
                    response = client.get(f'/api/samples/{sample_id}/{sequence}/files')
                    if response.status_code == 200:
                        files = response.json
                        print(f"Success! Found {len(files)} files.")
                        if len(files) > 0:
                            # Verify metadata structure
                            first_file = files[0]
                            if 'SliceLocation' in first_file and 'TriggerTime' in first_file:
                                print("Metadata extraction verified.")
                            else:
                                print("WARNING: Metadata missing in file list response.")
                                print(first_file)
                    else:
                        print(f"Failed: {response.status_code} - {response.data}")
            else:
                print(f"Failed: {response.status_code} - {response.data}")
    else:
        print(f"Failed: {response.status_code} - {response.data}")

if __name__ == "__main__":
    test_backend()
