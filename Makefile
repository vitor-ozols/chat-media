SERVICE ?= app
CONTAINER ?= chat-media
BASE_PATH ?= chat
DATA_DIR ?= $(CURDIR)/data
MUSIC_DIR ?= /mnt/sata/musics
MOVIES_DIR ?= /mnt/sata/streamlito/downloads
DOWNLOADS_DIR ?= $(CURDIR)/downloads

.PHONY: build start stop restart logs shell remove ps

build:
	mkdir -p "$(DATA_DIR)" "$(MUSIC_DIR)" "$(MOVIES_DIR)" "$(DOWNLOADS_DIR)"
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	docker compose build $(SERVICE)

start:
	mkdir -p "$(DATA_DIR)" "$(MUSIC_DIR)" "$(MOVIES_DIR)" "$(DOWNLOADS_DIR)"
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	docker compose up -d --build $(SERVICE)

stop:
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	docker compose stop $(SERVICE)

restart:
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	docker compose restart $(SERVICE)

logs:
	docker logs -f $(CONTAINER)

shell:
	docker exec -it $(CONTAINER) bash

remove:
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	docker compose rm -sf $(SERVICE)

ps:
	docker ps --filter name=$(CONTAINER)
