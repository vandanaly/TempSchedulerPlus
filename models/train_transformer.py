import torch
from .transformer_encoder import FileTemperatureTransformer

def ensure_model(device: torch.device) -> FileTemperatureTransformer:
    """
    Initializes the Transformer model and moves it to the appropriate device (CPU/GPU).
    """
    model = FileTemperatureTransformer().to(device)
    model.eval() # Set to evaluation mode for inference
    return model