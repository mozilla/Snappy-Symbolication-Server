DOCKERCOMPOSE = $(shell which docker-compose)

default:
	@echo "You need to specify a subcommand."
	@exit 1

help:
	@echo "build         - build docker containers for dev"
	@echo "run           - docker-compose up the entire system for dev"
	@echo ""
	@echo "clean         - remove all build, test, coverage and Python artifacts"
	@echo "lint          - check style with flake8"
	@echo "test          - run tests"

# Dev configuration steps
.docker-build:
	make build

build:
	${DOCKERCOMPOSE} build
	touch .docker-build

run: .docker-build
	-mkdir docker-state && chmod 777 docker-state
	${DOCKERCOMPOSE} up

clean:
	-${DOCKERCOMPOSE} run web rm -rf docker-state/*
	-rm -rf docker-state

lint:
	${DOCKERCOMPOSE} run web flake8 --ignore=E111,E114,E121,E127,E128,E251,E261,E241,E302,E501,W291,W293 snappy/

test:
	${DOCKERCOMPOSE} run web python runTests.py

.PHONY: default clean build lint run test
