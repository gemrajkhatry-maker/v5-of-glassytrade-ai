#!/usr/bin/env bash
# Download + reassemble the VibeThinker-3B + AMT LoRA model weights from the
# models-v1 GitHub Release on gemrajkhatry-maker/v5-of-glassytrade-ai, then
# verify checksums end-to-end. Idempotent and safe to re-run.
#
# The weights are too large for a normal git push (GitHub's 100MB/file limit),
# so they live as chunked Release assets. The model config/tokenizer files are
# already in the repo; this script restores only the weight binaries.
set -euo pipefail

REPO="gemrajkhatry-maker/v5-of-glassytrade-ai"
TAG="models-v1"
BASE="https://github.com/${REPO}/releases/download/${TAG}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST_MODEL="$ROOT/models/vibethinker-3b"
DEST_LORA="$ROOT/models/vibethinker-amt-lora"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Expected sha256 of the REASSEMBLED files (from the source machine).
SHA_SHARD1="2f060c748de624b9dcfe3159ef97242810c77974f32f3511668e9c70bef73754"
SHA_SHARD2="f0d4d1ef83d68a9268c42c90ff4d90317b5e60f8f78731349d63cfddc8852ce6"
SHA_ADAPTER="954dc89fbbd992e713d7814edda5fe28c843dcbb7225e459f54a1a4e270cb7c3"

echo "Downloading model chunks (~5.8GB) from ${REPO} release ${TAG}..."
for f in shard1.aa shard1.ab shard1.ac shard2.aa adapters.safetensors MANIFEST.sha256; do
  echo "  ${f}"
  curl -fL --retry 3 -o "$TMP/$f" "$BASE/$f"
done

echo "Verifying downloaded chunks..."
(cd "$TMP" && shasum -a 256 -c MANIFEST.sha256)

echo "Reassembling model shards..."
cat "$TMP/shard1.aa" "$TMP/shard1.ab" "$TMP/shard1.ac" > "$TMP/model-00001-of-00002.safetensors"
cp "$TMP/shard2.aa" "$TMP/model-00002-of-00002.safetensors"

echo "Verifying reassembled files..."
echo "$SHA_SHARD1  $TMP/model-00001-of-00002.safetensors" | shasum -a 256 -c -
echo "$SHA_SHARD2  $TMP/model-00002-of-00002.safetensors" | shasum -a 256 -c -
echo "$SHA_ADAPTER  $TMP/adapters.safetensors" | shasum -a 256 -c -

echo "Installing into ${DEST_MODEL} and ${DEST_LORA}..."
mkdir -p "$DEST_MODEL" "$DEST_LORA"
mv "$TMP/model-00001-of-00002.safetensors" "$TMP/model-00002-of-00002.safetensors" "$DEST_MODEL/"
mv "$TMP/adapters.safetensors" "$DEST_LORA/adapters.safetensors"

echo "Done. Model ready at:"
echo "  $DEST_MODEL"
echo "  $DEST_LORA"
