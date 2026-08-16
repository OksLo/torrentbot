GPU_OVERRIDE := $(shell [ -d /dev/dri ] && echo '-f docker-compose.gpu.yml')
export RENDER_GID := $(shell getent group render | cut -d: -f3)
export VIDEO_GID  := $(shell getent group video  | cut -d: -f3)

up:
	docker compose -f docker-compose.yml $(GPU_OVERRIDE) up -d

down:
	docker compose down

logs:
	docker compose logs -f

bot-logs:
	docker compose logs -f telegram-bot

restart-bot:
	docker compose restart telegram-bot

upgrade:
	docker compose -f docker-compose.yml $(GPU_OVERRIDE) pull
	docker compose -f docker-compose.yml $(GPU_OVERRIDE) up -d --force-recreate --remove-orphans
