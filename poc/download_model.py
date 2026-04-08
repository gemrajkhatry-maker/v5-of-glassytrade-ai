from huggingface_hub import snapshot_download
import os

MODEL_ID = "mlx-community/gemma-4-26b-a4b-it-4bit"
LOCAL_DIR = "./models/gemma-4-26b-it-4bit"

def download_model():
    print(f"Downloading {MODEL_ID} to {LOCAL_DIR}...")
    print(f"WARNING: This is a 26B parameter model (~20GB download)")
    os.makedirs(LOCAL_DIR, exist_ok=True)
    
    try:
        snapshot_download(
            repo_id=MODEL_ID,
            local_dir=LOCAL_DIR,
            resume_download=True
        )
        print("Download complete!")
    except Exception as e:
        print(f"Error downloading model: {e}")

if __name__ == "__main__":
    download_model()
