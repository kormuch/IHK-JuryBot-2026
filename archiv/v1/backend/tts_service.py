"""
Text-to-Speech service using Microsoft Edge TTS.

Default voice: de-DE-ConradNeural (German male).
Output format: MP3 saved to tts_output/ directory.
"""

import edge_tts
from pathlib import Path


async def generate_speech(
    text: str,
    output_path: str,
    voice: str = "de-DE-ConradNeural",
) -> str:
    """Generate German TTS audio file using edge-tts. Return file path."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    return output_path
