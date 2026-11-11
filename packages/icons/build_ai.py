"""Build apps/web/src/components/ai-brands.json: AI provider type -> logo SVG body (24x24).

Logos from LobeHub Icons (MIT, https://github.com/lobehub/lobe-icons). The logos are trademarks of their
owners and are used only to identify each provider. Source: npm pack @lobehub/icons-static-svg
Usage: python3 packages/icons/build_ai.py path/to/icons-static-svg/icons apps/web/src/components/ai-brands.json
A provider type with no logo here is drawn with the first two letters of its name.
"""
import json
import re
import sys
from pathlib import Path

# provider type (apps/api/app/modules/ai/catalog.py) -> LobeHub file; "-color" files keep the brand colours
MAP = {
    "openai": "openai", "anthropic": "claude-color", "gemini": "gemini-color", "azure_openai": "azure-color",
    "xai": "xai", "mistral": "mistral-color", "deepseek": "deepseek-color", "qwen": "qwen-color",
    "moonshot": "kimi-color", "cohere": "cohere-color", "perplexity": "perplexity-color", "groq": "groq",
    "together": "together-color", "fireworks": "fireworks-color", "openrouter": "openrouter", "ollama": "ollama",
    "lmstudio": "lmstudio", "stability": "stability-color", "replicate": "replicate", "runway": "runway",
    "luma": "luma-color", "elevenlabs": "elevenlabs",
}
ROOT = re.compile(r"<svg([^>]*)>(.*)</svg>\s*$", re.S)
ATTR = re.compile(r'\s(fill|fill-rule|clip-rule)="([^"]*)"')


def body(svg: str) -> str:
    m = ROOT.match(svg.strip())
    if not m:
        raise ValueError("not an svg")
    attrs, inner = m.groups()
    inner = re.sub(r"<title>.*?</title>", "", inner, flags=re.S)
    if re.search(r"<script|on[a-z]+=|href=\"(?!#)", inner, re.I):
        raise ValueError("unsafe svg")
    keep = " ".join(f'{k}="{v}"' for k, v in ATTR.findall(attrs))
    return f"<g {keep}>{inner}</g>" if keep else inner


def main(source: str, target: str) -> None:
    out = {}
    for ptype, name in MAP.items():
        svg = (Path(source) / f"{name}.svg").read_text()
        out[ptype] = {"body": body(svg), "color": name.endswith("-color")}
    Path(target).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(out)} logos -> {target}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
