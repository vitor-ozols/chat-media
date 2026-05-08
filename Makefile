IMAGE ?= chat-media
CONTAINER ?= chat-media
PORT ?= 8501
DATA_DIR ?= $(CURDIR)/data
MUSIC_DIR ?= $(CURDIR)/media/music
MOVIES_DIR ?= $(CURDIR)/media/movies
DOWNLOADS_DIR ?= $(CURDIR)/downloads
ENV_FILE ?= $(CURDIR)/.env
ENV_ARGS = $(if $(wildcard $(ENV_FILE)),--env-file "$(ENV_FILE)",-e GEMINI_API_KEY)

.PHONY: build start stop logs shell remove

build:
	mkdir -p "$(DATA_DIR)" "$(MUSIC_DIR)" "$(MOVIES_DIR)" "$(DOWNLOADS_DIR)"
	docker build -t $(IMAGE) .

start: build
	docker run -d --rm --name $(CONTAINER) -p $(PORT):8501 \
		$(ENV_ARGS) \
		-v "$(DATA_DIR):/app/data" \
		-v "$(MUSIC_DIR):/app/media/music" \
		-v "$(MOVIES_DIR):/app/media/movies" \
		-v "$(DOWNLOADS_DIR):/app/downloads" \
		$(IMAGE)

stop:
	-docker stop $(CONTAINER)

logs:
	docker logs -f $(CONTAINER)

shell:
	docker exec -it $(CONTAINER) bash

remove:
	-docker rm -f $(CONTAINER)
