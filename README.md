# MDZ C2

Painel web → API C2 remota.

## Render

1. Fork/push este repo
2. Render → New Web Service → conecte o repo
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn mdj:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
5. Deploy

IP de saída do Render precisa estar liberado na API (`/setip`).
