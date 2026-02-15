from huggingface_hub import snapshot_download
import os

MODEL_ID = "Nanbeige/Nanbeige4.1-3B"
LOCAL_DIR = "./models/Nanbeige4.1-3B"

def download_model():
    print(f"Downloading {MODEL_ID} to {LOCAL_DIR}...")
    os.makedirs(LOCAL_DIR, exist_ok=True)
    
    try:
        snapshot_download(
            repo_id=MODEL_ID,
            local_dir=LOCAL_DIR,
            local_dir_use_symlinks=False,
            resume_download=True
        )
        print("Download complete!")
    except Exception as e:
        print(f"Error downloading model: {e}")

if __name__ == "__main__":
    download_model()
