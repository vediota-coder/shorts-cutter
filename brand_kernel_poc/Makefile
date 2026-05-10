PYTHON ?= ../.venv/bin/python

.PHONY: all keys build license assets demo tamper clean

all: build

# 1. одноразово: генерируем RSA пару и вшиваем pubkey в .pyx
keys:
	$(PYTHON) tools/make_keys.py

# 2. собираем .pyx → .so
build:
	$(PYTHON) setup.py build_ext --inplace

# 3. выпускаем лицензию для текущей машины (демо)
license:
	@FP=$$($(PYTHON) -c "from brand_kernel import get_machine_fp; print(get_machine_fp())"); \
	echo "machine_fp: $$FP"; \
	$(PYTHON) tools/make_license.py \
		--customer "ACME Corp" \
		--machine-fp $$FP \
		--tier standard --days 365 \
		--out dist/ACME_license

# 4. шифруем ассеты для ACME
assets:
	$(PYTHON) tools/encrypt_assets.py \
		--license dist/ACME_license.json \
		--asset ../branding/_assets/excella.png \
		--asset ../branding/excella.json \
		--out dist/ACME_assets/

demo: build license assets
	$(PYTHON) tests/demo_normal.py

tamper: demo
	$(PYTHON) tests/demo_tamper.py

clean:
	rm -rf build/ dist/ACME_* dist/EVIL_* dist/FAKE_*
	rm -f brand_kernel/_kernel.c brand_kernel/*.so
	rm -rf brand_kernel/__pycache__/
