GPU_OVERRIDE := $(shell [ -d /dev/dri ] && echo '-f docker-compose.gpu.yml')

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
