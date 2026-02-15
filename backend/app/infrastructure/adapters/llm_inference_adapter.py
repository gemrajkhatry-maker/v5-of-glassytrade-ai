import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import logging
import os

logger = logging.getLogger(__name__)

class LLMInferenceAdapter:
    _instance = None
    
    # Paths from POC - In production these should be config-driven
    BASE_MODEL_PATH = "/Users/apple/Downloads/v5-of-glassytrade-ai/poc/models/Nanbeige4.1-3B"
    ADAPTER_PATH = "/Users/apple/Downloads/v5-of-glassytrade-ai/poc/lora_adapter_mac"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LLMInferenceAdapter, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = None
        self.tokenizer = None
        self._is_loading = False
        self._start_background_loading()
        self._initialized = True

    def _start_background_loading(self):
        import threading
        if not self._is_loading and self.model is None:
            self._is_loading = True
            logger.info("Starting AI Model loading in background thread...")
            thread = threading.Thread(target=self._load_model)
            thread.daemon = True
            thread.start()

    def _load_model(self):
        """Loads the model and tokenizer."""
        try:
            logger.info(f"Loading Base Model from {self.BASE_MODEL_PATH} on {self.device}...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.BASE_MODEL_PATH)
            
            base_model = AutoModelForCausalLM.from_pretrained(
                self.BASE_MODEL_PATH,
                torch_dtype=torch.float16,
                device_map=self.device,
                trust_remote_code=True
            )
            
            logger.info(f"Loading LoRA Adapter from {self.ADAPTER_PATH}...")
            self.model = PeftModel.from_pretrained(base_model, self.ADAPTER_PATH)
            self.model.eval()
            self._is_loading = False
            logger.info("AI Model successfully loaded!")
            
        except Exception as e:
            logger.error(f"Failed to load AI Model: {str(e)}")
            self._is_loading = False
            # Don't raise here, otherwise thread crashes silently. 
            # predict() will handle the missing model.

    def predict(self, instruction: str, input_text: str) -> str:
        """Runs inference on the loaded model."""
        if not self.model:
            if self._is_loading:
                return "Analysis Warning: Model is still loading..."
            return "Analysis Error: Model failed to load."

        alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
"""
        prompt = alpaca_prompt.format(instruction, input_text)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs, 
                max_new_tokens=256, 
                use_cache=True,
                temperature=0.1 
            )
        
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        # Extract only the response part
        clean_response = response.split("### Response:")[-1].strip()
        return clean_response
