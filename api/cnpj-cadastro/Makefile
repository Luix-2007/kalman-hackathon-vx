.PHONY: build deploy clean

build:
	sam build

deploy: build
	sam deploy

clean:
	rm -rf .aws-sam
