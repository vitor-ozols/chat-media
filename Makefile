SERVICE ?= app
CONTAINER ?= chat-media
BASE_PATH ?= chat
DATA_DIR ?= $(CURDIR)/data
MUSIC_DIR ?= /mnt/sata/musics
MOVIES_DIR = /mnt/sata/movies
DOWNLOADS_DIR ?= $(CURDIR)/downloads
DOCKER ?= sudo docker

.PHONY: build start up stop restart logs shell remove ps

build:
	mkdir -p "$(DATA_DIR)" "$(MUSIC_DIR)" "$(MOVIES_DIR)" "$(DOWNLOADS_DIR)"
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	$(DOCKER) compose build $(SERVICE)

start:
	mkdir -p "$(DATA_DIR)" "$(MUSIC_DIR)" "$(MOVIES_DIR)" "$(DOWNLOADS_DIR)"
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	$(DOCKER) compose up -d --build $(SERVICE)

up: start

stop:
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	$(DOCKER) compose stop $(SERVICE)

restart:
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	$(DOCKER) compose restart $(SERVICE)

logs:
	$(DOCKER) logs -f $(CONTAINER)

shell:
	$(DOCKER) exec -it $(CONTAINER) bash

remove:
	DATA_DIR="$(DATA_DIR)" \
	MUSIC_DIR="$(MUSIC_DIR)" \
	MOVIES_DIR="$(MOVIES_DIR)" \
	DOWNLOADS_DIR="$(DOWNLOADS_DIR)" \
	BASE_PATH="$(BASE_PATH)" \
	$(DOCKER) compose rm -sf $(SERVICE)

ps:
	$(DOCKER) ps --filter name=$(CONTAINER)
