IMAGE ?= media-control
CONTAINER ?= media-control
PORT ?= 8501
BASE_PATH ?= media
DATA_DIR ?= $(CURDIR)/data
MUSIC_DIR ?= /mnt/sata/musics
MOVIES_DIR ?= $(CURDIR)/media/movies
DOWNLOADS_DIR ?= $(CURDIR)/downloads

.PHONY: build start stop logs shell remove

build:
	mkdir -p "$(DATA_DIR)" "$(MUSIC_DIR)" "$(MOVIES_DIR)" "$(DOWNLOADS_DIR)"
	docker build -t $(IMAGE) .

start: build
	-docker rm -f $(CONTAINER)
	docker run -d --name $(CONTAINER) --restart unless-stopped -p $(PORT):8501 \
		-e STREAMLIT_SERVER_BASE_URL_PATH="$(BASE_PATH)" \
		-e GEMINI_API_KEY \
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
