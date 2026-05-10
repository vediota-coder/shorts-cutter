#!/usr/bin/env bash
# excella shorts-cutter — installer
#
# Использование:
#   curl -fsSL https://get.excella.ru/install.sh | bash
#   curl -fsSL https://get.excella.ru/install.sh | bash -s -- --channel=stable
#
# Что делает:
#   1. Определяет платформу (uname)
#   2. Проверяет prerequisites (Docker или системный package manager)
#   3. Скачивает docker-compose.yml + wrapper-скрипт excella из GitHub Releases
#   4. Создаёт ~/.excella/
#   5. Регистрирует команду excella в /usr/local/bin
#   6. Подсказывает следующий шаг: excella init
#
# Безопасность: скрипт распространяется через TLS-only (https://get.excella.ru)
# с подписью GPG. Проверьте подпись прежде чем запускать
# (см. https://docs.excella.ru/install/verify).

set -eu

# ────────────────────────────────────────────────────
# Конфигурация
# ────────────────────────────────────────────────────
readonly REPO="excella/shorts-cutter"
readonly INSTALL_DIR="${EXCELLA_INSTALL_DIR:-$HOME/.excella}"
readonly BIN_DIR="${EXCELLA_BIN_DIR:-/usr/local/bin}"
readonly CHANNEL="${CHANNEL:-stable}"

# Цвета терминала.
if [ -t 1 ]; then
    readonly C_GREEN=$'\033[0;32m'
    readonly C_RED=$'\033[0;31m'
    readonly C_YELLOW=$'\033[0;33m'
    readonly C_BLUE=$'\033[0;34m'
    readonly C_RESET=$'\033[0m'
else
    readonly C_GREEN='' C_RED='' C_YELLOW='' C_BLUE='' C_RESET=''
fi

log()   { echo "${C_BLUE}[*]${C_RESET} $*"; }
ok()    { echo "${C_GREEN}[✓]${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}[!]${C_RESET} $*"; }
fatal() { echo "${C_RED}[✗]${C_RESET} $*" >&2; exit 1; }


# ────────────────────────────────────────────────────
# Платформа
# ────────────────────────────────────────────────────
detect_platform() {
    local os arch
    case "$(uname -s)" in
        Darwin*) os="darwin" ;;
        Linux*)  os="linux" ;;
        MINGW*|MSYS*|CYGWIN*) os="windows" ;;
        *)       fatal "Неподдерживаемая ОС: $(uname -s). Используйте Docker." ;;
    esac
    case "$(uname -m)" in
        x86_64|amd64) arch="x86_64" ;;
        arm64|aarch64) arch="arm64" ;;
        *) fatal "Неподдерживаемая архитектура: $(uname -m)" ;;
    esac
    echo "${os}-${arch}"
}


# ────────────────────────────────────────────────────
# Проверка зависимостей
# ────────────────────────────────────────────────────
check_command() {
    command -v "$1" >/dev/null 2>&1 || return 1
    return 0
}

check_docker() {
    if ! check_command docker; then
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        warn "Docker установлен, но daemon недоступен. Запустите Docker Desktop."
        return 1
    fi
    return 0
}


# ────────────────────────────────────────────────────
# Установка через Docker (рекомендуется)
# ────────────────────────────────────────────────────
install_docker() {
    log "режим: Docker"

    mkdir -p "$INSTALL_DIR"

    # docker-compose.yml
    local compose_url="https://github.com/${REPO}/releases/latest/download/docker-compose.yml"
    log "качаю docker-compose.yml с $compose_url"
    if ! curl -fsSL "$compose_url" -o "$INSTALL_DIR/docker-compose.yml"; then
        warn "не удалось скачать релизный compose-файл, пробую main"
        curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/docker-compose.yml" \
             -o "$INSTALL_DIR/docker-compose.yml" \
             || fatal "не удалось скачать docker-compose.yml"
    fi

    # wrapper-скрипт `excella`
    install_wrapper docker
    ok "Docker mode: команда 'excella' установлена в $BIN_DIR"
}


# ────────────────────────────────────────────────────
# Установка native (опц., если нет Docker)
# ────────────────────────────────────────────────────
install_native() {
    local platform="$1"
    log "режим: native ($platform)"

    case "$platform" in
        darwin-arm64|darwin-x86_64)
            warn "На macOS рекомендуется через Homebrew:"
            echo "    brew install excella/tap/shorts-cutter"
            warn "Альтернатива — Docker (см. https://docs.excella.ru/install/docker)"
            exit 1
            ;;
        linux-x86_64)
            install_linux_pkg
            ;;
        *)
            fatal "Native install не реализован для $platform — используйте Docker"
            ;;
    esac
}

install_linux_pkg() {
    if check_command apt; then
        local deb_url="https://github.com/${REPO}/releases/latest/download/excella-cutter_amd64.deb"
        log "качаю .deb с $deb_url"
        local tmp_deb
        tmp_deb=$(mktemp -d)/excella.deb
        curl -fsSL "$deb_url" -o "$tmp_deb" \
            || fatal "не удалось скачать .deb"
        sudo apt install -y "$tmp_deb"
        rm -rf "$(dirname "$tmp_deb")"
    elif check_command dnf; then
        local rpm_url="https://github.com/${REPO}/releases/latest/download/excella-cutter.x86_64.rpm"
        log "ставлю .rpm с $rpm_url"
        sudo dnf install -y "$rpm_url"
    else
        fatal "На вашем Linux нет apt и dnf — используйте Docker"
    fi
}


# ────────────────────────────────────────────────────
# Wrapper-скрипт excella
# ────────────────────────────────────────────────────
install_wrapper() {
    local mode="$1"   # docker | native
    local wrapper
    wrapper=$(mktemp)
    cat > "$wrapper" <<EOF
#!/usr/bin/env bash
# excella CLI — wrapper над docker compose / native.
# Создан install.sh, mode=$mode.
set -eu
EXCELLA_HOME="\${EXCELLA_HOME:-$INSTALL_DIR}"
cd "\$EXCELLA_HOME"

case "\${1:-help}" in
    init)         shift; exec python3 -c "import urllib.request, json; \\
                  print('запустите: docker compose run --rm shorts-cutter python scripts/excella_init.py')";;
    start|up)     docker compose up -d ;;
    stop|down)    docker compose stop ;;
    restart)      docker compose restart ;;
    logs)         shift; docker compose logs -f "\$@" ;;
    status)       docker compose ps ;;
    update)       docker compose pull && docker compose up -d ;;
    server)       docker compose up ;;
    debug-info)   docker compose config && docker compose ps && docker compose logs --tail 100 ;;
    *)
        cat <<HELP
excella shorts-cutter ($mode)

Команды:
  excella init              регистрация лицензии
  excella start             поднять сервис в фоне
  excella stop              остановить
  excella restart           перезапустить
  excella status            статус контейнера
  excella logs              tail логов
  excella update            pull новый образ + restart
  excella server            запустить в foreground
  excella debug-info        собрать диагностику

UI: http://localhost:8000
HELP
        ;;
esac
EOF
    chmod +x "$wrapper"
    if [ -w "$BIN_DIR" ]; then
        mv "$wrapper" "$BIN_DIR/excella"
    else
        sudo mv "$wrapper" "$BIN_DIR/excella"
    fi
}


# ────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────
main() {
    log "excella shorts-cutter installer"
    local platform
    platform=$(detect_platform)
    ok "платформа: $platform"

    mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/jobs" "$INSTALL_DIR/output" \
             "$INSTALL_DIR/downloads" "$INSTALL_DIR/assets"

    if check_docker; then
        install_docker
    else
        warn "Docker не найден или не запущен."
        warn "Альтернатива — native install (только Linux deb/rpm)."
        read -r -p "Поставить native? [y/N] " ans
        case "$ans" in
            y|Y|yes|YES) install_native "$platform" ;;
            *) echo "Установите Docker Desktop: https://docs.docker.com/get-docker/"; exit 1 ;;
        esac
    fi

    echo
    ok "установка завершена"
    echo
    echo "Дальше:"
    echo "  ${C_GREEN}excella init${C_RESET}     # регистрация бесплатной лицензии"
    echo "  ${C_GREEN}excella start${C_RESET}    # запуск сервиса"
    echo "  ${C_GREEN}open http://localhost:8000${C_RESET}"
}

main "$@"
