TF := terraform -chdir=terraform

.PHONY: build deploy bootstrap backfill url test lint destroy

build:
	python3 scripts/build.py

deploy: build
	$(TF) init -upgrade
	$(TF) apply

bootstrap:
	python3 scripts/bootstrap_garmin_auth.py --parameter $$($(TF) output -raw garmin_tokens_parameter) --region $$($(TF) output -raw aws_region)

backfill:
	python3 scripts/backfill.py --function $$($(TF) output -raw gateway_function_name) --region $$($(TF) output -raw aws_region) --days $${DAYS:-180}

url:
	@$(TF) output -raw mcp_connector_url; echo

test:
	python3 -m pytest -q

lint:
	ruff check app tests scripts
	$(TF) fmt -check -recursive

destroy:
	$(TF) destroy
