"""Utility functions for MLX LoRA Trainer."""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Generator, Tuple, Union, List

import mlx.core as mx
import mlx.nn as nn
import yaml
from transformers import PreTrainedTokenizer

def setup_logging(log_file: Optional[str] = None) -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            *([] if log_file is None else [logging.FileHandler(log_file)])
        ]
    )

def ensure_dir(path: str) -> None:
    """Ensure directory exists."""
    Path(path).mkdir(parents=True, exist_ok=True)

def load_config(config_path: Union[str, Path]) -> Dict[str, Any]:
    """Load configuration from YAML file.
    
    Args:
        config_path: Path to config file
        
    Returns:
        Configuration dictionary
    """
    if isinstance(config_path, str):
        config_path = Path(config_path)
        
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    if not isinstance(config, dict):
        raise ValueError("Config must be a dictionary")
    
    return config

def sample_top_p(logits: mx.array, p: float = 0.9) -> mx.array:
    """Sample from logits with top-p sampling."""
    probs = mx.softmax(logits)
    indices = mx.argsort(-probs)
    sorted_probs = probs[indices]
    cumsum = mx.cumsum(sorted_probs)
    mask = cumsum <= p
    sorted_probs = mx.where(mask, sorted_probs, 0)
    sorted_probs = sorted_probs / mx.sum(sorted_probs)
    return indices[mx.random.categorical(mx.log(sorted_probs))]

def generate(
    model: nn.Module,
    tokenizer: PreTrainedTokenizer,
    prompt: str,
    max_tokens: int = 100,
    temperature: float = 0.7,
    top_p: float = 0.9,
) -> Generator[Tuple[str, mx.array], None, None]:
    """Generate text tokens with top-p sampling."""
    tokens = mx.array(tokenizer.encode(prompt))
    
    for _ in range(max_tokens):
        logits = model(tokens)[-1]
        
        if temperature > 0:
            logits = logits / temperature
            token = sample_top_p(logits, top_p)
        else:
            token = mx.argmax(logits)
        
        tokens = mx.concatenate([tokens, mx.array([token])])
        
        # Check if we hit the end of text
        if token == tokenizer.eos_token_id:
            break
        
        text = tokenizer.decode(tokens, skip_special_tokens=True)
        next_token = tokenizer.decode(token, skip_special_tokens=True)
        yield next_token, tokens

def split_batch(batch: Dict[str, mx.array], num_chunks: int) -> List[Dict[str, mx.array]]:
    """Split a batch into smaller chunks for gradient accumulation."""
    if num_chunks == 1:
        return [batch]
        
    batch_size = len(next(iter(batch.values())))
    chunk_size = batch_size // num_chunks
    
    chunks = []
    for i in range(num_chunks):
        start_idx = i * chunk_size
        end_idx = start_idx + chunk_size if i < num_chunks - 1 else batch_size
        
        chunk = {
            k: v[start_idx:end_idx] 
            for k, v in batch.items()
        }
        chunks.append(chunk)
    
    return chunks

def compute_grad_norm(model: nn.Module) -> float:
    """Compute gradient norm for the model parameters."""
    total_norm = 0.0
    for p in model.parameters():
        if p.grad is not None:
            total_norm += mx.sum(p.grad ** 2)
    return float(mx.sqrt(total_norm))
