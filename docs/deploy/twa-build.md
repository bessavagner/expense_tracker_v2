# TWA / APK build runbook (Sprint 11)

App Android = **TWA** empacotando a PWA. Distribuição: **APK assinado por sideload**
(sem Play Console). Host: `expense-tracker-654941182076.southamerica-east1.run.app`.

## Decisões travadas
- **applicationId:** `com.bessavagner.ledger`
- **Nome no launcher:** `Ledger`
- **Host / manifest:** `https://expense-tracker-654941182076.southamerica-east1.run.app/manifest.webmanifest`
- **Digital Asset Links:** servido por Django em `/.well-known/assetlinks.json`
  (rota `core.views.AssetLinksView`; fingerprint vem da env `TWA_CERT_FINGERPRINT`).

## Build do APK com Bubblewrap (rodar num terminal de verdade — TTY)

Pré-requisitos: Node (ok), JDK (o Bubblewrap baixa o JDK 17 dele). Espaço ~1GB.

```bash
# 1. instalar o CLI (já feito globalmente nesta máquina)
npm i -g @bubblewrap/cli

# 2. criar o projeto TWA (numa pasta dedicada, FORA do repo)
mkdir -p ~/Documents/projetos/expense_tracker_v2-twa
cd ~/Documents/projetos/expense_tracker_v2-twa
bubblewrap init --manifest https://expense-tracker-654941182076.southamerica-east1.run.app/manifest.webmanifest
#   Responda aos prompts:
#   - Install JDK / Android SDK? -> Yes (baixa ~1GB)
#   - Application name: Expense Tracker   | Short name (launcher): Ledger
#   - Application ID / package: com.bessavagner.ledger
#   - Display mode: standalone | Orientation: portrait
#   - Theme color: #147874 | Background: #f5f3ef (defaults vêm do manifest)
#   - Signing key: criar novo -> ele cria android.keystore com alias "android"
#     >>> ESCOLHA uma senha e GUARDE (necessária p/ atualizar o app no futuro) <<<

# 3. buildar o APK assinado
bubblewrap build
#   gera: app-release-signed.apk  (+ app-release-bundle.aab)

# 4. pegar o fingerprint SHA-256 da chave (é o que entra no assetlinks.json)
bubblewrap fingerprint  # OU:
keytool -list -v -keystore ./android.keystore -alias android | grep -A1 SHA256
#   copie a linha SHA256:  AA:BB:CC:...  (64 hex com ':')
```

## Depois do build (eu assumo de novo)
1. Você me passa o **SHA-256 fingerprint**.
2. Eu seto `TWA_CERT_FINGERPRINT=<fingerprint>` na env do Cloud Run e faço o deploy
   (a rota `/.well-known/assetlinks.json` passa a verificar a posse).
3. Confiro o assetlinks vivo no host e você instala o `app-release-signed.apk` nos 2 celulares
   (transferir + tocar; habilitar "instalar apps de fontes desconhecidas"). O app deve abrir
   **sem a barra de URL** (asset links verificado).

## Segredo
O `android.keystore` + senha são **secretos** e **não vão pro git**. Guarde o keystore
num lugar seguro com backup — sem ele você não consegue publicar atualizações do mesmo app.
