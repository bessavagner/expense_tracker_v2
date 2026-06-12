# Spec — PWA instalável (Sprint 10)

> Status: aprovado (2026-06-12). Backlog: `docs/deploy/backlog-deploy.md` Sprint 10 (tasks 10.1–10.5).

## Objetivo

Transformar a web app (Django 6 + HTMX + ilha React) num **PWA instalável**, responsivo,
com **app shell offline**. É o passo que destrava o app Android (Sprint 11 TWA). O app já roda
em HTTPS estável no Cloud Run, então o requisito de HTTPS para PWA está atendido.

## Decisões fechadas (brainstorming 2026-06-12)

| Tema | Decisão |
|------|---------|
| **Comportamento offline** | **Shell + fallback offline.** Estáticos em cache (cache-first); navegação network-first com página `/offline/` de fallback. Dados financeiros (saldos, lançamentos, API) **sempre da rede** — nunca mostrar número desatualizado como atual. Writes exigem rede. |
| **Tooling do SW** | **Service worker vanilla** (~60 linhas) servido por **view Django** em `/sw.js` (escopo raiz). Sem Workbox, sem vite-plugin-pwa, sem dependência nova. |
| **Ícone** | **Marca "ledger" gerada** — geométrica, paleta teal do tema, maskable com safe zone, nos tamanhos 192/512 + apple-touch. Mostrar PNG ao usuário p/ aprovar antes de commitar. |

### Guardrails de escopo (YAGNI — fora desta sprint)

Sem fila de writes offline, sem IndexedDB, sem sincronização, sem Workbox, sem push notifications.
Apenas: instalável + estáticos rápidos + offline gracioso.

## Arquitetura — 5 unidades isoláveis

| Unidade | O que faz | Onde |
|---------|-----------|------|
| **Manifest view** | Serve `manifest.webmanifest` como **template renderizado** (p/ `{% static %}` resolver URLs de ícones hasheadas em prod). Content-Type `application/manifest+json`. | `core/views.py` + url `/manifest.webmanifest` |
| **Service worker view** | Serve `sw.js` em **escopo raiz** com header `Service-Worker-Allowed: /`, `Content-Type: application/javascript`, e `Cache-Control: no-cache` (p/ updates do SW chegarem). | `core/views.py` + url `/sw.js` |
| **SW script** | SW vanilla: `install`→precache do shell; `activate`→purga caches antigos; `fetch`→roteamento (ver abaixo). | `static/js/sw.js` (fonte) |
| **Ícones** | `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon.png` (180). | `static/images/pwa/` |
| **Registro + head tags** | `<link rel="manifest">`, `<meta name="theme-color">` (light/dark), apple tags, e script que registra `/sw.js`. | `templates/base.html` |
| **Offline page** | Rota `/offline/` (`TemplateView`, sem auth, sem DB): página "Sem conexão" no tema ledger com botão "Tentar novamente". | `core/views.py` + url `/offline/` + `templates/offline.html` |

## Fluxo de dados — roteamento do `fetch` no SW

O coração da feature. Para cada requisição:

1. **Bypass total** (SW faz `return;`, sem `respondWith`) quando:
   - método não-GET (POST/PUT/PATCH/DELETE — todos os writes);
   - path começa com `/api/` (inclui o **stream SSE do assistente** — NÃO pode ser bufferizado);
   - path começa com `/admin/` ou é `/healthz/`.
2. **Estáticos** (`/static/*`): **cache-first** → se não tem, busca na rede e cacheia. Seguro porque
   `ManifestStaticFilesStorage` hasheia os nomes (imutáveis).
3. **Navegações** (`request.mode === 'navigate'`, GET HTML): **network-first** → em falha de rede,
   serve `/offline/` do cache. Nunca cacheia páginas vivas → saldo nunca aparece desatualizado.
4. **Resto** (GET de outras origens, fontes Google, etc.): network-first simples, sem cachear.

**Precache no `install`:** `/offline/`, os 4 ícones, e o CSS/JS do shell (tailwind.css, mount.js).
Nome do cache versionado: `ledger-pwa-v1`. No `activate`, deletar todo cache cujo nome ≠ atual → updates limpos.

## Manifest — conteúdo

```json
{
  "name": "Expense Tracker",
  "short_name": "Ledger",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait",
  "lang": "pt-BR",
  "dir": "ltr",
  "theme_color": "#147874",
  "background_color": "#f5f3ef",
  "categories": ["finance"],
  "icons": [
    { "src": "<static icon-192>", "sizes": "192x192", "type": "image/png" },
    { "src": "<static icon-512>", "sizes": "512x512", "type": "image/png" },
    { "src": "<static icon-maskable-512>", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```

Hexes sRGB convertidos do oklch do tema `ledger` (`static/css/input.css`): `theme_color` = primary
`oklch(52% 0.085 190)` → `#147874`; `background_color` = base-200 `oklch(96.5% 0.006 95)` → `#f5f3ef`.
Dark theme-color (meta tag) = base-200 dark `oklch(17.5% 0.012 240)` → `#0c1115`.

## Head tags em `base.html`

- `<link rel="manifest" href="/manifest.webmanifest">`
- `<meta name="theme-color" content="<paper>" media="(prefers-color-scheme: light)">` e variante dark.
- `<link rel="apple-touch-icon" href="<static apple-touch-icon>">` + `<meta name="apple-mobile-web-app-capable" content="yes">` + `apple-mobile-web-app-status-bar-style`.
- Script de registro (defer, após load): `if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js')`.

## Gotchas (já endereçados no design)

- **SSE/writes bypassados** — o assistente streama via SSE em `/api/assistant/`; o SW não pode interceptar.
- **SW no root** — servido de `/sw.js` p/ escopo = app inteiro (não `/static/sw.js`, que limitaria o escopo).
- **Manifest renderizado** — `{% static %}` resolve nomes hasheados sob `ManifestStaticFilesStorage` (prod).
- **`manage.py check --deploy`** deve continuar limpo.

## Testes (TDD — teste que falha primeiro)

`core/tests/test_pwa.py`:

- `/manifest.webmanifest` → 200, Content-Type `application/manifest+json`, JSON válido com chaves
  obrigatórias (`name`, `start_url`, `display`, `icons`), e URLs de ícones presentes.
- `/sw.js` → 200, Content-Type JS, header `Service-Worker-Allowed: /`.
- `/offline/` → 200 **sem login** (não exige auth, não toca DB).
- Arquivos de ícone existem nos paths estáticos esperados.

Validação não-unitária (tasks do backlog):

- **10.4** Lighthouse PWA → "installable" verde; corrigir pendências (manifest, SW, viewport, HTTPS).
- **10.5** QA mobile responsivo (dashboard, formulários, chat) via Playwright/screenshots no viewport mobile.

## Mapeamento p/ backlog

- 10.1 Web App Manifest → Manifest view + conteúdo.
- 10.2 Ícones + splash → unidade Ícones + apple/theme-color tags.
- 10.3 Service Worker → SW view + script + roteamento + offline page.
- 10.4 Auditoria de instalabilidade → Lighthouse.
- 10.5 QA mobile → passada Playwright.
