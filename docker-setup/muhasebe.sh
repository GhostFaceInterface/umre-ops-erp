#!/bin/bash
# Umre Ops - Tek Tıkla Yerel Muhasebe Platformu Yönetim Betiği
set -e

# Renk tanımları (Arayüz estetiği için)
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJ_DIR="/Users/boe747/muhasebe/erpnext-prod"
COMPOSE_FILE="${PROJ_DIR}/pwd.yml"

echo -e "${BLUE}======================================================${NC}"
echo -e "${BLUE}        UMRE OPS - YEREL MUHASEBE PLATFORMU           ${NC}"
echo -e "${BLUE}======================================================${NC}"

# 1. Docker Desktop'ın çalışıp çalışmadığını kontrol et
if ! docker info >/dev/null 2>&1; then
    echo -e "${YELLOW}[!] Docker Desktop çalışmıyor. Başlatılıyor...${NC}"
    open -a Docker
    
    echo -n "Docker daemon hazır olana kadar bekleniyor"
    until docker info >/dev/null 2>&1; do
        echo -n "."
        sleep 2
    done
    echo -e "\n${GREEN}[+] Docker Desktop başarıyla başlatıldı.${NC}"
else
    echo -e "${GREEN}[+] Docker Desktop zaten çalışıyor.${NC}"
fi

# 2. Docker Compose ile servisleri ayağa kaldır
echo -e "${BLUE}[*] Muhasebe servisleri başlatılıyor...${NC}"
docker compose -f "$COMPOSE_FILE" up -d

# 2.1. Nginx sembolik link erişim sorunlarını çözmek için asset linklerini fiziksel klasörle değiştir
if docker exec erpnext-prod-backend-1 test -L /home/frappe/frappe-bench/sites/assets/frappe; then
    echo -e "${BLUE}[*] Nginx statik asset yolları optimize ediliyor...${NC}"
    docker exec erpnext-prod-backend-1 rm -f /home/frappe/frappe-bench/sites/assets/frappe
    docker exec erpnext-prod-backend-1 cp -r /home/frappe/frappe-bench/apps/frappe/frappe/public /home/frappe/frappe-bench/sites/assets/frappe
    docker exec erpnext-prod-backend-1 rm -f /home/frappe/frappe-bench/sites/assets/erpnext
    docker exec erpnext-prod-backend-1 cp -r /home/frappe/frappe-bench/apps/erpnext/erpnext/public /home/frappe/frappe-bench/sites/assets/erpnext
    docker exec erpnext-prod-backend-1 rm -f /home/frappe/frappe-bench/sites/assets/umre_ops
    docker exec erpnext-prod-backend-1 cp -r /home/frappe/frappe-bench/apps/umre_ops/umre_ops/public /home/frappe/frappe-bench/sites/assets/umre_ops
fi

# 3. Nginx / Frontend servisinin hazır olmasını bekle
echo -n "Servislerin hazır olması bekleniyor"
until docker exec erpnext-prod-frontend-1 nginx -t >/dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e "\n${GREEN}[+] Tüm servisler aktif ve hazır!${NC}"

# Nginx DNS/Upstream önbelleğini yenilemek için reload tetikle (502 Bad Gateway koruması)
docker exec erpnext-prod-frontend-1 nginx -s reload >/dev/null 2>&1 || true

# 4. Tarayıcıda muhasebe arayüzünü aç
echo -e "${BLUE}[*] Tarayıcıda arayüz açılıyor...${NC}"
open "http://localhost:8080"

echo -e "${GREEN}======================================================${NC}"
echo -e "${GREEN}   Sistem Aktif! Kullanıcı adı: Administrator         ${NC}"
echo -e "${GREEN}   Tarayıcı Adresi: http://localhost:8080            ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "${YELLOW}   UYARI: Docker'ı durdurmak için bu terminali       ${NC}"
echo -e "${YELLOW}   kapatmayın. Aşağıdaki yönergeyi izleyin.          ${NC}"
echo -e "${GREEN}======================================================${NC}"

# 5. Çıkış yönergesi
read -p "Sistemi durdurmak ve Docker Desktop'ı kapatmak için [ENTER] tuşuna basın..."

echo -e "\n${BLUE}[*] Muhasebe servisleri durduruluyor (Konteynerler temizleniyor)...${NC}"
docker compose -f "$COMPOSE_FILE" down

echo -e "${BLUE}[*] Docker Desktop kapatılıyor...${NC}"
osascript -e 'quit app "Docker"'

echo -e "${GREEN}[+] Muhasebe platformu güvenle kapatıldı. Bilgisayarınız artık yorulmayacak!${NC}"
echo -e "${BLUE}======================================================${NC}"
