import json
from pathlib import Path
from scripts.amt_dataset_generator import AMTScenarioGenerator, PROFILES, DatasetExporter, DEFAULT_SYSTEM_INSTRUCTION

class TestAMTDatasetGenerator:
    def test_profile_integrity(self):
        assert "NSE" in PROFILES
        assert PROFILES["NSE"].currency == "₹"

    def test_scenario_generation(self):
        generator = AMTScenarioGenerator(PROFILES["NSE"])
        prompt, completion = generator.create_prompt_and_completion("LONG_ABSORPTION")
        
        assert "NSE Options" in prompt
        assert "Enter Long" in completion
        assert "Market State:" in completion
        assert "Logic:" in completion

    def test_exporter_chatml(self):
        exporter = DatasetExporter()
        entry = exporter.to_chatml("System", "User", "Assistant")
        
        assert "messages" in entry
        assert len(entry["messages"]) == 3
        assert entry["messages"][0]["role"] == "system"
        assert entry["messages"][2]["content"] == "Assistant"

    def test_exporter_mlx(self):
        exporter = DatasetExporter()
        entry = exporter.to_mlx_text("System", "User", "Assistant")
        
        assert "text" in entry
        assert "<|im_start|>system\nSystem<|im_end|>" in entry["text"]
        assert "<|im_start|>assistant\nAssistant<|im_end|>" in entry["text"]

    def test_stay_flat_risk_scenario(self):
        generator = AMTScenarioGenerator(PROFILES["NSE"])
        prompt, completion = generator.create_prompt_and_completion("STAY_FLAT_RISK")
        
        assert "consecutive losses" in prompt
        assert "Stay Flat" in completion
