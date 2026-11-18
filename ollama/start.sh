#!/bin/sh
# Start the Ollama server, then download the model on first start (it is kept in the `ollama`
# volume, so later starts need no network). If the download fails, the server keeps running and
# ShopFlow falls back to its offline rules until the model is there.
ollama serve &
server=$!
# This script is PID 1 in the container: pass `docker compose stop` on to the server, so it stops at once
# instead of being killed after the 10 s grace period.
trap 'kill -TERM "$server" 2>/dev/null' TERM INT
until ollama list >/dev/null 2>&1; do sleep 1; done
model="${LOCAL_LLM_MODEL:-qwen2.5:3b}"
if ollama list | grep -q "^${model}"; then
  echo "ShopFlow: model ${model} is ready"
else
  echo "ShopFlow: downloading ${model} (first start only)"
  if ollama pull "${model}"; then
    echo "ShopFlow: model ${model} is ready"
  else
    echo "ShopFlow: could not download ${model}; the app will use its offline rules"
  fi
fi
wait "$server"
