#!/usr/bin/env bash
# =====================================================
# adidas Knowledge Hub — 一键部署脚本
# 在 Ubuntu 20.04+/Debian 12 云服务器上以 root 运行
#
# 用法:
#   export DEEPSEEK_API_KEY=sk-xxxx && sudo -E ./deploy.sh
#   或者交互式输入 Key
# =====================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
die()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

DOMAIN="${DOMAIN:-}"
DEPLOY_USER="deploy"
PROJECT_DIR="/home/${DEPLOY_USER}/adidas-gbrain-v2"
GBRAIN_DIR="/home/${DEPLOY_USER}/gbrain"
GBRAIN_HOME="/home/${DEPLOY_USER}/.gbrain-adidas-v2"

echo "============================================"
echo " adidas Knowledge Hub — 公网部署"
echo "============================================"
echo ""

[ "$EUID" -eq 0 ] || die "请以 root 运行: sudo -E ./deploy.sh"

# ── Step 1 ──
info "Step 1/7: 安装系统依赖..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx certbot python3-certbot-nginx curl unzip git build-essential rsync

# ── Step 2 ──
info "Step 2/7: 安装 Bun..."
export BUN_INSTALL=/usr/local
if ! command -v bun &>/dev/null; then
    curl -fsSL https://bun.sh/install | bash
fi
su - "$DEPLOY_USER" -c 'curl -fsSL https://bun.sh/install | bash' 2>/dev/null || true

# ── Step 3 ──
info "Step 3/7: 创建部署用户..."
id "$DEPLOY_USER" &>/dev/null || useradd -m -s /bin/bash "$DEPLOY_USER"
mkdir -p "$PROJECT_DIR" "$GBRAIN_HOME"

# ── Step 4 ──
info "Step 4/7: 部署项目代码..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_SRC="$(dirname "$SCRIPT_DIR")"
if [ -f "$PROJECT_SRC/server.py" ]; then
    info "从 $PROJECT_SRC 复制..."
    rsync -a \
        --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
        --exclude 'raw/articles/_uploads/_archived' \
        --exclude '.ingest-queue.json' --exclude '.upload-history.json' \
        --exclude '.ingest-status.json' --exclude '.manifest.json' \
        --exclude '_proposals' --exclude '_backups' --exclude '.gitignore' \
        "$PROJECT_SRC/" "$PROJECT_DIR/"
else
    warn "未找到项目源。请手动 rsync 到 $PROJECT_DIR"
fi

# ── Step 5 ──
info "Step 5/7: 安装 gbrain..."
if [ ! -d "$GBRAIN_DIR" ]; then
    su - "$DEPLOY_USER" -c "git clone https://github.com/garrytan/gbrain.git $GBRAIN_DIR"
fi
su - "$DEPLOY_USER" -c "cd $GBRAIN_DIR && bun install && bun link"

# ── Step 6 ──
pip3 install jieba requests --break-system-packages 2>/dev/null || pip3 install jieba requests

# ── Step 7 ──
info "Step 7/7: 配置并启动..."

# 7a. 环境变量
ENV_FILE="$PROJECT_DIR/deploy/.env.production"
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo -n "DeepSeek API Key (sk-...): "
    read -r DEEPSEEK_API_KEY
fi
printf 'PORT=8767\nREAD_ONLY=true\nQA_RATE_LIMIT=10\nDEEPSEEK_API_KEY=%s\n' "$DEEPSEEK_API_KEY" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV_FILE"
info ".env.production 已配置"

# 7b. 修复 server.py 路径 (Mac → Linux)
SERVER_PY="$PROJECT_DIR/server.py"
sed -i "s|BASE = .*|BASE = \"${PROJECT_DIR}\"|" "$SERVER_PY"
sed -i "s|GBRAIN_CLI = .*|GBRAIN_CLI = \"${GBRAIN_DIR}/src/cli.ts\"|" "$SERVER_PY"
sed -i "s|GBRAIN_HOME\": .*|GBRAIN_HOME\": \"${GBRAIN_HOME}\"|" "$SERVER_PY"
sed -i "s|BUN = .*|BUN = '/usr/local/bin/bun'|" "$SERVER_PY"

# 7c. nginx
cp "$PROJECT_DIR/deploy/nginx-site.conf" /etc/nginx/sites-available/adidas-hub
if [ -n "$DOMAIN" ]; then
    sed -i "s/server_name _;/server_name ${DOMAIN};/g" /etc/nginx/sites-available/adidas-hub
    sed -i "s|adidas-hub/|${DOMAIN}/|g" /etc/nginx/sites-available/adidas-hub
fi
ln -sf /etc/nginx/sites-available/adidas-hub /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t || die "nginx 配置错误"
systemctl reload nginx

if [ -n "$DOMAIN" ]; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        --email "admin@${DOMAIN}" --redirect 2>/dev/null || \
        warn "SSL 申请失败，可稍后: certbot --nginx -d $DOMAIN"
fi

# 7d. systemd
cp "$PROJECT_DIR/deploy/adidas-hub.service" /etc/systemd/system/
systemctl daemon-reload
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$PROJECT_DIR" "$GBRAIN_HOME"

# 7e. gbrain init
su - "$DEPLOY_USER" -c "cd $PROJECT_DIR && DATABASE_URL='' GBRAIN_HOME=$GBRAIN_HOME bun run $GBRAIN_DIR/src/cli.ts init --yes" 2>/dev/null || warn "gbrain init 失败"
info "导入知识库索引..."
su - "$DEPLOY_USER" -c "cd $PROJECT_DIR && DATABASE_URL='' GBRAIN_HOME=$GBRAIN_HOME python3 regenerate-graph.py" 2>/dev/null || warn "索引导入失败，可稍后手动运行"

# 启动
systemctl enable --now adidas-hub
sleep 2

# ── 验证 ──
echo ""
echo "============================================"
echo " 部署完成！"
echo "============================================"
systemctl is-active --quiet adidas-hub && info "adidas-hub 运行中" || warn "服务未启动 → sudo journalctl -u adidas-hub -n 30"
systemctl is-active --quiet nginx && info "nginx 运行中" || warn "nginx 未启动"

SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_IP")
if [ -n "$DOMAIN" ]; then
    echo -e "${GREEN}📍 https://${DOMAIN}/product-hub.html${NC}"
else
    echo -e "${GREEN}📍 http://${SERVER_IP}/product-hub.html${NC}"
fi

echo ""
echo "常用管理命令:"
echo "  日志: sudo journalctl -u adidas-hub -f"
echo "  重启: sudo systemctl restart adidas-hub"
echo "  状态: sudo systemctl status adidas-hub"
echo "  编辑环境变量: sudo vi $ENV_FILE && sudo systemctl restart adidas-hub"
