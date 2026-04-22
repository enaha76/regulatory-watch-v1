.PHONY: up down logs migrate test shell clean

# ── Docker Compose ───────────────────────────────────────
up:
	docker compose up -d --build
	@echo "✅ Stack is starting..."
	@echo "   API:    http://localhost:8001"
	@echo "   Docs:   http://localhost:8001/docs"
	@echo "   Flower: http://localhost:5555"

down:
	docker compose down

clean:
	docker compose down -v --remove-orphans
	@echo "🧹 Volumes and orphans removed"

logs:
	docker compose logs -f --tail=50

logs-api:
	docker compose logs -f api --tail=50

logs-worker:
	docker compose logs -f worker --tail=50

# ── Database ─────────────────────────────────────────────
migrate:
	docker compose exec api alembic upgrade head

migrate-generate:
	docker compose exec api alembic revision --autogenerate -m "$(msg)"

# ── Development ──────────────────────────────────────────
shell:
	docker compose exec api bash

test:
	@echo "🧪 Running smoke tests..."
	@echo "\n--- Health Check ---"
	@curl -s http://localhost:8001/health | python3 -m json.tool
	@echo "\n--- DB Health ---"
	@curl -s http://localhost:8001/health/db | python3 -m json.tool
	@echo "\n--- Redis Health ---"
	@curl -s http://localhost:8001/health/redis | python3 -m json.tool
	@echo "\n--- Create Domain ---"
	@curl -s -X POST http://localhost:8001/domains \
		-H "Content-Type: application/json" \
		-d '{"domain":"cbp.gov","seed_urls":["https://www.cbp.gov/trade/rulings"]}' \
		| python3 -m json.tool
	@echo "\n--- List Domains ---"
	@curl -s http://localhost:8001/domains | python3 -m json.tool
	@echo "\n✅ Smoke tests complete!"

status:
	@docker compose ps
