.PHONY: setup db-up db-down init collect-once collect status scan dashboard test

setup:            ## Virtuelle Umgebung und Abhängigkeiten
	python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

db-up:            ## Datenbank starten (Docker)
	docker compose -f infra/docker-compose.yml up -d

db-down:
	docker compose -f infra/docker-compose.yml down

init:             ## Schema einspielen (idempotent)
	python scripts/init_db.py

collect-once:     ## Ein Collector-Durchlauf
	python -m collectors.run --once

collect:          ## Collector im Intervall
	python -m collectors.run

status:           ## Was ist in der Datenbank?
	python scripts/status.py

scan:             ## Valuebets und Surebets aus den gespeicherten Quoten suchen
	python scripts/scan.py

closing:          ## Schlussquoten sichern, CLV der eigenen Wetten berechnen und auswerten
	python scripts/closing.py --report

ai-assess:        ## KI: aktuelle Treffer einordnen (braucht ANTHROPIC_API_KEY)
	python scripts/ai_report.py --assess

ai-weekly:        ## KI: Wochenbericht
	python scripts/ai_report.py --weekly

dashboard:        ## Dashboard im Browser (http://localhost:8501)
	streamlit run dashboard/app.py

test:
	pytest -q
