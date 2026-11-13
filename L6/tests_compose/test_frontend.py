# test dei file Docker del front-end: build in due fasi, proxy /api di nginx, .dockerignore
# librerie standard: percorsi
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def leggi(nome: str) -> str:
    return (FRONTEND / nome).read_text(encoding="utf-8")


def test_dockerfile_in_due_fasi():
    testo = leggi("Dockerfile")
    for parte in ("FROM node:24-alpine AS build", "RUN npm ci", "RUN npm run build", "FROM nginx:alpine",
                  "COPY --from=build /app/dist /usr/share/nginx/html",
                  "COPY nginx.conf /etc/nginx/conf.d/default.conf"):
        assert parte in testo, parte
    # prima package.json e lock (livello di npm ci in cache), poi il resto
    assert testo.index("COPY package.json package-lock.json") < testo.index("RUN npm ci")


def test_nginx_proxy_api():
    testo = leggi("nginx.conf")
    for parte in ("listen 80;", "location /api/", "proxy_pass http://backend:8001/;",
                  "proxy_read_timeout 330s;", "try_files $uri $uri/ /index.html;"):
        assert parte in testo, parte


def test_dockerignore_del_frontend():
    voci = leggi(".dockerignore").splitlines()
    assert "node_modules/" in voci and "dist/" in voci
    # tsc --noEmit (dentro npm run build) controlla anche tests/ e *.config.ts: non vanno esclusi
    assert not any("tests" in v or "config.ts" in v for v in voci)
